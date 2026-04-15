from flask import Blueprint

bp = Blueprint('auth', __name__)

from auth import routes  # noqa: E402, F401
from auth import admin_routes  # noqa: E402, F401
