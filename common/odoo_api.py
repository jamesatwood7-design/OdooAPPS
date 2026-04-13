import xmlrpc.client
from common.exceptions import OdooConnectionError, OdooAuthenticationError, OdooAPIError


class OdooClient:
    """XML-RPC client for communicating with an Odoo server.

    This is the single gateway to Odoo - no other module should use
    xmlrpc.client directly.
    """

    def __init__(self, url, db, username, password):
        self.url = url.rstrip('/')
        self.db = db
        self.username = username
        self.password = password
        self.uid = None
        self._common_proxy = None
        self._object_proxy = None

    def _get_common_proxy(self):
        if self._common_proxy is None:
            try:
                self._common_proxy = xmlrpc.client.ServerProxy(
                    f'{self.url}/xmlrpc/2/common', allow_none=True
                )
            except Exception as e:
                raise OdooConnectionError(f'Cannot connect to Odoo at {self.url}: {e}')
        return self._common_proxy

    def _get_object_proxy(self):
        if self._object_proxy is None:
            try:
                self._object_proxy = xmlrpc.client.ServerProxy(
                    f'{self.url}/xmlrpc/2/object', allow_none=True
                )
            except Exception as e:
                raise OdooConnectionError(f'Cannot connect to Odoo at {self.url}: {e}')
        return self._object_proxy

    def authenticate(self):
        """Authenticate with the Odoo server and store the user ID."""
        try:
            common = self._get_common_proxy()
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

        Args:
            model: Odoo model name (e.g. 'hr.employee')
            method: Method to call (e.g. 'search_read')
            args: Positional arguments as a list
            kwargs: Keyword arguments as a dict
        """
        if self.uid is None:
            self.authenticate()

        if kwargs is None:
            kwargs = {}

        try:
            obj = self._get_object_proxy()
            return obj.execute_kw(
                self.db, self.uid, self.password,
                model, method, args, kwargs
            )
        except xmlrpc.client.Fault as e:
            raise OdooAPIError(f'Odoo API error on {model}.{method}: {e.faultString}')
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

    def read_group(self, model, domain, fields, groupby, offset=0, limit=None, orderby=None):
        """Read grouped and aggregated data (server-side aggregation)."""
        kwargs = {'offset': offset, 'lazy': True}
        if limit is not None:
            kwargs['limit'] = limit
        if orderby is not None:
            kwargs['orderby'] = orderby
        return self.execute_kw(model, 'read_group', [domain, fields, groupby], kwargs)
