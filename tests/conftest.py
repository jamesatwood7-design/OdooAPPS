import pytest
from unittest.mock import MagicMock
from app import create_app
from config import Config


class TestConfig(Config):
    TESTING = True
    ODOO_URL = 'http://test-odoo:8069'
    ODOO_DB = 'test_db'
    ODOO_USERNAME = 'test_user'
    ODOO_PASSWORD = 'test_pass'
    SECRET_KEY = 'test-secret'


@pytest.fixture
def mock_odoo():
    """Returns a mock OdooClient with pre-configured return values."""
    odoo = MagicMock()
    odoo.uid = 1
    odoo.authenticate.return_value = 1
    odoo.search_read.return_value = []
    odoo.safe_search_read.return_value = []
    odoo.search.return_value = []
    odoo.read.return_value = []
    odoo.create.return_value = 1
    odoo.write.return_value = True
    odoo.unlink.return_value = True
    odoo.execute_kw.return_value = True
    odoo.read_group.return_value = []
    odoo.fields_get.return_value = {}
    odoo.get_valid_fields.side_effect = lambda model, fields: fields
    return odoo


@pytest.fixture
def app(mock_odoo):
    """Creates Flask app with mocked Odoo client."""
    application = create_app(TestConfig)
    application.odoo = mock_odoo
    return application


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


@pytest.fixture
def all_permissions():
    """Full permissions dict for admin user."""
    from auth.db import FEATURES
    return {k: {'read': True, 'write': True, 'delete': True} for k, _, _ in FEATURES}


@pytest.fixture
def odoo_user_client(client, all_permissions):
    """Flask test client with full admin session."""
    with client.session_transaction() as sess:
        sess['user_id'] = 'test-user-id'
        sess['username'] = 'admin'
        sess['user_name'] = 'Test User'
        sess['employee_id'] = 1
        sess['permissions'] = all_permissions
        sess['is_manager'] = True
        sess['timeclock_employee_id'] = 1
        sess['timeclock_is_manager'] = True
        sess['auth_type'] = 'odoo_user'
    return client


@pytest.fixture
def employee_client(client):
    """Flask test client with employee-only permissions."""
    with client.session_transaction() as sess:
        sess['user_id'] = 'test-employee-id'
        sess['username'] = 'employee'
        sess['user_name'] = 'Test Employee'
        sess['employee_id'] = 2
        sess['permissions'] = {
            'timeclock': {'read': True, 'write': True, 'delete': False},
        }
        sess['is_manager'] = False
        sess['timeclock_employee_id'] = 2
        sess['timeclock_is_manager'] = False
        sess['auth_type'] = 'employee'
    return client
