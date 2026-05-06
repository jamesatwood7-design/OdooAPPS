"""Migrate account.analytic.line as Zoho time entries.

Only timesheet lines (employee + project) are migrated; expense-only lines
without a project are logged as skipped.
"""
from migration import mappers
from migration.mappers import _odoo_m2o_id
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.analytic.line'
ZOHO_TYPE = 'timeentry'

FIELDS = ['id', 'name', 'date', 'unit_amount', 'amount',
          'account_id', 'project_id', 'task_id', 'employee_id', 'user_id']


def _resolve_project(rec, id_map):
    """Find a Zoho project for this analytic line.

    Try in order: Odoo project_id -> linked analytic_account_id -> analytic
    account directly.
    """
    pid = _odoo_m2o_id(rec.get('project_id'))
    if pid:
        zid = id_map.get_zoho_id('project.project', pid)
        if zid:
            return zid
    aid = _odoo_m2o_id(rec.get('account_id'))
    if aid:
        zid = id_map.get_zoho_id('account.analytic.account', aid)
        if zid:
            return zid
    return None


def migrate(odoo, zoho, id_map, dry_run, logger, zoho_user_id=None):
    """zoho_user_id: fallback Zoho user to attribute time to. Required because
    mapping Odoo employees->Zoho users 1:1 is out of scope (orgs typically have
    a small Zoho user pool); pass the org's admin or a generic 'imported' user.
    """
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    if not zoho_user_id:
        raise ValueError(
            'zoho_user_id is required for analytic_lines phase '
            '(set MIGRATION_ZOHO_USER_ID env var)'
        )
    domain = [('unit_amount', '>', 0)]
    for rec in paginate(odoo, MODEL, domain, FIELDS):
        odoo_id = rec['id']
        existing = id_map.get_zoho_id(MODEL, odoo_id)
        if existing:
            record_skip(logger, MODEL, odoo_id, existing)
            counts['skipped'] += 1
            continue
        project_zoho = _resolve_project(rec, id_map)
        if not project_zoho:
            record_failure(logger, id_map, MODEL, odoo_id,
                           'no Zoho project for analytic line', ZOHO_TYPE)
            counts['failed'] += 1
            continue
        body = mappers.map_time_entry(rec, project_zoho, zoho_user_id)
        try:
            resp = zoho.log_time_entry(body)
            zoho_id = extract_zoho_id(resp, 'time_entry')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, ZOHO_TYPE, zoho_id)
            counts['created'] += 1
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e, ZOHO_TYPE)
            counts['failed'] += 1
    return counts
