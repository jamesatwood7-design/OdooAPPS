from migration import mappers
from migration.mappers import _odoo_m2o_id
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'project.project'
ZOHO_TYPE = 'project'

FIELDS = ['id', 'name', 'partner_id', 'date_start', 'date',
          'analytic_account_id']


def migrate(odoo, zoho, id_map, dry_run, logger):
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    for rec in paginate(odoo, MODEL, [], FIELDS):
        odoo_id = rec['id']
        existing = id_map.get_zoho_id(MODEL, odoo_id)
        if existing:
            record_skip(logger, MODEL, odoo_id, existing)
            counts['skipped'] += 1
            continue
        partner_id = _odoo_m2o_id(rec.get('partner_id'))
        customer_zoho = (
            id_map.get_zoho_id('res.partner', partner_id, 'customer')
            if partner_id else None
        )
        body = mappers.map_project(rec, customer_zoho_id=customer_zoho)
        try:
            resp = zoho.create_project(body)
            zoho_id = extract_zoho_id(resp, 'project')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, ZOHO_TYPE, zoho_id)
            counts['created'] += 1
            # Also map the linked analytic account to the same project.
            analytic_id = _odoo_m2o_id(rec.get('analytic_account_id'))
            if analytic_id:
                id_map.put('account.analytic.account', analytic_id,
                           ZOHO_TYPE, zoho_id, status='created')
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e, ZOHO_TYPE)
            counts['failed'] += 1
    return counts
