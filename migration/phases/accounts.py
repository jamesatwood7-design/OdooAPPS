from migration import mappers
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.account'
ZOHO_TYPE = 'chart_of_account'

FIELDS = ['id', 'name', 'code', 'account_type', 'currency_id']


def migrate(odoo, zoho, id_map, dry_run, logger):
    domain = [('deprecated', '=', False)]
    created = skipped = failed = 0
    for rec in paginate(odoo, MODEL, domain, FIELDS):
        odoo_id = rec['id']
        existing = id_map.get_zoho_id(MODEL, odoo_id)
        if existing:
            record_skip(logger, MODEL, odoo_id, existing)
            skipped += 1
            continue
        body = mappers.map_account(rec)
        try:
            resp = zoho.create_account(body)
            zoho_id = extract_zoho_id(resp, 'chart_of_account')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, ZOHO_TYPE, zoho_id)
            created += 1
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e, ZOHO_TYPE)
            failed += 1
    return {'created': created, 'skipped': skipped, 'failed': failed}
