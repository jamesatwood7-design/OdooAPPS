import pytest
from unittest.mock import MagicMock
from datetime import date

from jobcosting.services import (
    get_analytic_accounts, get_projects, get_project,
    get_tasks_for_project, get_analytic_lines,
    create_time_entry, create_expense_entry,
    get_project_detail, get_job_cost_report,
)


@pytest.fixture
def odoo():
    mock = MagicMock()
    mock.uid = 1
    return mock


class TestAnalyticAccounts:
    def test_get_all(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Acct A', 'code': 'AA', 'balance': 100.0,
             'debit': 200.0, 'credit': 100.0},
        ]

        result = get_analytic_accounts(odoo)

        assert len(result) == 1
        assert result[0]['name'] == 'Acct A'

    def test_get_with_domain(self, odoo):
        odoo.safe_search_read.return_value = []

        get_analytic_accounts(odoo, domain=[('code', '=', 'X')])

        call_args = odoo.safe_search_read.call_args
        assert ('account.analytic.account', [('code', '=', 'X')]) == call_args[0]


class TestProjects:
    def test_get_projects(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Project Alpha',
             'analytic_account_id': [10, 'Alpha Acct'],
             'date_start': '2024-01-01', 'date': False, 'task_count': 5},
        ]

        result = get_projects(odoo)

        assert len(result) == 1
        assert result[0]['task_count'] == 5

    def test_get_project_found(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Project Alpha',
             'analytic_account_id': [10, 'Alpha Acct'],
             'date_start': '2024-01-01', 'date': False, 'task_count': 5},
        ]

        result = get_project(odoo, 1)

        assert result['name'] == 'Project Alpha'

    def test_get_project_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_project(odoo, 999)

        assert result is None


class TestTasks:
    def test_get_tasks(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Task 1', 'planned_hours': 10.0,
             'effective_hours': 6.0, 'remaining_hours': 4.0,
             'stage_id': [1, 'In Progress']},
        ]

        result = get_tasks_for_project(odoo, 1)

        assert len(result) == 1
        assert result[0]['planned_hours'] == 10.0


class TestAnalyticLines:
    def test_get_lines_formatted(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Dev work', 'date': '2024-01-15',
             'amount': -150.0, 'unit_amount': 2.0,
             'employee_id': [1, 'Alice'], 'project_id': [1, 'Alpha'],
             'task_id': [1, 'Task 1'], 'account_id': [10, 'Acct']},
        ]

        result = get_analytic_lines(odoo, project_id=1)

        assert len(result) == 1
        assert result[0]['unit_amount_fmt'] == '2h 00m'
        assert result[0]['date_obj'] == date(2024, 1, 15)


class TestCreateEntries:
    def test_create_time_entry_with_rate(self, odoo):
        odoo.create.return_value = 100

        result = create_time_entry(
            odoo, account_id=10, project_id=1, task_id=1,
            employee_id=1, entry_date=date(2024, 1, 15),
            hours=2.5, description='Development work', hourly_rate=75.0,
        )

        assert result == 100
        call_args = odoo.create.call_args[0]
        assert call_args[0] == 'account.analytic.line'
        values = call_args[1]
        assert values['unit_amount'] == 2.5
        assert values['amount'] == -(2.5 * 75.0)
        assert values['name'] == 'Development work'

    def test_create_time_entry_no_rate(self, odoo):
        odoo.create.return_value = 101

        create_time_entry(
            odoo, account_id=10, project_id=1, task_id=None,
            employee_id=None, entry_date=date(2024, 1, 15),
            hours=3.0, description='Research',
        )

        values = odoo.create.call_args[0][1]
        assert values['amount'] == 0
        assert 'task_id' not in values
        assert 'employee_id' not in values

    def test_create_expense_entry(self, odoo):
        odoo.create.return_value = 102

        create_expense_entry(
            odoo, account_id=10, entry_date=date(2024, 1, 15),
            amount=250.0, description='Materials', project_id=1,
        )

        values = odoo.create.call_args[0][1]
        assert values['amount'] == -250.0
        assert values['name'] == 'Materials'
        assert values['project_id'] == 1


class TestProjectDetail:
    def test_returns_aggregated_data(self, odoo):
        def mock_search_read(model, domain, **kwargs):
            if model == 'project.project':
                return [{'id': 1, 'name': 'Alpha',
                         'analytic_account_id': [10, 'Acct'],
                         'date_start': False, 'date': False, 'task_count': 2}]
            elif model == 'project.task':
                return [
                    {'id': 1, 'name': 'Task 1', 'planned_hours': 10.0,
                     'effective_hours': 6.0, 'remaining_hours': 4.0,
                     'stage_id': [1, 'Done']},
                    {'id': 2, 'name': 'Task 2', 'planned_hours': 20.0,
                     'effective_hours': 15.0, 'remaining_hours': 5.0,
                     'stage_id': [2, 'In Progress']},
                ]
            elif model == 'account.analytic.line':
                return [
                    {'id': 1, 'name': 'Work', 'date': '2024-01-15',
                     'amount': -450.0, 'unit_amount': 6.0,
                     'employee_id': False, 'project_id': [1, 'Alpha'],
                     'task_id': [1, 'Task 1'], 'account_id': [10, 'Acct']},
                    {'id': 2, 'name': 'More work', 'date': '2024-01-16',
                     'amount': -1125.0, 'unit_amount': 15.0,
                     'employee_id': False, 'project_id': [1, 'Alpha'],
                     'task_id': [2, 'Task 2'], 'account_id': [10, 'Acct']},
                ]
            return []

        odoo.safe_search_read.side_effect = mock_search_read

        result = get_project_detail(odoo, 1)

        assert result is not None
        assert result['totals']['budgeted_hours'] == 30.0
        assert result['totals']['actual_hours'] == 21.0
        assert result['totals']['total_cost'] == 1575.0
        assert result['totals']['variance_sign'] == 'under'

    def test_project_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_project_detail(odoo, 999)

        assert result is None


class TestJobCostReport:
    def test_budget_vs_actual(self, odoo):
        call_count = [0]

        def mock_search_read(model, domain, **kwargs):
            if model == 'project.project':
                return [{'id': 1, 'name': 'Alpha',
                         'analytic_account_id': [10, 'Acct'],
                         'date_start': False, 'date': False, 'task_count': 1}]
            elif model == 'project.task':
                return [
                    {'id': 1, 'name': 'Task 1', 'planned_hours': 40.0,
                     'effective_hours': 45.0, 'remaining_hours': -5.0,
                     'stage_id': [1, 'In Progress']},
                ]
            return []

        odoo.safe_search_read.side_effect = mock_search_read
        odoo.read_group.return_value = [
            {'task_id': [1, 'Task 1'], 'unit_amount': 45.0,
             'amount': -3375.0, '__count': 10},
        ]

        result = get_job_cost_report(odoo, 1)

        assert result is not None
        assert len(result['task_rows']) == 1
        assert result['task_rows'][0]['budgeted_hours'] == 40.0
        assert result['task_rows'][0]['actual_hours'] == 45.0
        assert result['task_rows'][0]['variance_sign'] == 'over'
        assert result['totals']['variance_sign'] == 'over'

    def test_empty_project(self, odoo):
        odoo.safe_search_read.side_effect = lambda model, domain, **kw: (
            [{'id': 1, 'name': 'Empty', 'analytic_account_id': False,
              'date_start': False, 'date': False, 'task_count': 0}]
            if model == 'project.project' else []
        )
        odoo.read_group.return_value = []

        result = get_job_cost_report(odoo, 1)

        assert result is not None
        assert result['totals']['budgeted_hours'] == 0
        assert result['totals']['actual_hours'] == 0
