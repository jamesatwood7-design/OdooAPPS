import time
import threading
from collections import deque

import requests


class ZohoAuthError(Exception):
    pass


class ZohoAPIError(Exception):
    def __init__(self, message, status_code=None, body=None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


REGION_API_DOMAINS = {
    'US': 'zohoapis.com',
    'EU': 'zohoapis.eu',
    'IN': 'zohoapis.in',
    'AU': 'zohoapis.com.au',
    'JP': 'zohoapis.jp',
}

REGION_ACCOUNTS_DOMAINS = {
    'US': 'accounts.zoho.com',
    'EU': 'accounts.zoho.eu',
    'IN': 'accounts.zoho.in',
    'AU': 'accounts.zoho.com.au',
    'JP': 'accounts.zoho.jp',
}


class _RateLimiter:
    """Token bucket: max_calls per window_seconds."""

    def __init__(self, max_calls, window_seconds):
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls = deque()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self.window:
                self._calls.popleft()
            if len(self._calls) >= self.max_calls:
                wait = self.window - (now - self._calls[0])
                if wait > 0:
                    time.sleep(wait)
                self._calls.popleft()
            self._calls.append(time.monotonic())


class ZohoBooksClient:
    """REST client for Zoho Books v3 API.

    Handles OAuth refresh, region-aware base URL, organization_id injection,
    and 401/429/5xx retries.
    """

    def __init__(self, client_id, client_secret, refresh_token, org_id,
                 region='US', dry_run=False, session=None):
        if region not in REGION_API_DOMAINS:
            raise ValueError(f'Unknown ZOHO_REGION: {region}')
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.org_id = str(org_id)
        self.region = region
        self.api_base = f'https://www.{REGION_API_DOMAINS[region]}/books/v3'
        self.accounts_base = f'https://{REGION_ACCOUNTS_DOMAINS[region]}'
        self.dry_run = dry_run
        self._access_token = None
        self._access_token_expiry = 0.0
        self._session = session or requests.Session()
        # Zoho Books default: ~100 calls/minute per org.
        self._limiter = _RateLimiter(100, 60)
        self._daily_count = 0
        self._daily_warned = False

    def _refresh_access_token(self):
        url = f'{self.accounts_base}/oauth/v2/token'
        data = {
            'refresh_token': self.refresh_token,
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'refresh_token',
        }
        resp = self._session.post(url, data=data, timeout=30)
        if resp.status_code != 200:
            raise ZohoAuthError(
                f'Token refresh failed ({resp.status_code}): {resp.text}'
            )
        body = resp.json()
        if 'access_token' not in body:
            raise ZohoAuthError(f'Token refresh returned no access_token: {body}')
        self._access_token = body['access_token']
        # Zoho access tokens are valid for ~1h; subtract a buffer.
        expires_in = int(body.get('expires_in', 3600))
        self._access_token_expiry = time.monotonic() + max(60, expires_in - 60)

    def _ensure_token(self):
        if not self._access_token or time.monotonic() >= self._access_token_expiry:
            self._refresh_access_token()

    def _request(self, method, path, params=None, json=None, _retry_on_auth=True,
                 _attempt=0):
        if self.dry_run and method.upper() != 'GET':
            return {'_dry_run': True, 'method': method, 'path': path, 'body': json}

        self._ensure_token()
        self._limiter.acquire()
        self._daily_count += 1
        if self._daily_count >= 900 and not self._daily_warned:
            self._daily_warned = True

        url = f'{self.api_base}{path}'
        merged_params = {'organization_id': self.org_id}
        if params:
            merged_params.update(params)
        headers = {'Authorization': f'Zoho-oauthtoken {self._access_token}'}

        try:
            resp = self._session.request(
                method, url,
                params=merged_params,
                json=json,
                headers=headers,
                timeout=60,
            )
        except requests.RequestException as e:
            if _attempt < 5:
                time.sleep(2 ** _attempt)
                return self._request(method, path, params=params, json=json,
                                     _retry_on_auth=_retry_on_auth,
                                     _attempt=_attempt + 1)
            raise ZohoAPIError(f'Network error: {e}')

        if resp.status_code == 401 and _retry_on_auth:
            self._refresh_access_token()
            return self._request(method, path, params=params, json=json,
                                 _retry_on_auth=False, _attempt=_attempt)

        if resp.status_code == 429:
            retry_after = int(resp.headers.get('Retry-After', '60'))
            time.sleep(retry_after)
            if _attempt < 5:
                return self._request(method, path, params=params, json=json,
                                     _retry_on_auth=_retry_on_auth,
                                     _attempt=_attempt + 1)
            raise ZohoAPIError('Rate-limited (429), retries exhausted',
                               status_code=429, body=resp.text)

        if 500 <= resp.status_code < 600:
            if _attempt < 5:
                time.sleep(2 ** _attempt)
                return self._request(method, path, params=params, json=json,
                                     _retry_on_auth=_retry_on_auth,
                                     _attempt=_attempt + 1)
            raise ZohoAPIError(f'Server error {resp.status_code}',
                               status_code=resp.status_code, body=resp.text)

        if resp.status_code >= 400:
            raise ZohoAPIError(
                f'Zoho API error {resp.status_code} on {method} {path}: {resp.text}',
                status_code=resp.status_code, body=resp.text,
            )

        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            return {'raw': resp.text}

    def get(self, path, params=None):
        return self._request('GET', path, params=params)

    def post(self, path, body):
        return self._request('POST', path, json=body)

    def put(self, path, body):
        return self._request('PUT', path, json=body)

    # --- convenience wrappers used by phase modules ---

    def list_currencies(self):
        return self.get('/settings/currencies')

    def create_account(self, body):
        return self.post('/chartofaccounts', body)

    def create_tax(self, body):
        return self.post('/settings/taxes', body)

    def create_tax_group(self, body):
        return self.post('/settings/taxgroups', body)

    def create_contact(self, body):
        return self.post('/contacts', body)

    def create_invoice(self, body):
        return self.post('/invoices', body)

    def create_bill(self, body):
        return self.post('/bills', body)

    def create_journal(self, body):
        return self.post('/journals', body)

    def create_credit_note(self, body):
        return self.post('/creditnotes', body)

    def create_vendor_credit(self, body):
        return self.post('/vendorcredits', body)

    def create_customer_payment(self, body):
        return self.post('/customerpayments', body)

    def create_vendor_payment(self, body):
        return self.post('/vendorpayments', body)

    def create_project(self, body):
        return self.post('/projects', body)

    def log_time_entry(self, body):
        return self.post('/projects/timeentries', body)

    @property
    def daily_call_count(self):
        return self._daily_count
