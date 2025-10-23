from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from models import db, User, Meal, Reservation, Attendance
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash



bp = Blueprint('routes', __name__)

# Timezone da aplicação (Bucareste)
APP_TZ = ZoneInfo("Europe/Bucharest")

# Dias da semana em PT (0=segunda ... 6=domingo)
WEEKDAYS_PT = ['SEG', 'TER', 'QUA', 'QUI', 'SEX', 'SAB', 'DOM']

# Janela de validação do quiosque
WINDOW_BEFORE = timedelta(minutes=60)
WINDOW_AFTER  = timedelta(minutes=140)

# definir a semana para depois utilziar para as estatisticas semanais
def week_range_sat_to_fri(anchor: date | None = None):
    """Devolve (start, end) de uma semana Sábado..Sexta que contém `anchor` (ou hoje)."""
    if anchor is None:
        anchor = datetime.now().date()
    # weekday(): Mon=0..Sun=6  -> Queremos Sábado=5 como início
    dow = anchor.weekday()          # 0..6
    # distância até sábado (5)
    delta_to_sat = (dow - 5) % 7
    start = anchor - timedelta(days=delta_to_sat)
    end   = start + timedelta(days=6)
    return start, end

def in_window(meal_time, now=None):
    """True se o momento atual estiver dentro da janela de validação da refeição de HOJE."""
    if now is None:
        now = datetime.now(APP_TZ)
    start = datetime.combine(now.date(), meal_time, tzinfo=APP_TZ) - WINDOW_BEFORE
    end   = datetime.combine(now.date(), meal_time, tzinfo=APP_TZ) + WINDOW_AFTER
    return start <= now <= end

def is_locked(day, meal_time, now=None, hours=48):
    """True se (day + meal_time) estiver a menos de `hours` horas (bloqueado)."""
    if now is None:
        now = datetime.now(APP_TZ)
    meal_dt = datetime.combine(day, meal_time, tzinfo=APP_TZ)
    return (meal_dt - now) < timedelta(hours=hours)
    # Se preferires bloquear também exatamente às 48:00:00, troca por: <=

@bp.route('/')
def index():
    return render_template('index.html')


@bp.route('/mark', methods=['GET', 'POST'])
def mark():
    #Ler credenciais consoante o método
    if request.method == 'GET':
        user_id_raw = request.args.get('user_id')
        pin = request.args.get('pin')
    else:
        user_id_raw = request.form.get('user_id')
        pin = request.form.get('pin')

    #Validar user_id
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return render_template('index.html', error='Número inválido')

    user = User.query.get(user_id)
    if not user:
        return render_template('index.html', error='Utilizador não existe')

    #Validar PIN (sempre que entra na rota)
    if not pin or not user.pin_hash or not check_password_hash(user.pin_hash, str(pin)):
        return render_template('index.html', error='PIN inválido ou em falta')


    meals = Meal.query.order_by(Meal.id).all()
    now = datetime.now(APP_TZ)
    today = now.date()
    days = [(today + timedelta(days=i)) for i in range(0, 31)]

    existing = Reservation.query.filter_by(user_id=user_id).all()
    canceled_set = {(r.date, r.meal_id) for r in existing}

    locked_set = {
        (d, meal.id)
        for d in days
        for meal in meals
        if is_locked(d, meal.scheduled_time, now=now)
    }

    if request.method == 'POST':
        selected = set(request.form.getlist('reservation'))  # "YYYY-MM-DD_mealId"
        for d in days:
            for meal in meals:
                key = f"{d}_{meal.id}"
                if (d, meal.id) in locked_set:
                    continue
                wants_attend = key in selected
                is_canceled = (d, meal.id) in canceled_set
                if wants_attend and is_canceled:
                    res = Reservation.query.filter_by(user_id=user_id, meal_id=meal.id, date=d).first()
                    if res:
                        db.session.delete(res)
                elif (not wants_attend) and (not is_canceled):
                    db.session.add(Reservation(user_id=user_id, meal_id=meal.id, date=d))
        try:
            db.session.commit()
            flash('Refeições atualizadas!', 'success')
        except Exception:
            db.session.rollback()
            flash('Ocorreu um erro ao gravar. Tenta novamente.', 'danger')

        # **mantém o PIN no URL após guardar**
        return redirect(url_for('routes.mark', user_id=user_id, pin=pin))

    # GET → render
    return render_template(
        'mark.html',
        user_id=user_id,
        pin=pin,                    # <- PASSA O PIN PARA O TEMPLATE
        meals=meals,
        days=days,
        canceled_set=canceled_set,
        locked_set=locked_set,
        weekdays=WEEKDAYS_PT
    )

@bp.route('/check', methods=['GET', 'POST'])
def check():
    result = None
    selected_meal = None
    if request.method == 'POST':
        try:
            user_id = int(request.form['user_id'])
            meal_id = int(request.form['meal_id'])
        except (KeyError, ValueError):
            user_id = None
            meal_id = None

        today = datetime.now(APP_TZ).date()
        if user_id and meal_id:
            # OPT-OUT: se existir linha = cancelou → vermelho; se não existir = marcado → verde
            res = Reservation.query.filter_by(user_id=user_id, meal_id=meal_id, date=today).first()
            result = 'green' if not res else 'red'
            selected_meal = meal_id

    meals = Meal.query.order_by(Meal.id).all()
    return render_template('check.html', meals=meals, result=result, selected_meal=selected_meal)

@bp.route('/kiosk', methods=['GET', 'POST'])
@login_required
def kiosk():
    meals = Meal.query.order_by(Meal.id).all()
    now = datetime.now(APP_TZ)
    today = now.date()

    # escolhe a refeição cuja janela está ativa
    current_meal = next((m for m in meals if in_window(m.scheduled_time, now=now)), None)

    result = None
    msg = None

    if request.method == 'POST':
        # só pedimos o nº de utilizador; a refeição é a ativa
        try:
            user_id = int(request.form['user_id'])
        except (KeyError, ValueError):
            user_id = None

        if not user_id:
            result, msg = 'red', 'Número de OB inválido.'
        elif not current_meal:
            result, msg = 'red', 'Não há refeição em validação neste momento.'
        else:
            # validação para a refeição ativa de HOJE
            meal_id = current_meal.id
            day = today

            # modelo opt-out: se existir linha em reservations = cancelado
            canceled = Reservation.query.filter_by(
                user_id=user_id, meal_id=meal_id, date=day
            ).first() is not None

            if canceled:
                result, msg = 'red', 'Não tem refeição marcada.'
            else:
                # registo idempotente da presença
                existing = Attendance.query.filter_by(
                    user_id=user_id, meal_id=meal_id, date=day
                ).first()
                if not existing:
                    try:
                        db.session.add(Attendance(user_id=user_id, meal_id=meal_id, date=day))
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                        result, msg = 'yellow', 'Erro ao registar presença.'
                        return render_template('kiosk.html',
                                               current_meal=current_meal, day=today,
                                               result=result, msg=msg)
                result, msg = 'green', 'Presença registada.'

    return render_template('kiosk.html',
                           current_meal=current_meal, day=today,
                           result=result, msg=msg)


@bp.route('/admin')
@login_required
def admin_dashboard():
    date_str = request.args.get('date')
    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now(APP_TZ).date()
    except ValueError:
        day = datetime.now(APP_TZ).date()

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

    # lista de cancelamentos (útil para consulta)
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
        day = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.now(APP_TZ).date()
    except ValueError:
        day = datetime.now(APP_TZ).date()

    meal = Meal.query.get(meal_id)
    if not meal:
        flash('Refeição inválida', 'danger')
        return redirect(url_for('routes.admin_dashboard', date=day.strftime('%Y-%m-%d')))

    # Esperados = todos - cancelados
    canceled_users = {
        r.user_id for r in Reservation.query.with_entities(Reservation.user_id)
        .filter_by(date=day, meal_id=meal_id).all()
    }
    all_users = {u.id for u in User.query.with_entities(User.id).all()}
    expected_users = all_users - canceled_users

    # Presentes
    present_users = {
        a.user_id for a in Attendance.query.with_entities(Attendance.user_id)
        .filter_by(date=day, meal_id=meal_id).all()
    }

    absent_users = sorted(expected_users - present_users)
    return render_template('admin_absences.html', day=day, meal=meal, absent_users=absent_users)


@bp.route('/admin/weekly')
@login_required
def admin_weekly():
    """
    Estatísticas semanais (Sáb→Sex):
      - Top utilizadores com mais faltas (faltas = esperados - presentes)
      - Totais por refeição e percentagens
    """
    # Aceita ?anchor=YYYY-MM-DD para navegar semanas; se não vier: hoje
    anchor_str = request.args.get('anchor')
    try:
        anchor = datetime.strptime(anchor_str, '%Y-%m-%d').date() if anchor_str else datetime.now().date()
    except ValueError:
        anchor = datetime.now().date()

    week_start, week_end = week_range_sat_to_fri(anchor)

    # Dados base
    meals = Meal.query.order_by(Meal.id).all()
    all_days = [week_start + timedelta(days=i) for i in range(7)]

    # Universo de utilizadores
    all_user_ids = [u.id for u in User.query.with_entities(User.id).all()]
    all_user_set = set(all_user_ids)

    # Buscar CANCELAMENTOS da semana (opt-out)
    res_rows = (
        Reservation.query
        .with_entities(Reservation.user_id, Reservation.meal_id, Reservation.date)
        .filter(Reservation.date >= week_start, Reservation.date <= week_end)
        .all()
    )
    canceled_map: dict[tuple[date,int], set[int]] = {}
    for uid, mid, d in res_rows:
        canceled_map.setdefault((d, mid), set()).add(uid)

    # Buscar PRESENÇAS da semana
    att_rows = (
        Attendance.query
        .with_entities(Attendance.user_id, Attendance.meal_id, Attendance.date)
        .filter(Attendance.date >= week_start, Attendance.date <= week_end)
        .all()
    )
    present_map: dict[tuple[date,int], set[int]] = {}
    for uid, mid, d in att_rows:
        present_map.setdefault((d, mid), set()).add(uid)

    # Agregar faltas por utilizador e por refeição
    absences_per_user: dict[int, int] = {uid: 0 for uid in all_user_set}
    per_meal_totals = {m.id: {"name": m.name, "expected": 0, "present": 0, "absent": 0} for m in meals}

    for d in all_days:
        for m in meals:
            canceled = canceled_map.get((d, m.id), set())
            expected = all_user_set - canceled
            present  = present_map.get((d, m.id), set())
            # apenas contamos presentes dentro dos esperados (só por segurança)
            present_effective = present & expected
            absent_set = expected - present_effective

            # Totais por refeição
            per_meal_totals[m.id]["expected"] += len(expected)
            per_meal_totals[m.id]["present"]  += len(present_effective)
            per_meal_totals[m.id]["absent"]   += len(absent_set)

            # Acumular faltas por utilizador
            for uid in absent_set:
                absences_per_user[uid] = absences_per_user.get(uid, 0) + 1

    # Top faltosos (ordena desc, ignora quem tem 0)
    top_absentees = sorted(
        ((uid, cnt) for uid, cnt in absences_per_user.items() if cnt > 0),
        key=lambda x: x[1],
        reverse=True
    )

    # Traz info básica dos users (se tiveres campos como name, mostra; senão, fica só o id)
    users_map = {u.id: u for u in User.query.filter(User.id.in_([uid for uid, _ in top_absentees])).all()}

    # Preparar linhas para a tabela
    top_rows = []
    for uid, cnt in top_absentees:
        u = users_map.get(uid)
        display = getattr(u, "name", None) or getattr(u, "full_name", None) or f"Nº OB {uid}"
        top_rows.append({"user_id": uid, "display": display, "absences": cnt})

    # Converter totais por refeição para lista ordenada pelo id
    per_meal_rows = []
    for m in meals:
        t = per_meal_totals[m.id]
        expected = t["expected"]
        absent   = t["absent"]
        present  = t["present"]
        faltas_pct = (absent / expected * 100.0) if expected else 0.0
        per_meal_rows.append({
            "meal_id": m.id,
            "meal_name": t["name"],
            "expected": expected,
            "present": present,
            "absent": absent,
            "faltas_pct": round(faltas_pct, 1)
        })
    prev_anchor = (week_start - timedelta(days=1)).strftime('%Y-%m-%d')
    next_anchor = (week_end + timedelta(days=1)).strftime('%Y-%m-%d')

    return render_template(
        'admin_weekly.html',
        week_start=week_start,
        week_end=week_end,
        top_rows=top_rows[:50],
        per_meal_rows=per_meal_rows,
        prev_anchor=prev_anchor,
        next_anchor=next_anchor,
    )
