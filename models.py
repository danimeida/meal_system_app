from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.SmallInteger, primary_key=True)
    pin_hash = db.Column(db.Text, nullable=True)
    pin_set_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    # helpers (opcional)
    def set_pin(self, pin: str):
        self.pin_hash = generate_password_hash(str(pin))

    def check_pin(self, pin: str) -> bool:
        if not self.pin_hash:
            return False
        return check_password_hash(self.pin_hash, str(pin))



class Meal(db.Model):
    __tablename__ = 'meals'
    id = db.Column(db.SmallInteger, primary_key=True)
    name = db.Column(db.Text, nullable=False, unique=True)
    scheduled_time = db.Column(db.Time, nullable=False)

class Validator(db.Model):
    __tablename__ = 'validators'
    id = db.Column(db.BigInteger, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)

    def set_password(self, raw, hasher):
        self.password_hash = hasher.generate_password_hash(raw)

    def check_password(self, raw, hasher):
        return hasher.check_password_hash(self.password_hash, raw)

class Reservation(db.Model):
    __tablename__ = 'reservations'
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.SmallInteger, db.ForeignKey('users.id'), nullable=False)
    meal_id = db.Column(db.SmallInteger, db.ForeignKey('meals.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now())

    user = db.relationship('User')
    meal = db.relationship('Meal')

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.SmallInteger, db.ForeignKey('users.id'), nullable=False)
    meal_id = db.Column(db.SmallInteger, db.ForeignKey('meals.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    validated_at = db.Column(db.DateTime(timezone=True), server_default=db.func.now(), nullable=False)
    source = db.Column(db.Text, nullable=False, default='kiosk')

    __table_args__ = (
        db.UniqueConstraint('user_id', 'meal_id', 'date', name='uq_attendance_user_meal_date'),
    )


class Admin(db.Model):
    __tablename__ = 'admins'
    id = db.Column(db.BigInteger, primary_key=True)
    username = db.Column(db.Text, unique=True, nullable=False)
    password_hash = db.Column(db.Text, nullable=False)

