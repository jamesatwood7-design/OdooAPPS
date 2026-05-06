"""Migrate account.move records.

move_type values:
    out_invoice  -> Zoho /invoices
    out_refund   -> Zoho /creditnotes
    in_invoice   -> Zoho /bills
    in_refund    -> Zoho /vendorcredits
    entry        -> Zoho /journals (manual journal)
"""
from migration import mappers
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.move'
LINE_MODEL = 'account.move.line'

MOVE_FIELDS = ['id', 'name', 'move_type', 'state', 'partner_id', 'date',
               'invoice_date', 'invoice_date_due', 'currency_id',
               'amount_total', 'ref', 'line_ids']

LINE_FIELDS = ['id', 'name', 'move_id', 'account_id', 'partner_id',
               'price_unit', 'quantity', 'tax_ids', 'debit', 'credit',
               'analytic_distribution', 'display_type']


def _read_lines(odoo, line_ids):
    if not line_ids:
        return []
    return odoo.safe_search_read(
        LINE_MODEL, [('id', 'in', line_ids)], fields=LINE_FIELDS,
    )


def migrate(odoo, zoho, id_map, dry_run, logger, move_types=None):
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    if move_types is None:
        move_types = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund',
                      'entry')
    domain = [('move_type', 'in', list(move_types)),
              ('state', '=', 'posted')]
    for rec in paginate(odoo, MODEL, domain, MOVE_FIELDS, page_size=100):
        odoo_id = rec['id']
        move_type = rec.get('move_type')
        existing = id_map.get_zoho_id(MODEL, odoo_id, variant=move_type)
        if existing:
            record_skip(logger, MODEL, odoo_id, existing, variant=move_type)
            counts['skipped'] += 1
            continue
        try:
            lines = _read_lines(odoo, rec.get('line_ids') or [])
            if move_type == 'out_invoice':
                body = mappers.map_invoice(rec, lines, id_map)
                resp = zoho.create_invoice(body)
                zoho_type, zoho_id = 'invoice', extract_zoho_id(resp, 'invoice')
            elif move_type == 'out_refund':
                body = mappers.map_invoice(rec, lines, id_map)
                resp = zoho.create_credit_note(body)
                zoho_type, zoho_id = 'creditnote', extract_zoho_id(resp, 'creditnote')
            elif move_type == 'in_invoice':
                body = mappers.map_bill(rec, lines, id_map)
                resp = zoho.create_bill(body)
                zoho_type, zoho_id = 'bill', extract_zoho_id(resp, 'bill')
            elif move_type == 'in_refund':
                body = mappers.map_bill(rec, lines, id_map)
                resp = zoho.create_vendor_credit(body)
                zoho_type, zoho_id = 'vendorcredit', extract_zoho_id(resp, 'vendor_credit')
            elif move_type == 'entry':
                body = mappers.map_journal(rec, lines, id_map)
                resp = zoho.create_journal(body)
                zoho_type, zoho_id = 'journal', extract_zoho_id(resp, 'journal')
            else:
                raise ValueError(f'Unsupported move_type {move_type}')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, zoho_type, zoho_id,
                           variant=move_type)
            counts['created'] += 1
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e,
                           zoho_type='', variant=move_type or '')
            counts['failed'] += 1
    return counts
