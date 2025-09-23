# generate_pins.py
import csv, random, sys
from datetime import datetime
from werkzeug.security import generate_password_hash
from app import create_app
from models import db, User

def random_pin():
    return f"{random.randint(0, 9999):04d}"

app = create_app()

try:
    with app.app_context():
        uri = app.config.get("SQLALCHEMY_DATABASE_URI")
        print("DB URI =", uri)

        # Garante colunas (não falha se já existirem)
        print("A garantir colunas pin_hash/pin_set_at em users...")
        db.session.execute(db.text("""
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS pin_hash TEXT,
              ADD COLUMN IF NOT EXISTS pin_set_at TIMESTAMPTZ DEFAULT now()
        """))
        db.session.commit()

        # Gerar PINs só para quem não tem
        print("A gerar PINs em falta...")
        res = db.session.execute(db.text("SELECT id FROM users WHERE pin_hash IS NULL ORDER BY id"))
        users_no_pin = [row[0] for row in res.fetchall()]
        rows = []
        for uid in users_no_pin:
            pin = random_pin()
            db.session.execute(
                db.text("UPDATE users SET pin_hash=:h, pin_set_at=now() WHERE id=:i"),
                {"h": generate_password_hash(pin), "i": uid}
            )
            rows.append({"user_id": uid, "pin": pin})

        db.session.commit()

        fname = f"pins_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(fname, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["user_id", "pin"])
            w.writeheader()
            w.writerows(rows)

        print(f"✅ Terminado. Novos PINs gerados: {len(rows)}. Ficheiro: {fname}")

except Exception as e:
    print("❌ Erro:", e)
    sys.exit(1)
