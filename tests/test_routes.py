import pytest


class TestAuthRoutes:
    def test_unauthenticated_redirects_to_login(self, client):
        resp = client.get('/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/login' in resp.headers['Location']

    def test_login_page_loads(self, client):
        resp = client.get('/login')
        assert resp.status_code == 200
        assert b'Sign In' in resp.data

    def test_logout_clears_session(self, odoo_user_client):
        resp = odoo_user_client.get('/logout', follow_redirects=False)
        assert resp.status_code == 302


class TestAccessControl:
    def test_employee_cannot_access_jobcosting(self, employee_client):
        resp = employee_client.get('/jobcosting/', follow_redirects=False)
        assert resp.status_code == 302

    def test_employee_can_access_timeclock(self, employee_client, mock_odoo):
        mock_odoo.safe_search_read.side_effect = lambda model, domain, **kw: (
            [{'id': 2, 'name': 'Test', 'attendance_state': 'checked_out',
              'last_attendance_id': False, 'parent_id': False}]
            if model == 'hr.employee' else []
        )
        mock_odoo.search.return_value = []
        resp = employee_client.get('/timeclock/')
        assert resp.status_code == 200

    def test_odoo_user_can_access_jobcosting(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        mock_odoo.read_group.return_value = []
        mock_odoo.fields_get.return_value = {}
        mock_odoo.search_read.return_value = []
        resp = odoo_user_client.get('/jobcosting/jobs')
        assert resp.status_code == 200


class TestTimeclockRoutes:
    def test_dashboard_loads(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.side_effect = lambda model, domain, **kw: (
            [{'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
              'parent_id': False, 'last_attendance_id': False}]
            if model == 'hr.employee' else []
        )
        mock_odoo.search.return_value = []

        resp = odoo_user_client.get('/timeclock/')
        assert resp.status_code == 200
        assert b'Time Clock' in resp.data

    def test_select_employee(self, odoo_user_client):
        resp = odoo_user_client.post('/timeclock/select-employee',
                                     data={'employee_id': '1'},
                                     follow_redirects=False)
        assert resp.status_code == 302

    def test_toggle_without_employee_redirects(self, odoo_user_client):
        with odoo_user_client.session_transaction() as sess:
            sess.pop('timeclock_employee_id', None)
        resp = odoo_user_client.post('/timeclock/toggle', follow_redirects=False)
        assert resp.status_code == 302

    def test_toggle_with_employee(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Alice', 'attendance_state': 'checked_out',
             'last_attendance_id': False, 'parent_id': False},
        ]
        mock_odoo.execute_kw.return_value = {'action': 'sign_in'}

        resp = odoo_user_client.post('/timeclock/toggle', follow_redirects=False)
        assert resp.status_code == 302

    def test_history_requires_odoo_user(self, employee_client):
        resp = employee_client.get('/timeclock/history', follow_redirects=False)
        assert resp.status_code == 302

    def test_history_with_odoo_user(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        resp = odoo_user_client.get('/timeclock/history')
        assert resp.status_code == 200

    def test_summary_requires_odoo_user(self, employee_client):
        resp = employee_client.get('/timeclock/summary', follow_redirects=False)
        assert resp.status_code == 302

    def test_api_status_without_employee(self, odoo_user_client):
        with odoo_user_client.session_transaction() as sess:
            sess.pop('timeclock_employee_id', None)
        resp = odoo_user_client.get('/timeclock/api/status')
        assert resp.status_code == 400


class TestJobcostingRoutes:
    def test_dashboard_redirects_to_jobs(self, odoo_user_client):
        resp = odoo_user_client.get('/jobcosting/', follow_redirects=False)
        assert resp.status_code == 302
        assert '/jobs' in resp.headers['Location']

    def test_entries_page(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        resp = odoo_user_client.get('/jobcosting/entries')
        assert resp.status_code == 200

    def test_create_entry_get(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        resp = odoo_user_client.get('/jobcosting/entries/create')
        assert resp.status_code == 200
        assert b'Create Entry' in resp.data

    def test_create_time_entry_post(self, odoo_user_client, mock_odoo):
        mock_odoo.safe_search_read.return_value = []
        mock_odoo.create.return_value = 1

        resp = odoo_user_client.post('/jobcosting/entries/create', data={
            'entry_type': 'time',
            'account_id': '10',
            'employee_id': '1',
            'entry_date': '2024-01-15',
            'hours': '2.5',
            'hourly_rate': '75.0',
            'description': 'Test entry',
        }, follow_redirects=False)

        assert resp.status_code == 302
        mock_odoo.create.assert_called_once()


class TestJobsRoutes:
    def test_jobs_dashboard_loads(self, odoo_user_client, mock_odoo):
        mock_odoo.fields_get.return_value = {
            'id': {'string': 'ID', 'type': 'integer'},
            'name': {'string': 'Name', 'type': 'char'},
            'code': {'string': 'Code', 'type': 'char'},
        }
        mock_odoo.search_read.return_value = [
            {'id': 1, 'name': 'Test Job', 'code': 'S001'},
        ]
        resp = odoo_user_client.get('/jobcosting/jobs')
        assert resp.status_code == 200
        assert b'Jobs' in resp.data

    def test_job_detail_loads(self, odoo_user_client, mock_odoo):
        mock_odoo.fields_get.return_value = {
            'id': {'string': 'ID', 'type': 'integer'},
            'name': {'string': 'Name', 'type': 'char'},
            'code': {'string': 'Code', 'type': 'char'},
        }
        mock_odoo.search_read.return_value = [
            {'id': 1, 'name': 'Test Job', 'code': 'S001'},
        ]
        mock_odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Test Job', 'code': 'S001'},
        ]
        resp = odoo_user_client.get('/jobcosting/job/1')
        assert resp.status_code == 200
        assert b'Test Job' in resp.data

    def test_job_detail_not_found(self, odoo_user_client, mock_odoo):
        mock_odoo.fields_get.return_value = {}
        mock_odoo.search_read.return_value = []
        mock_odoo.safe_search_read.return_value = []
        resp = odoo_user_client.get('/jobcosting/job/999', follow_redirects=False)
        assert resp.status_code == 302

    def test_employee_cannot_access_jobs(self, employee_client):
        resp = employee_client.get('/jobcosting/jobs', follow_redirects=False)
        assert resp.status_code == 302
