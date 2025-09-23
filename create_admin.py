from getpass import getpass
from werkzeug.security import generate_password_hash
from models import db, Admin
from app import create_app

app = create_app()

with app.app_context():
    username = input('Username do admin: ').strip()
    password = getpass('Password: ')
    # procurar por username (unique), não por PK
    existing = Admin.query.filter_by(username=username).first()
    if existing:
        print('Já existe um admin com esse username.')
        raise SystemExit(1)
    admin = Admin(username=username, password_hash=generate_password_hash(password))
    db.session.add(admin)
    db.session.commit()
    print('Admin criado com sucesso!')
