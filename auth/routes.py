from functools import wraps
from flask import (
    render_template, redirect, url_for, flash, request,
    session, current_app,
)
from auth import bp
from auth.db import (
    verify_user, get_user_permissions, has_permission,
    create_user, user_count, FEATURES,
)


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def login_required(f):
    """Require any authenticated session."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


def permission_required(feature, level='read'):
    """Require a specific permission."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                flash('Please log in to continue.', 'warning')
                return redirect(url_for('auth.login'))

            perms = session.get('permissions', {})
            if not has_permission(perms, feature, level):
                flash('You do not have permission to access this feature.', 'danger')
                # Redirect to the most accessible page
                if has_permission(perms, 'jobs', 'read'):
                    return redirect(url_for('jobcosting.jobs_dashboard'))
                return redirect(url_for('timeclock.dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator


# Keep backward compat for existing code
def odoo_user_required(f):
    """Legacy decorator - now checks for jobs read permission."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('auth.login'))
        perms = session.get('permissions', {})
        if not has_permission(perms, 'jobs', 'read'):
            flash('You do not have permission to access this feature.', 'danger')
            return redirect(url_for('timeclock.dashboard'))
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/login', methods=['GET'])
def login():
    """Login page."""
    if 'user_id' in session:
        return redirect(url_for('index'))

    # Check if any users exist - if not, show setup
    needs_setup = False
    try:
        needs_setup = user_count() == 0
    except Exception:
        pass

    return render_template('auth/login.html', needs_setup=needs_setup)


@bp.route('/login', methods=['POST'])
def login_post():
    """Process login."""
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if not username or not password:
        flash('Please enter both username and password.', 'warning')
        return redirect(url_for('auth.login'))

    try:
        user = verify_user(username, password)
        if not user:
            flash('Invalid username or password.', 'danger')
            return redirect(url_for('auth.login'))

        # Load permissions
        perms = get_user_permissions(user['id'])

        # Set session
        session['user_id'] = user['id']
        session['username'] = user['username']
        session['user_name'] = user['full_name']
        session['employee_id'] = user.get('employee_id')
        session['permissions'] = perms
        session['timeclock_employee_id'] = user.get('employee_id')

        # Check if manager for timeclock
        is_mgr = False
        if user.get('employee_id') and has_permission(perms, 'time_allocation', 'read'):
            odoo = current_app.odoo
            try:
                from timeclock.services import is_manager
                is_mgr = is_manager(odoo, user['employee_id'])
            except Exception:
                pass
        session['timeclock_is_manager'] = is_mgr
        session['is_manager'] = is_mgr

        # Backward compat
        session['auth_type'] = 'odoo_user' if has_permission(perms, 'jobs', 'read') else 'employee'

        flash(f'Welcome, {user["full_name"]}!', 'success')
        return redirect(url_for('index'))

    except Exception as e:
        flash(f'Login error: {e}', 'danger')
        return redirect(url_for('auth.login'))


@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    """First-time setup: create the initial admin user."""
    try:
        if user_count() > 0:
            return redirect(url_for('auth.login'))
    except Exception as e:
        flash(f'Cannot connect to Supabase: {e}', 'danger')
        return render_template('auth/setup.html')

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        employee_id = request.form.get('employee_id', type=int)

        if not username or not password or not full_name:
            flash('Please fill in all required fields.', 'warning')
            return render_template('auth/setup.html')

        try:
            user = create_user(username, password, full_name, email, employee_id)
            if user:
                # Grant ALL permissions to the first user (admin)
                from auth.db import update_user_permissions
                all_perms = {}
                for feature_key, _, _ in FEATURES:
                    all_perms[feature_key] = {'read': True, 'write': True, 'delete': True}
                update_user_permissions(user['id'], all_perms)

                flash('Admin account created! Please log in.', 'success')
                return redirect(url_for('auth.login'))
            else:
                flash('Failed to create user.', 'danger')
        except Exception as e:
            flash(f'Error creating user: {e}', 'danger')

    # Load employees for dropdown
    employees = []
    try:
        odoo = current_app.odoo
        employees = odoo.search_read(
            'hr.employee', [], fields=['id', 'name'], order='name asc'
        )
    except Exception:
        pass

    return render_template('auth/setup.html', employees=employees)


@bp.route('/logout')
def logout():
    """Clear session and redirect to login."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
