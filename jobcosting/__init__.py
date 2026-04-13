from flask import Blueprint

bp = Blueprint('jobcosting', __name__)

from jobcosting import routes  # noqa: E402, F401
