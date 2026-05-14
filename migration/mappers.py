"""Pure functions converting Odoo records to Zoho Books request bodies.

These functions take plain dicts (as returned by OdooClient.safe_search_read)
and return dicts ready to be POSTed to Zoho. They never make network calls.

Reads from the IdMap to resolve foreign-key references and raise KeyError if
a required mapping is missing (caller is responsible for migrating
dependencies first).
"""

# Odoo account types -> Zoho Books account_type values.
# Zoho's allowed values per /chartofaccounts docs.
ODOO_TO_ZOHO_ACCOUNT_TYPE = {
    # Assets
    'asset_receivable': 'accounts_receivable',
    'asset_cash': 'cash',
    'asset_current': 'other_current_asset',
    'asset_non_current': 'other_asset',
    'asset_prepayments': 'other_current_asset',
    'asset_fixed': 'fixed_asset',
    # Liabilities
    'liability_payable': 'accounts_payable',
    'liability_credit_card': 'credit_card',
    'liability_current': 'other_current_liability',
    'liability_non_current': 'long_term_liability',
    # Equity
    'equity': 'equity',
    'equity_unaffected': 'equity',
    # Income
    'income': 'income',
    'income_other': 'other_income',
    # Expense
    'expense': 'expense',
    'expense_depreciation': 'expense',
    'expense_direct_cost': 'cost_of_goods_sold',
    # Off-balance
    'off_balance': 'other_asset',
}


def _odoo_m2o_id(value):
    """Odoo many2one field is [id, display_name] or False."""
    if value and isinstance(value, (list, tuple)):
        return value[0]
    return None


def _odoo_m2o_name(value):
    if value and isinstance(value, (list, tuple)) and len(value) > 1:
        return value[1]
    return None


def resolve_partner_zoho_id(id_map, partner_id, variant, odoo=None):
    """Look up the Zoho contact id for an Odoo partner.

    Resolution order:
    1. Exact match on (partner_id, variant).
    2. If `odoo` is provided and the partner has a parent, the parent's
       Zoho contact id under the same variant.
    3. The opposite variant for the same partner (vendor↔customer). Same
       legal entity often appears on both sides (e.g. a vendor refund
       lands as inbound).

    Raises KeyError if all three resolutions fail.
    """
    if not partner_id:
        raise KeyError(f'No Zoho {variant} for partner {partner_id}')
    zid = id_map.get_zoho_id('res.partner', partner_id, variant)
    if zid:
        return zid
    if odoo is not None:
        try:
            rec = odoo.read('res.partner', [partner_id], ['parent_id'])
        except Exception:
            rec = None
        if rec:
            parent_ref = rec[0].get('parent_id')
            parent_id = _odoo_m2o_id(parent_ref)
            if parent_id:
                zid = id_map.get_zoho_id('res.partner', parent_id, variant)
                if zid:
                    return zid
    other = 'vendor' if variant == 'customer' else 'customer'
    zid = id_map.get_zoho_id('res.partner', partner_id, other)
    if zid:
        return zid
    raise KeyError(
        f'No Zoho {variant} for partner {partner_id} '
        f'(no parent or opposite-variant fallback either)'
    )


def map_account(rec):
    """account.account -> Zoho /chartofaccounts body."""
    odoo_type = rec.get('account_type') or ''
    return {
        'account_name': rec.get('name') or f'Account {rec["id"]}',
        'account_code': rec.get('code') or '',
        'account_type': ODOO_TO_ZOHO_ACCOUNT_TYPE.get(odoo_type, 'other_current_asset'),
        'description': f"Imported from Odoo account.account #{rec['id']}",
    }


def map_tax(rec, child_zoho_ids=None):
    """account.tax -> Zoho /settings/taxes body.

    For compound (group) taxes, child_zoho_ids is the list of already-created
    Zoho tax IDs.
    """
    body = {
        'tax_name': rec.get('name') or f"Tax {rec['id']}",
        'tax_percentage': float(rec.get('amount') or 0.0),
        'tax_type': 'tax',
    }
    if rec.get('amount_type') == 'group' and child_zoho_ids:
        body['tax_specific_type'] = 'compound_tax'
    return body


def _address_from_partner(rec):
    state = _odoo_m2o_name(rec.get('state_id')) or ''
    country = _odoo_m2o_name(rec.get('country_id')) or ''
    return {
        'address': rec.get('street') or '',
        'street2': rec.get('street2') or '',
        'city': rec.get('city') or '',
        'state': state,
        'zip': rec.get('zip') or '',
        'country': country,
    }


def map_contact(rec, contact_type):
    """res.partner -> Zoho /contacts body. contact_type: 'customer' or 'vendor'."""
    if contact_type not in ('customer', 'vendor'):
        raise ValueError(f'contact_type must be customer|vendor, got {contact_type}')
    address = _address_from_partner(rec)
    name = rec.get('name') or f'Partner {rec["id"]}'
    body = {
        'contact_name': name,
        'company_name': rec.get('company_name') or (name if rec.get('is_company') else ''),
        'contact_type': contact_type,
        'billing_address': address,
        'shipping_address': address,
    }
    if rec.get('email'):
        body['email'] = rec['email']
    if rec.get('phone'):
        body['phone'] = rec['phone']
    if rec.get('mobile'):
        body['mobile'] = rec['mobile']
    if rec.get('website'):
        body['website'] = rec['website']
    if rec.get('vat'):
        body['tax_reg_no'] = rec['vat']
    currency = _odoo_m2o_name(rec.get('currency_id'))
    if currency:
        body['currency_code'] = currency
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_project(rec, customer_zoho_id=None):
    """project.project -> Zoho /projects body."""
    body = {
        'project_name': rec.get('name') or f'Project {rec["id"]}',
        'description': f"Imported from Odoo project.project #{rec['id']}",
        'billing_type': 'based_on_project_hours',
    }
    if customer_zoho_id:
        body['customer_id'] = customer_zoho_id
    if rec.get('date_start'):
        body['start_date'] = rec['date_start']
    if rec.get('date'):
        body['end_date'] = rec['date']
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_analytic_account_as_project(rec, customer_zoho_id=None):
    """account.analytic.account with no linked project.project -> Zoho project.

    Used as a fallback when an analytic account exists standalone (cost
    center) and we need a Zoho project to attach time entries to.
    """
    body = {
        'project_name': rec.get('name') or f'Cost Center {rec["id"]}',
        'description': f"Imported from Odoo account.analytic.account #{rec['id']}",
        'billing_type': 'based_on_project_hours',
    }
    if customer_zoho_id:
        body['customer_id'] = customer_zoho_id
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def _line_items_for_doc(line_recs, id_map):
    """Translate account.move.line -> Zoho line_items. Skips section/note lines."""
    items = []
    for line in line_recs:
        if line.get('display_type') in ('line_section', 'line_note'):
            continue
        account_id = _odoo_m2o_id(line.get('account_id'))
        zoho_account_id = (
            id_map.get_zoho_id('account.account', account_id) if account_id else None
        )
        item = {
            'name': (line.get('name') or '')[:100] or 'Item',
            'description': line.get('name') or '',
            'rate': float(line.get('price_unit') or 0.0),
            'quantity': float(line.get('quantity') or 1.0),
        }
        if zoho_account_id:
            item['account_id'] = zoho_account_id
        tax_ids = line.get('tax_ids') or []
        zoho_tax_ids = [
            id_map.get_zoho_id('account.tax', t) for t in tax_ids
        ]
        zoho_tax_ids = [t for t in zoho_tax_ids if t]
        if zoho_tax_ids:
            item['tax_id'] = zoho_tax_ids[0]
        analytic = line.get('analytic_distribution') or {}
        if analytic:
            try:
                first_key = next(iter(analytic))
                analytic_id = int(first_key)
                project_zoho = id_map.get_zoho_id(
                    'account.analytic.account', analytic_id
                )
                if project_zoho:
                    item['project_id'] = project_zoho
            except (StopIteration, ValueError, TypeError):
                pass
        items.append(item)
    return items


def map_invoice(rec, lines, id_map, odoo=None):
    """account.move (out_invoice or out_refund) -> /invoices or /creditnotes body."""
    customer_id = _odoo_m2o_id(rec.get('partner_id'))
    customer_zoho = resolve_partner_zoho_id(
        id_map, customer_id, 'customer', odoo=odoo
    )
    body = {
        'customer_id': customer_zoho,
        'invoice_number': rec.get('name') or f"INV/{rec['id']}",
        'reference_number': f"odoo:{rec['id']}",
        'date': rec.get('invoice_date') or rec.get('date'),
        'line_items': _line_items_for_doc(lines, id_map),
    }
    if rec.get('invoice_date_due'):
        body['due_date'] = rec['invoice_date_due']
    currency = _odoo_m2o_name(rec.get('currency_id'))
    if currency:
        body['currency_code'] = currency
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_bill(rec, lines, id_map, odoo=None):
    """account.move (in_invoice or in_refund) -> /bills or /vendorcredits body."""
    vendor_id = _odoo_m2o_id(rec.get('partner_id'))
    vendor_zoho = resolve_partner_zoho_id(
        id_map, vendor_id, 'vendor', odoo=odoo
    )
    body = {
        'vendor_id': vendor_zoho,
        'bill_number': rec.get('ref') or rec.get('name') or f"BILL/{rec['id']}",
        'reference_number': f"odoo:{rec['id']}",
        'date': rec.get('invoice_date') or rec.get('date'),
        'line_items': _line_items_for_doc(lines, id_map),
    }
    if rec.get('invoice_date_due'):
        body['due_date'] = rec['invoice_date_due']
    currency = _odoo_m2o_name(rec.get('currency_id'))
    if currency:
        body['currency_code'] = currency
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_journal(rec, lines, id_map):
    """account.move (entry) -> /journals body."""
    journal_lines = []
    for line in lines:
        account_id = _odoo_m2o_id(line.get('account_id'))
        zoho_account_id = (
            id_map.get_zoho_id('account.account', account_id) if account_id else None
        )
        debit = float(line.get('debit') or 0.0)
        credit = float(line.get('credit') or 0.0)
        if debit == 0.0 and credit == 0.0:
            continue
        item = {
            'description': line.get('name') or '',
            'amount': debit if debit > 0 else credit,
            'debit_or_credit': 'debit' if debit > 0 else 'credit',
        }
        if zoho_account_id:
            item['account_id'] = zoho_account_id
        journal_lines.append(item)
    return {
        'journal_date': rec.get('date'),
        'reference_number': rec.get('name') or f"JE/{rec['id']}",
        'notes': f"Imported from Odoo account.move #{rec['id']}",
        'line_items': journal_lines,
    }


def map_customer_payment(rec, id_map, invoice_zoho_ids, odoo=None):
    """account.payment (inbound) -> /customerpayments body."""
    customer_id = _odoo_m2o_id(rec.get('partner_id'))
    customer_zoho = resolve_partner_zoho_id(
        id_map, customer_id, 'customer', odoo=odoo
    )
    body = {
        'customer_id': customer_zoho,
        'payment_mode': 'banktransfer',
        'amount': float(rec.get('amount') or 0.0),
        'date': rec.get('date'),
        'reference_number': rec.get('name') or f"PMT/{rec['id']}",
    }
    if invoice_zoho_ids:
        body['invoices'] = [
            {'invoice_id': zid, 'amount_applied': 0}
            for zid in invoice_zoho_ids
        ]
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_vendor_payment(rec, id_map, bill_zoho_ids, odoo=None):
    """account.payment (outbound) -> /vendorpayments body."""
    vendor_id = _odoo_m2o_id(rec.get('partner_id'))
    vendor_zoho = resolve_partner_zoho_id(
        id_map, vendor_id, 'vendor', odoo=odoo
    )
    body = {
        'vendor_id': vendor_zoho,
        'payment_mode': 'banktransfer',
        'amount': float(rec.get('amount') or 0.0),
        'date': rec.get('date'),
        'reference_number': rec.get('name') or f"VPMT/{rec['id']}",
    }
    if bill_zoho_ids:
        body['bills'] = [
            {'bill_id': zid, 'amount_applied': 0}
            for zid in bill_zoho_ids
        ]
    body['custom_fields'] = [{'label': 'odoo_id', 'value': str(rec['id'])}]
    return body


def map_time_entry(rec, project_zoho_id, user_zoho_id):
    """account.analytic.line (timesheet) -> /projects/timeentries body."""
    return {
        'project_id': project_zoho_id,
        'user_id': user_zoho_id,
        'log_date': rec.get('date'),
        'log_time': float(rec.get('unit_amount') or 0.0),
        'notes': rec.get('name') or '',
    }
