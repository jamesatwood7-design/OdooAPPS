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
    SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
    SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
    ZOHO_CLIENT_ID = os.environ.get('ZOHO_CLIENT_ID', '')
    ZOHO_CLIENT_SECRET = os.environ.get('ZOHO_CLIENT_SECRET', '')
    ZOHO_REFRESH_TOKEN = os.environ.get('ZOHO_REFRESH_TOKEN', '')
    ZOHO_ORG_ID = os.environ.get('ZOHO_ORG_ID', '')
    ZOHO_REGION = os.environ.get('ZOHO_REGION', 'US')
    MIGRATION_STATE_DIR = os.environ.get(
        'MIGRATION_STATE_DIR',
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'migration', 'state'),
    )
