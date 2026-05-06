from migration import mappers
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.tax'
ZOHO_TYPE = 'tax'

FIELDS = ['id', 'name', 'amount', 'amount_type', 'type_tax_use',
          'children_tax_ids', 'price_include']


def migrate(odoo, zoho, id_map, dry_run, logger):
    """Create non-group taxes first, then group taxes referencing children."""
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    domain = [('active', '=', True)]
    all_taxes = list(paginate(odoo, MODEL, domain, FIELDS))

    leaf_taxes = [t for t in all_taxes if t.get('amount_type') != 'group']
    group_taxes = [t for t in all_taxes if t.get('amount_type') == 'group']

    for rec in leaf_taxes:
        _migrate_one(zoho, id_map, logger, rec, child_ids=None, counts=counts)

    for rec in group_taxes:
        child_zoho_ids = []
        for child_odoo_id in rec.get('children_tax_ids') or []:
            zid = id_map.get_zoho_id(MODEL, child_odoo_id)
            if zid:
                child_zoho_ids.append(zid)
        _migrate_one(zoho, id_map, logger, rec,
                     child_ids=child_zoho_ids, counts=counts)

    return counts


def _migrate_one(zoho, id_map, logger, rec, child_ids, counts):
    odoo_id = rec['id']
    existing = id_map.get_zoho_id(MODEL, odoo_id)
    if existing:
        record_skip(logger, MODEL, odoo_id, existing)
        counts['skipped'] += 1
        return
    body = mappers.map_tax(rec, child_zoho_ids=child_ids)
    try:
        resp = zoho.create_tax(body)
        zoho_id = extract_zoho_id(resp, 'tax')
        if not zoho_id:
            raise ValueError(f'No id in response: {resp}')
        id_map.put(MODEL, odoo_id, ZOHO_TYPE, zoho_id, status='created')
        record_success(logger, id_map, MODEL, odoo_id, ZOHO_TYPE, zoho_id)
        counts['created'] += 1
    except Exception as e:
        record_failure(logger, id_map, MODEL, odoo_id, e, ZOHO_TYPE)
        counts['failed'] += 1
