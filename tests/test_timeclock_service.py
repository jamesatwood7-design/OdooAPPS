import pytest
from unittest.mock import MagicMock
from datetime import date

from timeclock.services import (
    get_all_employees, get_employee, get_attendance_status,
    toggle_attendance, get_attendance_history,
    get_daily_summary, get_weekly_summary,
)


@pytest.fixture
def odoo():
    mock = MagicMock()
    mock.uid = 1
    return mock


class TestGetEmployees:
    def test_get_all_employees(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out'},
            {'id': 2, 'name': 'Bob', 'attendance_state': 'checked_in'},
        ]

        result = get_all_employees(odoo)

        assert len(result) == 2
        assert result[0]['name'] == 'Alice'
        odoo.safe_search_read.assert_called_once()

    def test_get_employee_found(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
             'last_attendance_id': [10, 'Attendance']},
        ]

        result = get_employee(odoo, 1)

        assert result['name'] == 'Alice'

    def test_get_employee_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_employee(odoo, 999)

        assert result is None


class TestAttendanceStatus:
    def test_checked_out(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
             'last_attendance_id': False},
        ]

        result = get_attendance_status(odoo, 1)

        assert result['state'] == 'checked_out'
        assert result['since'] is None

    def test_checked_in(self, odoo):
        def mock_search_read(model, domain, **kwargs):
            if model == 'hr.employee':
                return [{'id': 1, 'name': 'Alice',
                         'attendance_state': 'checked_in',
                         'last_attendance_id': [10, 'Attendance']}]
            elif model == 'hr.attendance':
                return [{'id': 10, 'check_in': '2024-01-15 08:00:00'}]
            return []

        odoo.safe_search_read.side_effect = mock_search_read

        result = get_attendance_status(odoo, 1)

        assert result['state'] == 'checked_in'
        assert result['since'] is not None
        assert result['attendance_id'] == 10

    def test_employee_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_attendance_status(odoo, 999)

        assert result['state'] == 'checked_out'


class TestToggleAttendance:
    def test_toggle_uses_action_change(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
             'last_attendance_id': False},
        ]
        odoo.execute_kw.return_value = {'action': 'sign_in'}

        toggle_attendance(odoo, 1)

        odoo.execute_kw.assert_called_with(
            'hr.employee', 'attendance_action_change', [[1]]
        )


class TestAttendanceHistory:
    def test_returns_formatted_records(self, odoo):
        odoo.safe_search_read.return_value = [
            {
                'id': 1,
                'check_in': '2024-01-15 08:00:00',
                'check_out': '2024-01-15 17:00:00',
                'worked_hours': 9.0,
            },
        ]

        result = get_attendance_history(odoo, 1)

        assert len(result) == 1
        assert result[0]['worked_hours_fmt'] == '9h 00m'
        assert result[0]['check_in_dt'] is not None

    def test_open_record_has_no_checkout(self, odoo):
        odoo.safe_search_read.return_value = [
            {
                'id': 2,
                'check_in': '2024-01-15 08:00:00',
                'check_out': False,
                'worked_hours': 0,
            },
        ]

        result = get_attendance_history(odoo, 1)

        assert result[0]['check_out_dt'] is None


class TestDailySummary:
    def test_sums_hours(self, odoo):
        odoo.safe_search_read.return_value = [
            {'worked_hours': 4.0, 'check_in': '2024-01-15 08:00:00',
             'check_out': '2024-01-15 12:00:00'},
            {'worked_hours': 3.5, 'check_in': '2024-01-15 13:00:00',
             'check_out': '2024-01-15 16:30:00'},
        ]

        result = get_daily_summary(odoo, 1, date(2024, 1, 15))

        assert result['total_hours'] == 7.5
        assert result['total_hours_fmt'] == '7h 30m'
        assert result['record_count'] == 2

    def test_empty_day(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_daily_summary(odoo, 1, date(2024, 1, 15))

        assert result['total_hours'] == 0
        assert result['record_count'] == 0


class TestWeeklySummary:
    def test_groups_by_day(self, odoo):
        # Monday Jan 15 2024
        odoo.safe_search_read.return_value = [
            {'worked_hours': 8.0, 'check_in': '2024-01-15 08:00:00'},
            {'worked_hours': 7.5, 'check_in': '2024-01-16 08:00:00'},
        ]

        result = get_weekly_summary(odoo, 1, date(2024, 1, 15))

        assert len(result['days']) == 7
        assert result['days'][0]['name'] == 'Monday'
        assert result['days'][0]['hours'] == 8.0
        assert result['days'][1]['hours'] == 7.5
        assert result['total_hours'] == 15.5
