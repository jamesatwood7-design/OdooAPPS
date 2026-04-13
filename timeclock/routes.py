from datetime import date, timedelta
from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, current_app,
)
from timeclock import bp
from timeclock import services
from common.exceptions import OdooAPIError, OdooConnectionError


@bp.route('/')
def dashboard():
    """Main time clock dashboard showing employee status and clock in/out button."""
    odoo = current_app.odoo
    employee_id = session.get('timeclock_employee_id')

    employees = []
    status = None
    today_summary = None

    try:
        employees = services.get_all_employees(odoo)

        if employee_id:
            status = services.get_attendance_status(odoo, employee_id)
            today_summary = services.get_daily_summary(odoo, employee_id)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'timeclock/dashboard.html',
        employees=employees,
        selected_employee_id=employee_id,
        status=status,
        today_summary=today_summary,
    )


@bp.route('/select-employee', methods=['POST'])
def select_employee():
    """Set the active employee for time clock operations."""
    employee_id = request.form.get('employee_id', type=int)
    if employee_id:
        session['timeclock_employee_id'] = employee_id
    else:
        session.pop('timeclock_employee_id', None)
    return redirect(url_for('timeclock.dashboard'))


@bp.route('/toggle', methods=['POST'])
def toggle_attendance():
    """Clock in or out (toggle) for the selected employee."""
    employee_id = session.get('timeclock_employee_id')
    if not employee_id:
        flash('Please select an employee first.', 'warning')
        return redirect(url_for('timeclock.dashboard'))

    odoo = current_app.odoo
    try:
        services.toggle_attendance(odoo, employee_id)
        status = services.get_attendance_status(odoo, employee_id)
        if status['state'] == 'checked_in':
            flash('Clocked in successfully.', 'success')
        else:
            flash('Clocked out successfully.', 'success')
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Error toggling attendance: {e}', 'danger')

    return redirect(url_for('timeclock.dashboard'))


@bp.route('/history')
def history():
    """Attendance history with date range filters."""
    employee_id = session.get('timeclock_employee_id')
    if not employee_id:
        flash('Please select an employee first.', 'warning')
        return redirect(url_for('timeclock.dashboard'))

    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    date_from = None
    date_to = None

    if date_from_str:
        try:
            date_from = date.fromisoformat(date_from_str)
        except ValueError:
            pass

    if date_to_str:
        try:
            date_to = date.fromisoformat(date_to_str)
        except ValueError:
            pass

    if not date_from and not date_to:
        date_from = date.today() - timedelta(days=30)
        date_to = date.today()

    odoo = current_app.odoo
    records = []
    employee = None

    try:
        employee = services.get_employee(odoo, employee_id)
        records = services.get_attendance_history(
            odoo, employee_id, date_from=date_from, date_to=date_to
        )
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'timeclock/history.html',
        records=records,
        employee=employee,
        date_from=date_from,
        date_to=date_to,
    )


@bp.route('/summary')
def summary():
    """Daily and weekly hour summaries."""
    employee_id = session.get('timeclock_employee_id')
    if not employee_id:
        flash('Please select an employee first.', 'warning')
        return redirect(url_for('timeclock.dashboard'))

    target_date_str = request.args.get('date', '')
    target_date = date.today()

    if target_date_str:
        try:
            target_date = date.fromisoformat(target_date_str)
        except ValueError:
            pass

    odoo = current_app.odoo
    daily = None
    weekly = None
    employee = None

    try:
        employee = services.get_employee(odoo, employee_id)
        daily = services.get_daily_summary(odoo, employee_id, target_date)
        weekly = services.get_weekly_summary(odoo, employee_id, target_date)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'timeclock/summary.html',
        employee=employee,
        daily=daily,
        weekly=weekly,
        target_date=target_date,
    )


@bp.route('/api/status')
def api_status():
    """JSON endpoint for AJAX status polling."""
    employee_id = session.get('timeclock_employee_id')
    if not employee_id:
        return jsonify({'error': 'No employee selected'}), 400

    odoo = current_app.odoo
    try:
        status = services.get_attendance_status(odoo, employee_id)
        return jsonify({
            'state': status['state'],
            'since': status['since'].isoformat() if status['since'] else None,
            'employee_name': status['employee']['name'] if status['employee'] else None,
        })
    except (OdooConnectionError, OdooAPIError) as e:
        return jsonify({'error': str(e)}), 503
