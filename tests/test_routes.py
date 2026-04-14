import pytest


class TestIndexRoute:
    def test_index_page(self, client):
        resp = client.get('/')
        assert resp.status_code == 200
        assert b'Time Clock' in resp.data
        assert b'Job Costing' in resp.data


class TestTimeclockRoutes:
    def test_dashboard_loads(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out'},
        ]

        resp = client.get('/timeclock/')
        assert resp.status_code == 200
        assert b'Time Clock' in resp.data

    def test_select_employee(self, client):
        resp = client.post('/timeclock/select-employee',
                           data={'employee_id': '1'},
                           follow_redirects=False)
        assert resp.status_code == 302

    def test_toggle_without_employee_redirects(self, client):
        resp = client.post('/timeclock/toggle', follow_redirects=False)
        assert resp.status_code == 302

    def test_toggle_with_employee(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
             'last_attendance_id': False},
        ]
        mock_odoo.execute_kw.return_value = {'action': 'sign_in'}

        with client.session_transaction() as sess:
            sess['timeclock_employee_id'] = 1

        resp = client.post('/timeclock/toggle', follow_redirects=False)
        assert resp.status_code == 302

    def test_history_without_employee_redirects(self, client):
        resp = client.get('/timeclock/history', follow_redirects=False)
        assert resp.status_code == 302

    def test_history_with_employee(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        with client.session_transaction() as sess:
            sess['timeclock_employee_id'] = 1

        resp = client.get('/timeclock/history')
        assert resp.status_code == 200

    def test_summary_without_employee_redirects(self, client):
        resp = client.get('/timeclock/summary', follow_redirects=False)
        assert resp.status_code == 302

    def test_api_status_without_employee(self, client):
        resp = client.get('/timeclock/api/status')
        assert resp.status_code == 400


class TestJobcostingRoutes:
    def test_dashboard_loads(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        mock_odoo.read_group.return_value = []

        resp = client.get('/jobcosting/')
        assert resp.status_code == 200
        assert b'Job Costing' in resp.data

    def test_accounts_page(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        resp = client.get('/jobcosting/accounts')
        assert resp.status_code == 200

    def test_entries_page(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        resp = client.get('/jobcosting/entries')
        assert resp.status_code == 200

    def test_create_entry_get(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        resp = client.get('/jobcosting/entries/create')
        assert resp.status_code == 200
        assert b'Create Entry' in resp.data

    def test_create_time_entry_post(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        mock_odoo.create.return_value = 1

        resp = client.post('/jobcosting/entries/create', data={
            'entry_type': 'time',
            'account_id': '10',
            'project_id': '1',
            'task_id': '1',
            'employee_id': '1',
            'entry_date': '2024-01-15',
            'hours': '2.5',
            'hourly_rate': '75.0',
            'description': 'Test entry',
        }, follow_redirects=False)

        assert resp.status_code == 302
        mock_odoo.create.assert_called_once()

    def test_create_entry_missing_account(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        resp = client.post('/jobcosting/entries/create', data={
            'entry_type': 'time',
            'account_id': '',
            'description': 'Test',
            'entry_date': '2024-01-15',
            'hours': '1',
        }, follow_redirects=False)

        assert resp.status_code == 302
        mock_odoo.create.assert_not_called()

    def test_report_list(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []

        resp = client.get('/jobcosting/report')
        assert resp.status_code == 200

    def test_api_tasks(self, client, mock_odoo):
        mock_odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Task 1', 'planned_hours': 10,
             'effective_hours': 5, 'remaining_hours': 5,
             'stage_id': [1, 'In Progress']},
        ]

        resp = client.get('/jobcosting/api/tasks/1')
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 1
        assert data[0]['name'] == 'Task 1'
