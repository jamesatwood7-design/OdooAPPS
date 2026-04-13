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
    odoo.search.return_value = []
    odoo.read.return_value = []
    odoo.create.return_value = 1
    odoo.write.return_value = True
    odoo.unlink.return_value = True
    odoo.execute_kw.return_value = True
    odoo.read_group.return_value = []
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
