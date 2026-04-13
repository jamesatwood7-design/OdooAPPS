from flask import Blueprint

bp = Blueprint('timeclock', __name__)

from timeclock import routes  # noqa: E402, F401
