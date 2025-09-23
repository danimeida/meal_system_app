from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required
from werkzeug.security import check_password_hash
from models import db, User, Meal, Reservation, Attendance

# Timezone da app
APP_TZ = ZoneInfo("Europe/Bucharest")

# dias da semana em PT
WEEKDAYS_PT = ['segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado', 'domingo']

# janela de validação do quiosque
WINDOW_BEFORE = timedelta(minutes=60)
WINDOW_AFTER  = timedelta(minutes=90)

# sessão de marcação: tempo máximo de inatividade
MARK_SESSION_TTL = timedelta(minutes=60)


def in_window_for(day, meal_time, now=None):
    """Verifica se AGORA está dentro da janela da refeição (no fuso APP_TZ) para a data `day`."""
    if now is None:
        now = datetime.now(APP_TZ)
    start = datetime.combine(day, meal_time, tzinfo=APP_TZ) - WINDOW_BEFORE
    end   = datetime.combine(day, meal_time, tzinfo=APP_TZ) + WINDOW_AFTER
    return start <= now <= end



def is_locked(day, meal_time, now=None, hours=48):
    if now is None:
        now = datetime.now(APP_TZ)
    meal_dt = datetime.combine(day, meal_time, tzinfo=APP_TZ)
    return (meal_dt - now) < timedelta(hours=hours)


def _mark_session_user_id():
    """Devolve o user_id autenticado para marcação, ou None se expirou/inválido."""
    uid = session.get('mark_user_id')
    exp_ts = session.get('mark_expires_ts')
    if not uid or not exp_ts:
        return None
    # expiração
    now_ts = datetime.now(APP_TZ).timestamp()
    if now_ts > float(exp_ts):
        # expirada
        session.pop('mark_user_id', None)
        session.pop('mark_expires_ts', None)
        return None
    return int(uid)


def _refresh_mark_session():
    """Renova o TTL enquanto o utilizador navega na área de marcação."""
    session['mark_expires_ts'] = (datetime.now(APP_TZ) + MARK_SESSION_TTL).timestamp()


bp = Blueprint('routes', __name__)


@bp.route('/')
def index():
    # Página de entrada com form para user_id + pin
    return render_template('index.html')


# ---- LOGIN/LOGOUT DA MARCAÇÃO (usa sessão) ----

@bp.route('/mark/login', methods=['POST'])
def mark_login():
    """Valida PIN e cria sessão de marcação sem expor o PIN no URL."""
    # Lido sempre do POST do index.html
    user_id_raw = request.form.get('user_id')
    pin = request.form.get('pin', '').strip()

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return render_template('index.html', error='Número inválido')

    user = User.query.get(user_id)
    if not user:
        return render_template('index.html', error='Utilizador não existe')

    if not pin or not user.pin_hash or not check_password_hash(user.pin_hash, pin):
        return render_template('index.html', error='PIN inválido')

    # OK → cria sessão
    session['mark_user_id'] = user_id
    _refresh_mark_session()

    # vai para a área de marcação sem PIN no URL
    return redirect(url_for('routes.mark'))


@bp.route('/mark/logout')
def mark_logout():
    session.pop('mark_user_id', None)
    session.pop('mark_expires_ts', None)
    flash('Terminaste a sessão de marcação.', 'info')
    return redirect(url_for('routes.index'))


# ---- MARCAÇÃO (listagem/edição) ----

@bp.route('/mark', methods=['GET', 'POST'])
def mark():
    # Autenticação por sessão
    user_id = _mark_session_user_id()
    if not user_id:
        return render_template('index.html', error='Sessão expirada. Faz login novamente.')

    user = User.query.get(user_id)
    if not user:
        # user foi removido mean time
        session.pop('mark_user_id', None)
        session.pop('mark_expires_ts', None)
        return render_template('index.html', error='Utilizador não existe')

    meals = Meal.query.order_by(Meal.id).all()
    now = datetime.now(APP_TZ)
    today = now.date()
    days = [(today + timedelta(days=i)) for i in range(0, 14)]

    # OPT-OUT: linha existente = cancelado
    existing = Reservation.query.filter_by(user_id=user_id).all()
    canceled_set = {(r.date, r.meal_id) for r in existing}

    # (dia, meal_id) bloqueados pelas 48h
    locked_set = {
        (d, meal.id)
        for d in days
        for meal in meals
        if is_locked(d, meal.scheduled_time, now=now)
    }

    if request.method == 'POST':
        # Form da própria página mark.html
        selected = set(request.form.getlist('reservation'))  # "YYYY-MM-DD_mealId"

        for d in days:
            for meal in meals:
                key = f"{d}_{meal.id}"
                if (d, meal.id) in locked_set:
                    continue  # não mexe < 48h

                wants_attend = key in selected
                is_canceled = (d, meal.id) in canceled_set

                if wants_attend and is_canceled:
                    # remover cancelamento
                    res = Reservation.query.filter_by(user_id=user_id, meal_id=meal.id, date=d).first()
                    if res:
                        db.session.delete(res)

                elif (not wants_attend) and (not is_canceled):
                    # criar cancelamento
                    db.session.add(Reservation(user_id=user_id, meal_id=meal.id, date=d))

        try:
            db.session.commit()
            flash('Preferências atualizadas!', 'success')
        except Exception:
            db.session.rollback()
            flash('Ocorreu um erro ao gravar. Tenta novamente.', 'danger')

        # renova TTL e volta à página
        _refresh_mark_session()
        return redirect(url_for('routes.mark'))

    # GET → mostra tabela
    _refresh_mark_session()
    return render_template(
        'mark.html',
        user_id=user_id,
        meals=meals,
        days=days,
        canceled_set=canceled_set,
        locked_set=locked_set,
        weekdays=WEEKDAYS_PT
    )


# ---- QUIOSQUE ----

@bp.route('/kiosk', methods=['GET', 'POST'])
@login_required  # só admins autenticados
def kiosk():
    meals = Meal.query.order_by(Meal.id).all()
    result = None
    msg = None

    # Determina refeição “corrente” para mostrar ao operador
    now_utc = datetime.now(timezone.utc)
    today = now_utc.date()

    current_meal = None
    for m in meals:
        if in_window(m.scheduled_time, now=now_utc):
            current_meal = m
            break

    if request.method == 'POST':
        try:
            user_id = int(request.form['user_id'])
        except (KeyError, ValueError):
            user_id = None

        # Se houver um <select> para forçar a refeição, respeita-o; senão usa a current_meal
        try:
            posted_meal_id = int(request.form.get('meal_id') or 0)
        except ValueError:
            posted_meal_id = 0

        meal = Meal.query.get(posted_meal_id) if posted_meal_id else current_meal

        if not user_id or not meal:
            result, msg = 'red', 'Dados inválidos.'
        else:
            canceled = Reservation.query.filter_by(
                user_id=user_id, meal_id=meal.id, date=today
            ).first() is not None
            if canceled:
                result, msg = 'red', 'Reserva cancelada.'
            elif not in_window(meal.scheduled_time, now=now_utc):
                result, msg = 'red', 'Fora da janela de validação.'
            else:
                existing = Attendance.query.filter_by(
                    user_id=user_id, meal_id=meal.id, date=today
                ).first()
                if not existing:
                    try:
                        db.session.add(Attendance(user_id=user_id, meal_id=meal.id, date=today))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        result, msg = 'red', 'Erro ao registar presença.'
                        return render_template('kiosk.html', meals=meals, result=result, msg=msg,
                                               current_meal=current_meal, today=today)
                result, msg = 'green', 'Presença registada.'

    return render_template('kiosk.html', meals=meals, result=result, msg=msg,
                           current_meal=current_meal, today=today)


# ---- DASHBOARD ADMIN ----

@bp.route('/admin')
@login_required
def admin_dashboard():
    date_str = request.args.get('date')
    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
    except ValueError:
        day = datetime.now().date()

    from sqlalchemy import func
    total_users = db.session.query(func.count(User.id)).scalar() or 0

    canceled = dict(
        db.session.query(Reservation.meal_id, func.count(Reservation.id))
        .filter(Reservation.date == day)
        .group_by(Reservation.meal_id)
        .all()
    )
    present = dict(
        db.session.query(Attendance.meal_id, func.count(Attendance.id))
        .filter(Attendance.date == day)
        .group_by(Attendance.meal_id)
        .all()
    )

    cards = []
    for meal in Meal.query.order_by(Meal.id).all():
        c = canceled.get(meal.id, 0)
        p = present.get(meal.id, 0)
        expected = total_users - c
        absences = max(expected - p, 0)
        faltas_pct = round(100.0 * absences / expected, 1) if expected else 0.0
        cards.append({
            "meal": meal, "total": total_users, "canceled": c,
            "present": p, "expected": expected, "absences": absences,
            "faltas_pct": faltas_pct
        })

    reservations = (
        db.session.query(Reservation, Meal)
        .join(Meal, Reservation.meal_id == Meal.id)
        .filter(Reservation.date == day)
        .order_by(Meal.id, Reservation.user_id)
        .all()
    )

    return render_template('admin_dashboard.html', day=day, cards=cards, reservations=reservations)


@bp.route('/admin/absences')
@login_required
def admin_absences():
    date_str = request.args.get('date')
    meal_id = request.args.get('meal_id', type=int)
    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now().date()
    except ValueError:
        day = datetime.now().date()

    meal = Meal.query.get(meal_id)
    if not meal:
        flash('Refeição inválida', 'danger')
        return redirect(url_for('routes.admin_dashboard', date=day.strftime('%Y-%m-%d')))

    canceled_users = {
        r.user_id for r in Reservation.query.with_entities(Reservation.user_id)
        .filter_by(date=day, meal_id=meal_id).all()
    }
    all_users = {u.id for u in User.query.with_entities(User.id).all()}
    expected_users = all_users - canceled_users

    present_users = {
        a.user_id for a in Attendance.query.with_entities(Attendance.user_id)
        .filter_by(date=day, meal_id=meal_id).all()
    }

    absent_users = sorted(expected_users - present_users)
    return render_template('admin_absences.html', day=day, meal=meal, absent_users=absent_users)
