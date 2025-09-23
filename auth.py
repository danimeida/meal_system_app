from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import (
    LoginManager, login_user, logout_user, login_required,
    UserMixin, current_user
)
from werkzeug.security import check_password_hash
from models import Admin  # PK = id (bigint), username UNIQUE, password_hash
                         # (ajusta se o teu Admin tiver outro esquema)

# Blueprint de autenticação
bp_auth = Blueprint('auth', __name__)

# Instância global do LoginManager exportada para o app.py
login_manager = LoginManager()
login_manager.login_view = 'auth.admin_login'  # para @login_required redirecionar

# Wrapper do utilizador admin para a sessão
class AdminUser(UserMixin):
    def __init__(self, username: str):
        # guardamos o id da sessão com um prefixo para evitar colisões
        self.id = f"admin:{username}"
        self.username = username

# Carregador de utilizadores da sessão
@login_manager.user_loader
def load_user(user_id: str):
    """
    user_id vem no formato 'admin:<username>'.
    """
    try:
        role, username = user_id.split(':', 1)
    except ValueError:
        return None

    if role != 'admin':
        return None

    a = Admin.query.filter_by(username=username).first()
    return AdminUser(a.username) if a else None


# -------------------------
# Rotas de autenticação
# -------------------------

@bp_auth.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    """
    Login de administrador. Usa username (UNIQUE) + password hash.
    """
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''

        a = Admin.query.filter_by(username=username).first()
        if a and check_password_hash(a.password_hash, password):
            login_user(AdminUser(a.username), remember=True)
            return redirect(url_for('routes.admin_dashboard'))

        flash('Credenciais inválidas.', 'danger')

    return render_template('admin_login.html')


@bp_auth.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('routes.index'))
