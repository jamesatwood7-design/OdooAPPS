import xmlrpc.client
import http.client
from common.exceptions import OdooConnectionError, OdooAuthenticationError, OdooAPIError


class OdooClient:
    """XML-RPC client for communicating with an Odoo server.

    This is the single gateway to Odoo - no other module should use
    xmlrpc.client directly.

    A fresh ServerProxy is created for each call to avoid stale HTTP
    connection issues (CannotSendRequest) that occur when a single
    proxy is reused across multiple Flask requests.
    """

    def __init__(self, url, db, username, password):
        self.url = url.rstrip('/')
        self.db = db
        self.username = username
        self.password = password
        self.uid = None
        self._model_fields_cache = {}

    def _make_proxy(self, endpoint):
        """Create a fresh ServerProxy for the given endpoint."""
        try:
            transport = xmlrpc.client.SafeTransport() if self.url.startswith('https') else None
            return xmlrpc.client.ServerProxy(
                f'{self.url}/xmlrpc/2/{endpoint}',
                allow_none=True,
                transport=transport,
            )
        except Exception as e:
            raise OdooConnectionError(f'Cannot connect to Odoo at {self.url}: {e}')

    def authenticate(self):
        """Authenticate with the Odoo server and store the user ID."""
        try:
            common = self._make_proxy('common')
            self.uid = common.authenticate(self.db, self.username, self.password, {})
        except OdooConnectionError:
            raise
        except Exception as e:
            raise OdooConnectionError(f'Cannot connect to Odoo at {self.url}: {e}')

        if not self.uid:
            raise OdooAuthenticationError(
                f'Authentication failed for user "{self.username}" on database "{self.db}"'
            )
        return self.uid

    def execute_kw(self, model, method, args, kwargs=None):
        """Execute an Odoo RPC call.

        A fresh ServerProxy is created for each call to prevent
        stale connection errors.
        """
        if self.uid is None:
            self.authenticate()

        if kwargs is None:
            kwargs = {}

        try:
            obj = self._make_proxy('object')
            return obj.execute_kw(
                self.db, self.uid, self.password,
                model, method, args, kwargs
            )
        except xmlrpc.client.Fault as e:
            raise OdooAPIError(f'Odoo API error on {model}.{method}: {e.faultString}')
        except xmlrpc.client.ProtocolError as e:
            raise OdooConnectionError(f'Protocol error communicating with Odoo: {e}')
        except http.client.CannotSendRequest as e:
            raise OdooConnectionError(f'Connection error with Odoo (try again): {e}')
        except (ConnectionRefusedError, OSError) as e:
            raise OdooConnectionError(f'Lost connection to Odoo: {e}')

    def search(self, model, domain, offset=0, limit=None, order=None):
        """Search for record IDs matching the domain."""
        kwargs = {'offset': offset}
        if limit is not None:
            kwargs['limit'] = limit
        if order is not None:
            kwargs['order'] = order
        return self.execute_kw(model, 'search', [domain], kwargs)

    def read(self, model, ids, fields=None):
        """Read records by their IDs."""
        kwargs = {}
        if fields is not None:
            kwargs['fields'] = fields
        return self.execute_kw(model, 'read', [ids], kwargs)

    def search_read(self, model, domain, fields=None, offset=0, limit=None, order=None):
        """Search and read records in a single call."""
        kwargs = {'offset': offset}
        if fields is not None:
            kwargs['fields'] = fields
        if limit is not None:
            kwargs['limit'] = limit
        if order is not None:
            kwargs['order'] = order
        return self.execute_kw(model, 'search_read', [domain], kwargs)

    def create(self, model, values):
        """Create a new record and return its ID."""
        return self.execute_kw(model, 'create', [values])

    def write(self, model, ids, values):
        """Update existing records."""
        return self.execute_kw(model, 'write', [ids, values])

    def unlink(self, model, ids):
        """Delete records."""
        return self.execute_kw(model, 'unlink', [ids])

    def fields_get(self, model, attributes=None):
        """Get field definitions for a model. Results are cached."""
        if model in self._model_fields_cache:
            return self._model_fields_cache[model]
        if attributes is None:
            attributes = ['string', 'type']
        result = self.execute_kw(model, 'fields_get', [], {'attributes': attributes})
        self._model_fields_cache[model] = result
        return result

    def get_valid_fields(self, model, requested_fields):
        """Filter a list of requested fields to only those that exist on the model."""
        try:
            available = self.fields_get(model)
            return [f for f in requested_fields if f in available]
        except Exception:
            return requested_fields

    def safe_search_read(self, model, domain, fields=None, offset=0, limit=None, order=None):
        """Like search_read but validates fields exist first, dropping invalid ones."""
        if fields:
            fields = self.get_valid_fields(model, fields)
            if not fields:
                fields = None
        return self.search_read(model, domain, fields=fields, offset=offset,
                                limit=limit, order=order)

    def read_group(self, model, domain, fields, groupby, offset=0, limit=None, orderby=None):
        """Read grouped and aggregated data (server-side aggregation)."""
        kwargs = {'offset': offset, 'lazy': True}
        if limit is not None:
            kwargs['limit'] = limit
        if orderby is not None:
            kwargs['orderby'] = orderby
        return self.execute_kw(model, 'read_group', [domain, fields, groupby], kwargs)
