from unittest.mock import MagicMock

import pytest

from migration.zoho_client import ZohoBooksClient, ZohoAuthError, ZohoAPIError


def _make_client(session, **overrides):
    kwargs = dict(
        client_id='cid', client_secret='csec', refresh_token='rtok',
        org_id='10', region='US', session=session,
    )
    kwargs.update(overrides)
    return ZohoBooksClient(**kwargs)


def _mock_response(status_code=200, json_body=None, headers=None, text=''):
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_body if json_body is not None else {}
    resp.text = text
    resp.content = b'{}' if json_body else b''
    return resp


def test_invalid_region_raises():
    with pytest.raises(ValueError):
        _make_client(MagicMock(), region='ZZ')


def test_refresh_then_get_succeeds():
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, json_body={'access_token': 'AT', 'expires_in': 3600},
    )
    session.request.return_value = _mock_response(
        200, json_body={'chartofaccounts': []},
    )
    client = _make_client(session)
    result = client.get('/chartofaccounts')
    assert result == {'chartofaccounts': []}
    assert session.post.call_count == 1
    args, kwargs = session.request.call_args
    assert args[0] == 'GET'
    assert 'chartofaccounts' in args[1]
    assert kwargs['params']['organization_id'] == '10'
    assert kwargs['headers']['Authorization'] == 'Zoho-oauthtoken AT'


def test_refresh_failure_raises():
    session = MagicMock()
    session.post.return_value = _mock_response(401, text='bad')
    client = _make_client(session)
    with pytest.raises(ZohoAuthError):
        client.get('/contacts')


def test_401_triggers_token_refresh_and_retry():
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, json_body={'access_token': 'AT2', 'expires_in': 3600},
    )
    session.request.side_effect = [
        _mock_response(401, text='expired'),
        _mock_response(200, json_body={'ok': True}),
    ]
    client = _make_client(session)
    result = client.get('/contacts')
    assert result == {'ok': True}
    # Initial token + refresh on 401 = 2 token POSTs
    assert session.post.call_count == 2
    assert session.request.call_count == 2


def test_429_sleeps_and_retries(monkeypatch):
    sleeps = []
    monkeypatch.setattr('migration.zoho_client.time.sleep',
                        lambda s: sleeps.append(s))
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, json_body={'access_token': 'AT', 'expires_in': 3600},
    )
    session.request.side_effect = [
        _mock_response(429, headers={'Retry-After': '1'}),
        _mock_response(200, json_body={'ok': True}),
    ]
    client = _make_client(session)
    assert client.get('/contacts') == {'ok': True}
    assert 1 in sleeps


def test_5xx_retries_with_backoff(monkeypatch):
    monkeypatch.setattr('migration.zoho_client.time.sleep', lambda s: None)
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, json_body={'access_token': 'AT', 'expires_in': 3600},
    )
    session.request.side_effect = [
        _mock_response(503, text='down'),
        _mock_response(503, text='down'),
        _mock_response(200, json_body={'ok': True}),
    ]
    client = _make_client(session)
    assert client.get('/x') == {'ok': True}
    assert session.request.call_count == 3


def test_4xx_raises_zoho_api_error():
    session = MagicMock()
    session.post.return_value = _mock_response(
        200, json_body={'access_token': 'AT', 'expires_in': 3600},
    )
    session.request.return_value = _mock_response(400, text='bad request')
    client = _make_client(session)
    with pytest.raises(ZohoAPIError) as excinfo:
        client.post('/contacts', {'x': 1})
    assert excinfo.value.status_code == 400


def test_dry_run_skips_writes():
    session = MagicMock()
    client = _make_client(session, dry_run=True)
    result = client.create_invoice({'foo': 'bar'})
    assert result['_dry_run'] is True
    assert result['method'] == 'POST'
    assert result['path'] == '/invoices'
    # No HTTP calls made
    assert not session.post.called
    assert not session.request.called
