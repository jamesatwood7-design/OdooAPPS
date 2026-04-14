from functools import wraps
from flask import (
    render_template, redirect, url_for, flash, request,
    session, current_app,
)
from auth import bp
from common.odoo_api import OdooClient
from common.exceptions import OdooConnectionError, OdooAuthenticationError


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Require any authenticated session (Odoo user or employee)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'auth_type' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def odoo_user_required(f):
    """Require an authenticated Odoo user session (not employee-only)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('auth_type') != 'odoo_user':
            flash('This feature requires an Odoo user account.', 'danger')
            return redirect(url_for('timeclock.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/login', methods=['GET'])
def login():
    """Show the login page with dual tabs."""
    if 'auth_type' in session:
        return redirect(url_for('index'))

    odoo = current_app.odoo
    employees = []
    try:
        employees = odoo.search_read(
            'hr.employee', [],
            fields=['id', 'name'],
            order='name asc',
        )
    except Exception:
        flash('Cannot load employee list from Odoo.', 'danger')

    return render_template('auth/login.html', employees=employees)


@bp.route('/login/odoo', methods=['POST'])
def login_odoo():
    """Authenticate with Odoo credentials."""
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')

    if not email or not password:
        flash('Please enter both email and password.', 'warning')
        return redirect(url_for('auth.login'))

    app = current_app
    try:
        # Authenticate against Odoo with the user's own credentials
        temp_client = OdooClient(
            url=app.config['ODOO_URL'],
            db=app.config['ODOO_DB'],
            username=email,
            password=password,
        )
        uid = temp_client.authenticate()

        # Look up the employee record for this Odoo user
        admin_odoo = app.odoo
        emp_records = admin_odoo.search_read(
            'hr.employee',
            [('user_id', '=', uid)],
            fields=['id', 'name', 'parent_id'],
        )

        employee_id = None
        employee_name = email
        is_manager = False

        if emp_records:
            employee_id = emp_records[0]['id']
            employee_name = emp_records[0]['name']
            # Check if manager
            subordinates = admin_odoo.search(
                'hr.employee',
                [('parent_id', '=', employee_id)],
                limit=1,
            )
            is_manager = len(subordinates) > 0

        # Set session
        session['auth_type'] = 'odoo_user'
        session['odoo_uid'] = uid
        session['employee_id'] = employee_id
        session['user_name'] = employee_name
        session['is_manager'] = is_manager
        session['timeclock_employee_id'] = employee_id
        session['timeclock_is_manager'] = is_manager

        flash(f'Welcome, {employee_name}!', 'success')
        return redirect(url_for('index'))

    except OdooAuthenticationError:
        flash('Invalid email or password.', 'danger')
        return redirect(url_for('auth.login'))
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
        return redirect(url_for('auth.login'))
    except Exception as e:
        flash(f'Login error: {e}', 'danger')
        return redirect(url_for('auth.login'))


@bp.route('/login/employee', methods=['POST'])
def login_employee():
    """Employee self-identification (clock-in only access)."""
    employee_id = request.form.get('employee_id', type=int)

    if not employee_id:
        flash('Please select your name.', 'warning')
        return redirect(url_for('auth.login'))

    odoo = current_app.odoo
    try:
        records = odoo.search_read(
            'hr.employee',
            [('id', '=', employee_id)],
            fields=['id', 'name'],
        )
        if not records:
            flash('Employee not found.', 'danger')
            return redirect(url_for('auth.login'))

        employee_name = records[0]['name']

        session['auth_type'] = 'employee'
        session['odoo_uid'] = None
        session['employee_id'] = employee_id
        session['user_name'] = employee_name
        session['is_manager'] = False
        session['timeclock_employee_id'] = employee_id
        session['timeclock_is_manager'] = False

        flash(f'Welcome, {employee_name}!', 'success')
        return redirect(url_for('timeclock.dashboard'))

    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
        return redirect(url_for('auth.login'))


@bp.route('/logout')
def logout():
    """Clear the session and redirect to login."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
