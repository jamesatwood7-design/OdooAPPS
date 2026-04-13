from flask import Flask, render_template
from config import Config
from common.odoo_api import OdooClient
from common.exceptions import OdooConnectionError, OdooAuthenticationError


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    odoo = OdooClient(
        url=app.config['ODOO_URL'],
        db=app.config['ODOO_DB'],
        username=app.config['ODOO_USERNAME'],
        password=app.config['ODOO_PASSWORD'],
    )

    try:
        odoo.authenticate()
    except (OdooConnectionError, OdooAuthenticationError) as e:
        app.logger.warning(f'Could not connect to Odoo on startup: {e}')

    app.odoo = odoo

    from timeclock import bp as timeclock_bp
    app.register_blueprint(timeclock_bp, url_prefix='/timeclock')

    from jobcosting import bp as jobcosting_bp
    app.register_blueprint(jobcosting_bp, url_prefix='/jobcosting')

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.errorhandler(OdooConnectionError)
    def handle_connection_error(e):
        return render_template('error.html', title='Connection Error',
                               message=str(e)), 503

    @app.errorhandler(OdooAuthenticationError)
    def handle_auth_error(e):
        return render_template('error.html', title='Authentication Error',
                               message=str(e)), 401

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=app.config['DEBUG'], port=5000)
