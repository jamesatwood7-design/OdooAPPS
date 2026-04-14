from datetime import datetime, date, timedelta
from common.utils import (
    datetime_to_odoo, odoo_to_datetime, format_duration,
    get_week_boundaries, get_day_boundaries,
)


def get_all_employees(odoo):
    """Return a list of all employees with their attendance state."""
    return odoo.safe_search_read(
        'hr.employee', [],
        fields=['id', 'name', 'attendance_state', 'parent_id'],
        order='name asc',
    )


def get_employee(odoo, employee_id):
    """Get a single employee record by ID."""
    records = odoo.safe_search_read(
        'hr.employee',
        [('id', '=', employee_id)],
        fields=['id', 'name', 'attendance_state', 'last_attendance_id', 'parent_id'],
    )
    return records[0] if records else None


def get_subordinates(odoo, manager_employee_id):
    """Get employees who report to the given manager (direct reports)."""
    return odoo.safe_search_read(
        'hr.employee',
        [('parent_id', '=', manager_employee_id)],
        fields=['id', 'name', 'attendance_state'],
        order='name asc',
    )


def is_manager(odoo, employee_id):
    """Check if an employee is a manager (has direct reports)."""
    subordinates = odoo.search(
        'hr.employee',
        [('parent_id', '=', employee_id)],
        limit=1,
    )
    return len(subordinates) > 0


def can_manage_employee(odoo, manager_id, target_employee_id):
    """Check if manager_id is the manager of target_employee_id."""
    if manager_id == target_employee_id:
        return True
    emp = get_employee(odoo, target_employee_id)
    if not emp:
        return False
    parent = emp.get('parent_id')
    if isinstance(parent, (list, tuple)):
        return parent[0] == manager_id
    return parent == manager_id


def get_attendance_status(odoo, employee_id):
    """Return the current attendance status for an employee.

    Returns a dict with:
        state: 'checked_in' or 'checked_out'
        since: datetime when the current clock-in started (or None)
        attendance_id: ID of the open attendance record (or None)
    """
    employee = get_employee(odoo, employee_id)
    if not employee:
        return {'state': 'checked_out', 'since': None, 'attendance_id': None}

    state = employee.get('attendance_state', 'checked_out')
    since = None
    attendance_id = None

    if state == 'checked_in':
        open_records = odoo.safe_search_read(
            'hr.attendance',
            [('employee_id', '=', employee_id), ('check_out', '=', False)],
            fields=['id', 'check_in'],
            limit=1,
            order='check_in desc',
        )
        if open_records:
            attendance_id = open_records[0]['id']
            since = odoo_to_datetime(open_records[0]['check_in'])

    return {
        'state': state,
        'since': since,
        'attendance_id': attendance_id,
        'employee': employee,
    }


def toggle_attendance(odoo, employee_id):
    """Toggle clock in/out for the employee.

    Tries the Odoo built-in attendance_action_change first,
    falling back to manual create/write.
    """
    status = get_attendance_status(odoo, employee_id)

    try:
        result = odoo.execute_kw(
            'hr.employee', 'attendance_action_change', [[employee_id]]
        )
        return result
    except Exception:
        if status['state'] == 'checked_out':
            return clock_in(odoo, employee_id)
        else:
            return clock_out(odoo, employee_id, status['attendance_id'])


def clock_in(odoo, employee_id):
    """Manually clock in by creating an hr.attendance record."""
    now_str = datetime_to_odoo(datetime.utcnow())
    return odoo.create('hr.attendance', {
        'employee_id': employee_id,
        'check_in': now_str,
    })


def clock_out(odoo, employee_id, attendance_id=None):
    """Manually clock out by writing check_out on the open attendance record."""
    if attendance_id is None:
        open_records = odoo.search(
            'hr.attendance',
            [('employee_id', '=', employee_id), ('check_out', '=', False)],
            limit=1,
        )
        if not open_records:
            return None
        attendance_id = open_records[0]

    now_str = datetime_to_odoo(datetime.utcnow())
    odoo.write('hr.attendance', [attendance_id], {'check_out': now_str})
    return attendance_id


def get_attendance_history(odoo, employee_id, date_from=None, date_to=None, limit=50):
    """Return attendance records for an employee within a date range."""
    domain = [('employee_id', '=', employee_id)]

    if date_from:
        start_str, _ = get_day_boundaries(date_from)
        domain.append(('check_in', '>=', start_str))

    if date_to:
        _, end_str = get_day_boundaries(date_to)
        domain.append(('check_in', '<=', end_str))

    records = odoo.safe_search_read(
        'hr.attendance', domain,
        fields=['id', 'check_in', 'check_out', 'worked_hours'],
        order='check_in desc',
        limit=limit,
    )

    for rec in records:
        rec['check_in_dt'] = odoo_to_datetime(rec['check_in'])
        rec['check_out_dt'] = odoo_to_datetime(rec.get('check_out'))
        rec['worked_hours_fmt'] = format_duration(rec.get('worked_hours'))

    return records


def get_daily_summary(odoo, employee_id, target_date=None):
    """Get total hours worked on a specific date."""
    if target_date is None:
        target_date = date.today()

    start_str, end_str = get_day_boundaries(target_date)
    records = odoo.safe_search_read(
        'hr.attendance',
        [
            ('employee_id', '=', employee_id),
            ('check_in', '>=', start_str),
            ('check_in', '<=', end_str),
        ],
        fields=['worked_hours', 'check_in', 'check_out'],
        order='check_in asc',
    )

    total_hours = sum(r.get('worked_hours', 0) or 0 for r in records)

    for rec in records:
        rec['check_in_dt'] = odoo_to_datetime(rec['check_in'])
        rec['check_out_dt'] = odoo_to_datetime(rec.get('check_out'))
        rec['worked_hours_fmt'] = format_duration(rec.get('worked_hours'))

    return {
        'date': target_date,
        'records': records,
        'total_hours': total_hours,
        'total_hours_fmt': format_duration(total_hours),
        'record_count': len(records),
    }


def get_weekly_summary(odoo, employee_id, target_date=None):
    """Get daily totals for the week containing the target date."""
    if target_date is None:
        target_date = date.today()

    monday, sunday = get_week_boundaries(target_date)

    start_str, _ = get_day_boundaries(monday)
    _, end_str = get_day_boundaries(sunday)

    records = odoo.safe_search_read(
        'hr.attendance',
        [
            ('employee_id', '=', employee_id),
            ('check_in', '>=', start_str),
            ('check_in', '<=', end_str),
        ],
        fields=['worked_hours', 'check_in'],
        order='check_in asc',
    )

    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    days = []
    week_total = 0.0

    for i in range(7):
        day = monday + timedelta(days=i)
        day_hours = 0.0
        for rec in records:
            rec_dt = odoo_to_datetime(rec['check_in'])
            if rec_dt and rec_dt.date() == day:
                day_hours += rec.get('worked_hours', 0) or 0

        week_total += day_hours
        days.append({
            'date': day,
            'name': day_names[i],
            'hours': day_hours,
            'hours_fmt': format_duration(day_hours),
        })

    return {
        'week_start': monday,
        'week_end': sunday,
        'days': days,
        'total_hours': week_total,
        'total_hours_fmt': format_duration(week_total),
    }


# ---------------------------------------------------------------------------
# Time Allocation (assign attendance hours to jobs/analytic accounts)
# ---------------------------------------------------------------------------

def get_jobs_for_allocation(odoo):
    """Get analytic accounts that can receive time allocations."""
    return odoo.search_read(
        'account.analytic.account', [],
        fields=['id', 'name', 'code'],
        order='code asc',
    )


def get_attendance_record(odoo, attendance_id):
    """Get a single attendance record with employee info."""
    records = odoo.safe_search_read(
        'hr.attendance',
        [('id', '=', attendance_id)],
        fields=['id', 'employee_id', 'check_in', 'check_out', 'worked_hours'],
    )
    if not records:
        return None
    rec = records[0]
    rec['check_in_dt'] = odoo_to_datetime(rec.get('check_in'))
    rec['check_out_dt'] = odoo_to_datetime(rec.get('check_out'))
    rec['worked_hours_fmt'] = format_duration(rec.get('worked_hours'))
    return rec


def get_allocations_for_attendance(odoo, attendance_id, employee_id, check_in_dt):
    """Get existing analytic line allocations for a specific attendance.

    We match by employee + date since analytic lines don't have an
    attendance_id field. We look for lines created by this app
    (they have a specific name pattern).
    """
    if not check_in_dt:
        return []

    att_date = check_in_dt.strftime('%Y-%m-%d')
    records = odoo.safe_search_read(
        'account.analytic.line',
        [
            ('employee_id', '=', employee_id),
            ('date', '=', att_date),
            ('name', 'ilike', f'[ATT-{attendance_id}]'),
        ],
        fields=['id', 'name', 'account_id', 'unit_amount', 'amount', 'date'],
        order='id asc',
    )

    for rec in records:
        rec['hours_fmt'] = format_duration(rec.get('unit_amount'))
        acct = rec.get('account_id')
        if isinstance(acct, (list, tuple)):
            rec['account_name'] = acct[1]
            rec['account_id_val'] = acct[0]
        else:
            rec['account_name'] = str(acct) if acct else ''
            rec['account_id_val'] = acct

    return records


def get_unallocated_attendances(odoo, employee_id, limit=20):
    """Find recent attendance records that haven't been fully allocated.

    Returns attendances where no matching analytic lines with ATT- tag exist.
    """
    # Get recent completed attendances
    attendances = odoo.safe_search_read(
        'hr.attendance',
        [
            ('employee_id', '=', employee_id),
            ('check_out', '!=', False),
        ],
        fields=['id', 'check_in', 'check_out', 'worked_hours'],
        order='check_in desc',
        limit=limit,
    )

    unallocated = []
    for att in attendances:
        att['check_in_dt'] = odoo_to_datetime(att.get('check_in'))
        att['check_out_dt'] = odoo_to_datetime(att.get('check_out'))
        att['worked_hours_fmt'] = format_duration(att.get('worked_hours'))

        # Check if this attendance has allocations
        existing = get_allocations_for_attendance(
            odoo, att['id'], employee_id, att['check_in_dt']
        )
        allocated_hours = sum(a.get('unit_amount', 0) or 0 for a in existing)
        total_hours = att.get('worked_hours', 0) or 0
        att['allocated_hours'] = allocated_hours
        att['allocated_hours_fmt'] = format_duration(allocated_hours)
        att['remaining_hours'] = max(0, total_hours - allocated_hours)
        att['remaining_hours_fmt'] = format_duration(max(0, total_hours - allocated_hours))
        att['fully_allocated'] = allocated_hours >= (total_hours - 0.01)
        att['allocations'] = existing

        if not att['fully_allocated']:
            unallocated.append(att)

    return unallocated


def save_time_allocations(odoo, attendance_id, employee_id, allocations,
                          hourly_rate=0):
    """Save time allocations for an attendance record.

    Each allocation is a dict: {account_id: int, hours: float}
    Creates account.analytic.line records in Odoo tagged with the
    attendance ID for tracking.

    Deletes any previous allocations for this attendance before saving.
    """
    # Get the attendance to determine the date
    att = get_attendance_record(odoo, attendance_id)
    if not att:
        raise ValueError('Attendance record not found')

    check_in_dt = att['check_in_dt']
    att_date = check_in_dt.strftime('%Y-%m-%d')

    # Delete existing allocations for this attendance
    existing = get_allocations_for_attendance(
        odoo, attendance_id, employee_id, check_in_dt
    )
    existing_ids = [e['id'] for e in existing]
    if existing_ids:
        odoo.unlink('account.analytic.line', existing_ids)

    # Create new allocations
    created_ids = []
    for alloc in allocations:
        account_id = alloc.get('account_id')
        hours = alloc.get('hours', 0)
        if not account_id or hours <= 0:
            continue

        amount = -(hours * hourly_rate) if hourly_rate else 0
        line_id = odoo.create('account.analytic.line', {
            'name': f'[ATT-{attendance_id}] Time allocation',
            'account_id': account_id,
            'employee_id': employee_id,
            'date': att_date,
            'unit_amount': hours,
            'amount': amount,
        })
        created_ids.append(line_id)

    return created_ids
