class OdooConnectionError(Exception):
    """Raised when the Odoo server cannot be reached."""
    pass


class OdooAuthenticationError(Exception):
    """Raised when authentication with Odoo fails."""
    pass


class OdooAPIError(Exception):
    """Raised when an Odoo API call returns an error."""
    pass
