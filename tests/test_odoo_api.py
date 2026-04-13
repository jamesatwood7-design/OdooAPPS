import pytest
from unittest.mock import patch, MagicMock
import xmlrpc.client

from common.odoo_api import OdooClient
from common.exceptions import (
    OdooConnectionError, OdooAuthenticationError, OdooAPIError,
)


class TestOdooClientAuthentication:
    def test_authenticate_success(self):
        with patch('xmlrpc.client.ServerProxy') as mock_proxy_cls:
            mock_common = MagicMock()
            mock_common.authenticate.return_value = 42
            mock_proxy_cls.return_value = mock_common

            client = OdooClient('http://localhost:8069', 'testdb', 'admin', 'admin')
            uid = client.authenticate()

            assert uid == 42
            assert client.uid == 42
            mock_common.authenticate.assert_called_once_with(
                'testdb', 'admin', 'admin', {}
            )

    def test_authenticate_failure(self):
        with patch('xmlrpc.client.ServerProxy') as mock_proxy_cls:
            mock_common = MagicMock()
            mock_common.authenticate.return_value = False
            mock_proxy_cls.return_value = mock_common

            client = OdooClient('http://localhost:8069', 'testdb', 'admin', 'wrong')

            with pytest.raises(OdooAuthenticationError):
                client.authenticate()

    def test_authenticate_connection_error(self):
        with patch('xmlrpc.client.ServerProxy') as mock_proxy_cls:
            mock_proxy_cls.side_effect = ConnectionRefusedError('Connection refused')

            client = OdooClient('http://localhost:8069', 'testdb', 'admin', 'admin')

            with pytest.raises(OdooConnectionError):
                client.authenticate()


class TestOdooClientOperations:
    def setup_method(self):
        self.mock_object = MagicMock()
        self.mock_common = MagicMock()
        self.mock_common.authenticate.return_value = 1

    def _make_client(self):
        client = OdooClient('http://localhost:8069', 'testdb', 'admin', 'admin')
        client._common_proxy = self.mock_common
        client._object_proxy = self.mock_object
        client.uid = 1
        return client

    def test_search_read(self):
        client = self._make_client()
        self.mock_object.execute_kw.return_value = [
            {'id': 1, 'name': 'Test'}
        ]

        result = client.search_read(
            'hr.employee', [('id', '=', 1)],
            fields=['id', 'name']
        )

        self.mock_object.execute_kw.assert_called_once_with(
            'testdb', 1, 'admin',
            'hr.employee', 'search_read',
            [[('id', '=', 1)]],
            {'offset': 0, 'fields': ['id', 'name']},
        )
        assert result == [{'id': 1, 'name': 'Test'}]

    def test_create(self):
        client = self._make_client()
        self.mock_object.execute_kw.return_value = 5

        result = client.create('hr.attendance', {
            'employee_id': 1,
            'check_in': '2024-01-01 08:00:00',
        })

        assert result == 5

    def test_write(self):
        client = self._make_client()
        self.mock_object.execute_kw.return_value = True

        result = client.write('hr.attendance', [5], {
            'check_out': '2024-01-01 17:00:00',
        })

        assert result is True

    def test_api_error(self):
        client = self._make_client()
        self.mock_object.execute_kw.side_effect = xmlrpc.client.Fault(
            1, 'Access Denied'
        )

        with pytest.raises(OdooAPIError):
            client.search_read('hr.employee', [])

    def test_connection_lost(self):
        client = self._make_client()
        self.mock_object.execute_kw.side_effect = ConnectionRefusedError(
            'Connection refused'
        )

        with pytest.raises(OdooConnectionError):
            client.search_read('hr.employee', [])

    def test_url_trailing_slash_stripped(self):
        client = OdooClient('http://localhost:8069/', 'db', 'u', 'p')
        assert client.url == 'http://localhost:8069'
