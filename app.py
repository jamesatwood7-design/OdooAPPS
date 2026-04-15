from flask import Flask, render_template, redirect, url_for, session, request
from config import Config
from common.odoo_api import OdooClient
from common.exceptions import OdooConnectionError, OdooAuthenticationError


# Paths that don't require authentication
PUBLIC_PATHS = {'/login', '/logout', '/setup', '/static',
                '/timeclock/kiosk', '/timeclock/kiosk/clock'}


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Admin OdooClient - used for employee lookups and API calls
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

    # Initialize Supabase client
    if app.config.get('SUPABASE_URL') and app.config.get('SUPABASE_KEY'):
        try:
            from supabase import create_client
            app.supabase = create_client(
                app.config['SUPABASE_URL'],
                app.config['SUPABASE_KEY'],
            )
        except Exception as e:
            app.logger.warning(f'Could not initialize Supabase: {e}')
            app.supabase = None
    else:
        app.supabase = None

    # Register blueprints
    from auth import bp as auth_bp
    app.register_blueprint(auth_bp)

    from timeclock import bp as timeclock_bp
    app.register_blueprint(timeclock_bp, url_prefix='/timeclock')

    from jobcosting import bp as jobcosting_bp
    app.register_blueprint(jobcosting_bp, url_prefix='/jobcosting')

    from accounting import bp as accounting_bp
    app.register_blueprint(accounting_bp, url_prefix='/accounting')

    @app.before_request
    def require_login():
        """Redirect unauthenticated users to the login page."""
        path = request.path
        if any(path.startswith(p) for p in PUBLIC_PATHS):
            return None
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))

    @app.route('/')
    def index():
        if 'user_id' not in session:
            return redirect(url_for('auth.login'))
        perms = session.get('permissions', {})
        from auth.db import has_permission
        if has_permission(perms, 'jobs', 'read'):
            return redirect(url_for('jobcosting.jobs_dashboard'))
        return redirect(url_for('timeclock.dashboard'))

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
    app.run(host='0.0.0.0', debug=app.config['DEBUG'], port=5000)
