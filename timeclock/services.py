from datetime import datetime, date, timedelta
from common.utils import (
    datetime_to_odoo, odoo_to_datetime, format_duration,
    get_week_boundaries, get_day_boundaries,
)


def get_all_employees(odoo):
    """Return a list of all employees with their attendance state."""
    return odoo.safe_search_read(
        'hr.employee', [],
        fields=['id', 'name', 'attendance_state'],
        order='name asc',
    )


def get_employee(odoo, employee_id):
    """Get a single employee record by ID."""
    records = odoo.safe_search_read(
        'hr.employee',
        [('id', '=', employee_id)],
        fields=['id', 'name', 'attendance_state', 'last_attendance_id'],
    )
    return records[0] if records else None


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
