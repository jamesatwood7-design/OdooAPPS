from datetime import datetime, timedelta


ODOO_DATETIME_FORMAT = '%Y-%m-%d %H:%M:%S'
ODOO_DATE_FORMAT = '%Y-%m-%d'


def format_duration(hours_float):
    """Convert Odoo's float hours (e.g. 8.5) to a readable string like '8h 30m'."""
    if hours_float is None or hours_float is False:
        return '0h 0m'
    total_minutes = int(round(hours_float * 60))
    hours = total_minutes // 60
    minutes = total_minutes % 60
    return f'{hours}h {minutes:02d}m'


def datetime_to_odoo(dt):
    """Convert a Python datetime to Odoo's string format."""
    return dt.strftime(ODOO_DATETIME_FORMAT)


def odoo_to_datetime(s):
    """Convert an Odoo datetime string to a Python datetime."""
    if not s:
        return None
    return datetime.strptime(s, ODOO_DATETIME_FORMAT)


def date_to_odoo(d):
    """Convert a Python date to Odoo's date string format."""
    return d.strftime(ODOO_DATE_FORMAT)


def odoo_to_date(s):
    """Convert an Odoo date string to a Python date."""
    if not s:
        return None
    return datetime.strptime(s, ODOO_DATE_FORMAT).date()


def get_week_boundaries(date):
    """Return (monday, sunday) of the week containing the given date."""
    monday = date - timedelta(days=date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday


def get_day_boundaries(date):
    """Return (start_of_day, end_of_day) as datetime strings for Odoo queries."""
    start = datetime.combine(date, datetime.min.time())
    end = datetime.combine(date, datetime.max.time())
    return datetime_to_odoo(start), datetime_to_odoo(end)
