import logging

from migration import mappers
from migration.mappers import _odoo_m2o_id
from migration.logging_setup import log_record
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

MOVE_VARIANT = {
    'out_invoice': 'customer', 'out_refund': 'customer',
    'in_invoice': 'vendor',   'in_refund': 'vendor',
}
PAYMENT_VARIANT = {'inbound': 'customer', 'outbound': 'vendor'}


def migrate(odoo, zoho, id_map, dry_run, logger):
    """Create Zoho contacts for every partner that has a rank set OR appears
    referenced on an account.move / account.payment we plan to migrate.

    For each candidate, the set of variants (`customer`, `vendor`) created is
    the union of its rank-implied variants and the transaction-implied
    variants. Same Odoo partner can become two Zoho contacts.

    The self-partner (your own company) is hard-skipped — transactions
    referencing it are bookkeeping artifacts (owner draws, legacy imports)
    that we'll skip in the moves/payments phases.

    Archived (active=False) partners are included by explicitly bypassing
    Odoo's implicit active-filter; they migrate as active Zoho contacts.
    """
    counts = {'created': 0, 'skipped': 0, 'failed': 0}

    self_partner_id = _read_self_partner_id(odoo)
    if self_partner_id:
        _mark_self_skipped(id_map, logger, self_partner_id, counts)

    needed = _collect_needed_variants(odoo, exclude_partner_id=self_partner_id)
    if not needed:
        return counts

    # Read every candidate partner in pages, including archived. Explicitly
    # adding ('active', 'in', [True, False]) bypasses Odoo's implicit
    # active_test filter without needing to thread `context=` through the
    # OdooClient.
    candidate_ids = sorted(needed.keys())
    domain = [
        ('id', 'in', candidate_ids),
        ('active', 'in', [True, False]),
    ]
    for rec in paginate(odoo, MODEL, domain, FIELDS):
        roles = needed.get(rec['id'])
        if not roles:
            continue
        for role in sorted(roles):
            _migrate_one(zoho, id_map, logger, rec, role, counts)
    return counts


def _read_self_partner_id(odoo):
    """Return res.company.partner_id (the partner backing your own company)."""
    try:
        companies = odoo.safe_search_read(
            'res.company', [], ['id', 'partner_id'], limit=10,
        )
    except Exception:
        return None
    if not companies:
        return None
    # If there are multiple companies, treat every one of them as self.
    # The caller only uses the primary one; orchestrator can be extended later.
    return _odoo_m2o_id(companies[0].get('partner_id'))


def _mark_self_skipped(id_map, logger, partner_id, counts):
    existing = id_map.get('res.partner', partner_id, variant='self')
    if existing:
        counts['skipped'] += 1
        return
    id_map.put(MODEL, partner_id, ZOHO_TYPE, 'SELF',
               status='skipped', variant='self', error='self_partner')
    log_record(
        logger, logging.INFO,
        f'skip self partner #{partner_id} (transactions against self are '
        f'bookkeeping artifacts; will be skipped in moves/payments)',
        action='skipped', odoo_model=MODEL, odoo_id=partner_id,
        variant='self', error='self_partner',
    )
    counts['skipped'] += 1


def _collect_needed_variants(odoo, exclude_partner_id=None):
    """Return {partner_id: {'customer'|'vendor', ...}} for every partner we
    must have a Zoho contact for.

    Sources unioned:
    1. Any partner with customer_rank > 0 → 'customer'.
    2. Any partner with supplier_rank > 0 → 'vendor'.
    3. Distinct partner_id on each posted account.move, mapped by move_type.
    4. Distinct partner_id on each settled account.payment, mapped by
       payment_type.

    Includes archived partners (active=False) by passing an explicit active
    clause that bypasses Odoo's implicit filter.
    """
    needed = {}

    def _add(pid, variant):
        if not pid or pid == exclude_partner_id:
            return
        needed.setdefault(pid, set()).add(variant)

    rank_rows = odoo.safe_search_read(
        MODEL,
        ['|',
         ('customer_rank', '>', 0),
         ('supplier_rank', '>', 0),
         ('active', 'in', [True, False])],
        fields=['id', 'customer_rank', 'supplier_rank'],
    )
    for p in rank_rows:
        if (p.get('customer_rank') or 0) > 0:
            _add(p['id'], 'customer')
        if (p.get('supplier_rank') or 0) > 0:
            _add(p['id'], 'vendor')

    for move_type, variant in MOVE_VARIANT.items():
        try:
            groups = odoo.read_group(
                'account.move',
                [('move_type', '=', move_type),
                 ('state', '=', 'posted'),
                 ('partner_id', '!=', False)],
                fields=['partner_id'],
                groupby=['partner_id'],
            )
        except Exception:
            groups = []
        for g in groups:
            _add(_odoo_m2o_id(g.get('partner_id')), variant)

    for ptype, variant in PAYMENT_VARIANT.items():
        try:
            groups = odoo.read_group(
                'account.payment',
                [('payment_type', '=', ptype),
                 ('partner_id', '!=', False),
                 ('state', 'in', ['posted', 'paid', 'in_process',
                                  'reconciled'])],
                fields=['partner_id'],
                groupby=['partner_id'],
            )
        except Exception:
            groups = []
        for g in groups:
            _add(_odoo_m2o_id(g.get('partner_id')), variant)

    return needed


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
