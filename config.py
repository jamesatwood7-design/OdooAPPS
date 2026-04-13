import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    ODOO_URL = os.environ.get('ODOO_URL', 'http://localhost:8069')
    ODOO_DB = os.environ.get('ODOO_DB', 'odoo')
    ODOO_USERNAME = os.environ.get('ODOO_USERNAME', 'admin')
    ODOO_PASSWORD = os.environ.get('ODOO_PASSWORD', 'admin')
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
