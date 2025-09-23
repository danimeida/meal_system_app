from flask import Flask
from models import db
from auth import bp_auth, login_manager   # usa o login_manager definido em auth.py
from routes import bp
from config import Config


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Inicializações
    db.init_app(app)
    login_manager.init_app(app)

    # Blueprints
    app.register_blueprint(bp_auth, url_prefix='/auth')
    app.register_blueprint(bp)

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
