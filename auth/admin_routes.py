from flask import (
    render_template, redirect, url_for, flash, request, current_app,
)
from auth import bp
from auth.routes import permission_required
from auth.db import (
    list_users, get_user, create_user, update_user, update_password,
    get_user_permissions, update_user_permissions, delete_user, FEATURES,
)


@bp.route('/admin/users')
@permission_required('admin', 'read')
def admin_users():
    """List all users."""
    users = []
    try:
        users = list_users()
    except Exception as e:
        flash(f'Error loading users: {e}', 'danger')

    return render_template('admin/users.html', users=users)


@bp.route('/admin/users/create', methods=['GET', 'POST'])
@permission_required('admin', 'write')
def admin_create_user():
    """Create a new user."""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        employee_id = request.form.get('employee_id', type=int)

        if not username or not password or not full_name:
            flash('Username, password, and full name are required.', 'warning')
            return redirect(url_for('auth.admin_create_user'))

        try:
            user = create_user(username, password, full_name, email, employee_id)
            if user:
                # Parse permissions from form
                perms = _parse_permission_form(request.form)
                update_user_permissions(user['id'], perms)

                flash(f'User "{full_name}" created successfully.', 'success')
                return redirect(url_for('auth.admin_users'))
            else:
                flash('Failed to create user.', 'danger')
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    employees = []
    try:
        odoo = current_app.odoo
        employees = odoo.search_read(
            'hr.employee', [], fields=['id', 'name'], order='name asc'
        )
    except Exception:
        pass

    return render_template(
        'admin/user_form.html',
        user=None,
        permissions={},
        features=FEATURES,
        employees=employees,
        action='Create',
    )


@bp.route('/admin/users/<user_id>/edit', methods=['GET', 'POST'])
@permission_required('admin', 'write')
def admin_edit_user(user_id):
    """Edit an existing user."""
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip()
        employee_id = request.form.get('employee_id', type=int)
        new_password = request.form.get('password', '').strip()

        try:
            update_user(user_id, {
                'full_name': full_name,
                'email': email or None,
                'employee_id': employee_id,
            })

            if new_password:
                update_password(user_id, new_password)

            perms = _parse_permission_form(request.form)
            update_user_permissions(user_id, perms)

            flash('User updated successfully.', 'success')
            return redirect(url_for('auth.admin_users'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    user = None
    permissions = {}
    try:
        user = get_user(user_id)
        permissions = get_user_permissions(user_id)
    except Exception as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('auth.admin_users'))

    if not user:
        flash('User not found.', 'warning')
        return redirect(url_for('auth.admin_users'))

    employees = []
    try:
        odoo = current_app.odoo
        employees = odoo.search_read(
            'hr.employee', [], fields=['id', 'name'], order='name asc'
        )
    except Exception:
        pass

    return render_template(
        'admin/user_form.html',
        user=user,
        permissions=permissions,
        features=FEATURES,
        employees=employees,
        action='Edit',
    )


@bp.route('/admin/users/<user_id>/toggle', methods=['POST'])
@permission_required('admin', 'write')
def admin_toggle_user(user_id):
    """Activate/deactivate a user."""
    try:
        user = get_user(user_id)
        if user:
            new_status = not user.get('is_active', True)
            update_user(user_id, {'is_active': new_status})
            status_text = 'activated' if new_status else 'deactivated'
            flash(f'User {user["full_name"]} {status_text}.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('auth.admin_users'))


@bp.route('/admin/users/<user_id>/delete', methods=['POST'])
@permission_required('admin', 'delete')
def admin_delete_user(user_id):
    """Delete a user."""
    try:
        user = get_user(user_id)
        if user:
            delete_user(user_id)
            flash(f'User {user["full_name"]} deleted.', 'success')
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return redirect(url_for('auth.admin_users'))


def _parse_permission_form(form):
    """Parse permission checkboxes from form data."""
    perms = {}
    for feature_key, _, _ in FEATURES:
        perms[feature_key] = {
            'read': form.get(f'perm_{feature_key}_read') == 'on',
            'write': form.get(f'perm_{feature_key}_write') == 'on',
            'delete': form.get(f'perm_{feature_key}_delete') == 'on',
        }
    return perms
