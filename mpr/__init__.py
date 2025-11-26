# mpr/__init__.py
from flask import Blueprint

mpr_bp = Blueprint('mpr', __name__, template_folder='templates')

from . import routes  # Import routes to register them