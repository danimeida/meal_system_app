from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    print("DB URI =", app.config.get("SQLALCHEMY_DATABASE_URI"))
    print("Conectando...")
    print("Users na BD:", db.session.query(User).count())
