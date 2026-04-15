from flask import Blueprint

bp = Blueprint('accounting', __name__)

from accounting import routes  # noqa: E402, F401
