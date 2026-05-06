from migration import mappers
from migration.mappers import _odoo_m2o_id
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.analytic.account'
ZOHO_TYPE = 'project'

FIELDS = ['id', 'name', 'partner_id', 'active']


def migrate(odoo, zoho, id_map, dry_run, logger):
    """Migrate analytic accounts that aren't already linked to a project.project.

    project.project phase will already have populated id_map entries for any
    analytic account that's a project's analytic_account_id. Anything left is
    a standalone cost center that we create as its own Zoho project so time
    entries can attach to it.
    """
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    for rec in paginate(odoo, MODEL, [('active', '=', True)], FIELDS):
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
        body = mappers.map_analytic_account_as_project(
            rec, customer_zoho_id=customer_zoho
        )
        try:
            resp = zoho.create_project(body)
            zoho_id = extract_zoho_id(resp, 'project')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, ZOHO_TYPE, zoho_id)
            counts['created'] += 1
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e, ZOHO_TYPE)
            counts['failed'] += 1
    return counts
