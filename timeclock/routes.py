from datetime import date, timedelta
from flask import (
    render_template, redirect, url_for, flash, request,
    session, jsonify, current_app,
)
from timeclock import bp
from timeclock import services
from common.exceptions import OdooAPIError, OdooConnectionError
from auth.routes import odoo_user_required


def _is_manager_session():
    """Check if the current session is in manager mode."""
    return session.get('timeclock_is_manager', False)


@bp.route('/')
def dashboard():
    """Main time clock dashboard showing employee status and clock in/out button."""
    odoo = current_app.odoo
    employee_id = session.get('timeclock_employee_id')

    employees = []
    status = None
    today_summary = None
    is_mgr = False

    try:
        employees = services.get_all_employees(odoo)

        if employee_id:
            status = services.get_attendance_status(odoo, employee_id)
            today_summary = services.get_daily_summary(odoo, employee_id)
            is_mgr = services.is_manager(odoo, employee_id)
            session['timeclock_is_manager'] = is_mgr
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
        is_manager=is_mgr,
    )


@bp.route('/select-employee', methods=['POST'])
def select_employee():
    """Set the active employee for time clock operations."""
    employee_id = request.form.get('employee_id', type=int)
    if employee_id:
        session['timeclock_employee_id'] = employee_id
        # Clear manager flag; will be re-evaluated on dashboard load
        session.pop('timeclock_is_manager', None)
    else:
        session.pop('timeclock_employee_id', None)
        session.pop('timeclock_is_manager', None)
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
@odoo_user_required
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
@odoo_user_required
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


# ---------------------------------------------------------------------------
# Time Allocation routes
# ---------------------------------------------------------------------------

@bp.route('/allocate')
def allocate_list():
    """Show team members with attendance records that need time allocation.

    Manager-only: requires the logged-in employee to have direct reports.
    Shows only the manager's subordinates.
    """
    manager_id = session.get('timeclock_employee_id')
    if not manager_id:
        flash('Please select your employee profile first.', 'warning')
        return redirect(url_for('timeclock.dashboard'))

    if not _is_manager_session():
        flash('Only managers can access time allocation.', 'danger')
        return redirect(url_for('timeclock.dashboard'))

    odoo = current_app.odoo
    subordinates_data = []
    manager = None

    try:
        manager = services.get_employee(odoo, manager_id)
        subordinates = services.get_subordinates(odoo, manager_id)

        for sub in subordinates:
            unallocated = services.get_unallocated_attendances(odoo, sub['id'])
            subordinates_data.append({
                'employee': sub,
                'unallocated': unallocated,
                'unallocated_count': len(unallocated),
            })
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'timeclock/allocate_list.html',
        manager=manager,
        subordinates_data=subordinates_data,
    )


@bp.route('/allocate/<int:attendance_id>', methods=['GET', 'POST'])
def allocate(attendance_id):
    """Allocate hours from an attendance record to jobs.

    Manager-only: verifies the attendance belongs to a subordinate.
    """
    manager_id = session.get('timeclock_employee_id')
    if not manager_id:
        flash('Please select your employee profile first.', 'warning')
        return redirect(url_for('timeclock.dashboard'))

    if not _is_manager_session():
        flash('Only managers can access time allocation.', 'danger')
        return redirect(url_for('timeclock.dashboard'))

    odoo = current_app.odoo

    # Verify the attendance record belongs to a subordinate
    try:
        att_check = services.get_attendance_record(odoo, attendance_id)
        if not att_check:
            flash('Attendance record not found.', 'warning')
            return redirect(url_for('timeclock.allocate_list'))

        att_emp = att_check.get('employee_id')
        target_emp_id = att_emp[0] if isinstance(att_emp, (list, tuple)) else att_emp

        if not services.can_manage_employee(odoo, manager_id, target_emp_id):
            flash('You can only allocate time for your direct reports.', 'danger')
            return redirect(url_for('timeclock.allocate_list'))
    except (OdooConnectionError, OdooAPIError) as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('timeclock.allocate_list'))

    if request.method == 'POST':
        try:
            allocations = []
            hourly_rate = request.form.get('hourly_rate', 0, type=float)
            i = 0
            while True:
                acct_key = f'account_id_{i}'
                hours_key = f'hours_{i}'
                if acct_key not in request.form:
                    break
                account_id = request.form.get(acct_key, type=int)
                hours = request.form.get(hours_key, 0, type=float)
                if account_id and hours > 0:
                    allocations.append({'account_id': account_id, 'hours': hours})
                i += 1

            if not allocations:
                flash('Please add at least one allocation.', 'warning')
                return redirect(url_for('timeclock.allocate', attendance_id=attendance_id))

            services.save_time_allocations(
                odoo, attendance_id, target_emp_id, allocations, hourly_rate
            )
            flash('Time allocated successfully.', 'success')
            return redirect(url_for('timeclock.allocate_list'))

        except OdooConnectionError as e:
            flash(f'Cannot connect to Odoo: {e}', 'danger')
        except OdooAPIError as e:
            flash(f'Error saving allocation: {e}', 'danger')
        except ValueError as e:
            flash(str(e), 'danger')

    # GET: load the attendance record, existing allocations, and job list
    attendance = att_check
    existing = []
    jobs = []
    employee = None

    try:
        employee = services.get_employee(odoo, target_emp_id)
        existing = services.get_allocations_for_attendance(
            odoo, attendance_id, target_emp_id, attendance['check_in_dt']
        )
        jobs = services.get_jobs_for_allocation(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    allocated_hours = sum(a.get('unit_amount', 0) or 0 for a in existing)
    total_hours = attendance.get('worked_hours', 0) or 0 if attendance else 0

    return render_template(
        'timeclock/allocate.html',
        employee=employee,
        attendance=attendance,
        existing=existing,
        jobs=jobs,
        allocated_hours=allocated_hours,
        remaining_hours=max(0, total_hours - allocated_hours),
    )


# ---------------------------------------------------------------------------
# Kiosk Mode (PIN + Photo, no auth required)
# ---------------------------------------------------------------------------

@bp.route('/kiosk')
def kiosk():
    """Kiosk mode - full screen clock in/out with PIN and photo."""
    return render_template('timeclock/kiosk.html')


@bp.route('/kiosk/clock', methods=['POST'])
def kiosk_clock():
    """Process a kiosk clock in/out via PIN + photo."""
    odoo = current_app.odoo
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    pin = data.get('pin', '')
    photo = data.get('photo', '')

    if not pin:
        return jsonify({'error': 'Please enter your PIN'}), 400

    try:
        employee = services.verify_pin(odoo, pin)
        if not employee:
            return jsonify({'error': 'Invalid PIN. Please try again.'}), 401

        result = services.kiosk_clock(odoo, employee['id'], photo_base64=photo)
        return jsonify({
            'success': True,
            'employee_name': result['employee_name'],
            'action': result['action'],
            'state': result['state'],
        })

    except OdooConnectionError as e:
        return jsonify({'error': f'Cannot connect to Odoo: {e}'}), 503
    except OdooAPIError as e:
        return jsonify({'error': f'Error: {e}'}), 500
    except Exception as e:
        return jsonify({'error': f'Error: {e}'}), 500
