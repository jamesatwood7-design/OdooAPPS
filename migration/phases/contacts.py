from migration import mappers
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'res.partner'
ZOHO_TYPE = 'contact'

FIELDS = [
    'id', 'name', 'company_name', 'is_company',
    'email', 'phone', 'mobile', 'website', 'vat',
    'street', 'street2', 'city', 'zip',
    'state_id', 'country_id', 'currency_id',
    'customer_rank', 'supplier_rank', 'parent_id',
]


def migrate(odoo, zoho, id_map, dry_run, logger):
    """Create one Zoho contact per (partner, role). A partner that's both
    customer and vendor in Odoo becomes two Zoho contacts (customer + vendor)
    because Zoho contact_type is exclusive."""
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    # Skip "child" contacts (employees of a parent company etc.) - they can be
    # imported separately if needed.
    domain = [
        '|',
        ('customer_rank', '>', 0),
        ('supplier_rank', '>', 0),
        ('parent_id', '=', False),
    ]
    for rec in paginate(odoo, MODEL, domain, FIELDS):
        roles = []
        if (rec.get('customer_rank') or 0) > 0:
            roles.append('customer')
        if (rec.get('supplier_rank') or 0) > 0:
            roles.append('vendor')
        if not roles:
            continue
        for role in roles:
            _migrate_one(zoho, id_map, logger, rec, role, counts)
    return counts


def _migrate_one(zoho, id_map, logger, rec, role, counts):
    odoo_id = rec['id']
    existing = id_map.get_zoho_id(MODEL, odoo_id, variant=role)
    if existing:
        record_skip(logger, MODEL, odoo_id, existing, variant=role)
        counts['skipped'] += 1
        return
    body = mappers.map_contact(rec, contact_type=role)
    try:
        resp = zoho.create_contact(body)
        zoho_id = extract_zoho_id(resp, 'contact')
        if not zoho_id:
            raise ValueError(f'No id in response: {resp}')
        record_success(logger, id_map, MODEL, odoo_id,
                       ZOHO_TYPE, zoho_id, variant=role)
        counts['created'] += 1
    except Exception as e:
        record_failure(logger, id_map, MODEL, odoo_id, e,
                       ZOHO_TYPE, variant=role)
        counts['failed'] += 1
