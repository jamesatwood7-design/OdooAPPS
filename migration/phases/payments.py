from migration import mappers
from migration.phases._common import (
    paginate, extract_zoho_id, record_success, record_skip, record_failure,
)


MODEL = 'account.payment'

FIELDS = ['id', 'name', 'partner_id', 'partner_type', 'payment_type',
          'amount', 'date', 'currency_id', 'state',
          'reconciled_invoice_ids', 'reconciled_bill_ids']


def migrate(odoo, zoho, id_map, dry_run, logger):
    counts = {'created': 0, 'skipped': 0, 'failed': 0}
    domain = [('state', 'in', ['posted', 'paid', 'in_process', 'reconciled'])]
    for rec in paginate(odoo, MODEL, domain, FIELDS):
        odoo_id = rec['id']
        ptype = rec.get('payment_type')
        variant = ptype or ''
        existing = id_map.get_zoho_id(MODEL, odoo_id, variant=variant)
        if existing:
            record_skip(logger, MODEL, odoo_id, existing, variant=variant)
            counts['skipped'] += 1
            continue
        try:
            if ptype == 'inbound':
                invoice_zoho_ids = []
                for inv_id in rec.get('reconciled_invoice_ids') or []:
                    zid = id_map.get_zoho_id(
                        'account.move', inv_id, variant='out_invoice'
                    )
                    if zid:
                        invoice_zoho_ids.append(zid)
                body = mappers.map_customer_payment(rec, id_map, invoice_zoho_ids)
                resp = zoho.create_customer_payment(body)
                zoho_type = 'customerpayment'
                zoho_id = extract_zoho_id(resp, 'payment')
            elif ptype == 'outbound':
                bill_zoho_ids = []
                for bill_id in rec.get('reconciled_bill_ids') or []:
                    zid = id_map.get_zoho_id(
                        'account.move', bill_id, variant='in_invoice'
                    )
                    if zid:
                        bill_zoho_ids.append(zid)
                body = mappers.map_vendor_payment(rec, id_map, bill_zoho_ids)
                resp = zoho.create_vendor_payment(body)
                zoho_type = 'vendorpayment'
                zoho_id = extract_zoho_id(resp, 'vendor_payment')
            else:
                raise ValueError(f'Unsupported payment_type {ptype}')
            if not zoho_id:
                raise ValueError(f'No id in response: {resp}')
            record_success(logger, id_map, MODEL, odoo_id, zoho_type, zoho_id,
                           variant=variant)
            counts['created'] += 1
        except Exception as e:
            record_failure(logger, id_map, MODEL, odoo_id, e,
                           zoho_type='', variant=variant)
            counts['failed'] += 1
    return counts
