"""Per-entity exporters.

Each `export_<entity>(odoo, out_dir, chunk_size, logger, **ctx)` reads from
Odoo and writes one or more XLSX files into `out_dir`. Returns a small dict
of {'rows': N, 'files': [...paths]} suitable for the summary table.

Most exporters look up display names for foreign-key fields via the helpers
in `_names.py`. Zoho's CSV importers resolve customers/vendors/accounts
by name (not id), so the same `_names` helper must be used everywhere a
reference is emitted.
"""
import logging

from migration.mappers import (
    ODOO_TO_ZOHO_ACCOUNT_TYPE,
    _odoo_m2o_id, _odoo_m2o_name,
)
from migration.phases._common import paginate
from migration.export._writer import ChunkedXlsx
from migration.export._names import (
    partner_display_name, account_display_name, project_display_name,
    tax_display_name, invoice_number, bill_number,
)


# Zoho Books Chart-of-Accounts type values are human-readable strings in
# their import format (different from the API enum). This is the canonical
# mapping from our internal Zoho type to the import-friendly string.
ZOHO_API_TYPE_TO_IMPORT_LABEL = {
    'accounts_receivable':    'Accounts Receivable',
    'accounts_payable':       'Accounts Payable',
    'bank':                   'Bank',
    'cash':                   'Cash',
    'other_current_asset':    'Other Current Asset',
    'other_asset':            'Other Asset',
    'fixed_asset':            'Fixed Asset',
    'stock':                  'Stock',
    'credit_card':            'Credit Card',
    'other_current_liability':'Other Current Liability',
    'long_term_liability':    'Long Term Liability',
    'other_liability':        'Other Liability',
    'equity':                 'Equity',
    'income':                 'Income',
    'other_income':           'Other Income',
    'expense':                'Expense',
    'other_expense':          'Other Expense',
    'cost_of_goods_sold':     'Cost of Goods Sold',
}


# --- Chart of Accounts -----------------------------------------------------

ACCOUNT_FIELDS = ['id', 'name', 'code', 'account_type', 'currency_id']

ACCOUNT_COLUMNS = [
    'Account Name', 'Account Code', 'Account Type', 'Description',
    'Currency', 'Reference Number',
]


def export_chart_of_accounts(odoo, out_dir, chunk_size, logger, **_ctx):
    w = ChunkedXlsx(out_dir, 'chart_of_accounts', ACCOUNT_COLUMNS,
                    chunk_size=chunk_size, prefix='01_')
    for rec in paginate(odoo, 'account.account', [], ACCOUNT_FIELDS):
        api_type = ODOO_TO_ZOHO_ACCOUNT_TYPE.get(rec.get('account_type'),
                                                 'other_current_asset')
        w.write_row({
            'Account Name': account_display_name(rec),
            'Account Code': rec.get('code') or '',
            'Account Type': ZOHO_API_TYPE_TO_IMPORT_LABEL.get(
                api_type, 'Other Current Asset'),
            'Description': f"Imported from Odoo account.account #{rec['id']}",
            'Currency': _odoo_m2o_name(rec.get('currency_id')) or '',
            'Reference Number': f"odoo:{rec['id']}",
        })
    w.close()
    logger.info('chart_of_accounts: %d rows -> %d file(s)',
                w.total_rows, len(w.paths))
    return {'rows': w.total_rows, 'files': w.paths}


# --- Taxes -----------------------------------------------------------------
# Zoho Books has no Taxes CSV import — taxes must be set up in the Settings
# UI. This export is a reference sheet so the user can replicate them.

TAX_FIELDS = ['id', 'name', 'amount', 'amount_type', 'type_tax_use',
              'children_tax_ids', 'active']

TAX_COLUMNS = [
    'Tax Name', 'Rate (%)', 'Tax Type', 'Direction', 'Compound Children',
    'Active', 'Reference Number',
]


def export_taxes(odoo, out_dir, chunk_size, logger, **_ctx):
    w = ChunkedXlsx(out_dir, 'taxes_REFERENCE_ONLY', TAX_COLUMNS,
                    chunk_size=chunk_size, prefix='02_')
    children_lookup = {}
    rows = list(paginate(odoo, 'account.tax',
                         [('active', 'in', [True, False])], TAX_FIELDS))
    for rec in rows:
        children_lookup[rec['id']] = rec.get('children_tax_ids') or []
    name_by_id = {r['id']: tax_display_name(r) for r in rows}
    for rec in rows:
        kids = ', '.join(name_by_id.get(c, str(c))
                         for c in (rec.get('children_tax_ids') or []))
        w.write_row({
            'Tax Name': tax_display_name(rec),
            'Rate (%)': rec.get('amount') or 0.0,
            'Tax Type': rec.get('amount_type') or '',
            'Direction': rec.get('type_tax_use') or '',
            'Compound Children': kids,
            'Active': 'Yes' if rec.get('active') else 'No',
            'Reference Number': f"odoo:{rec['id']}",
        })
    w.close()
    logger.info('taxes (reference): %d rows', w.total_rows)
    return {'rows': w.total_rows, 'files': w.paths,
            'note': 'Zoho Books has no tax CSV importer; recreate manually '
                    'using this sheet as a reference.'}


# --- Contacts (split into customers / vendors) -----------------------------

CONTACT_FIELDS = [
    'id', 'name', 'company_name', 'is_company', 'parent_id',
    'email', 'phone', 'mobile', 'website', 'vat',
    'street', 'street2', 'city', 'zip',
    'state_id', 'country_id', 'currency_id',
    'customer_rank', 'supplier_rank', 'active',
]

CONTACT_COLUMNS = [
    'Display Name', 'Company Name', 'Salutation', 'First Name', 'Last Name',
    'Email', 'Phone', 'MobilePhone', 'Website', 'Currency Code',
    'Tax ID', 'Notes',
    'Billing Attention', 'Billing Address', 'Billing Street2',
    'Billing City', 'Billing State', 'Billing Code', 'Billing Country',
    'Shipping Attention', 'Shipping Address', 'Shipping Street2',
    'Shipping City', 'Shipping State', 'Shipping Code', 'Shipping Country',
    'Contact Type', 'Reference Number',
]


def _row_for_contact(rec, contact_type):
    name = (rec.get('name') or '').strip() or f"Partner {rec['id']}"
    is_company = bool(rec.get('is_company'))
    first, last = '', ''
    if not is_company and ' ' in name:
        first, _, last = name.partition(' ')
    elif not is_company:
        first = name
    state = _odoo_m2o_name(rec.get('state_id')) or ''
    country = _odoo_m2o_name(rec.get('country_id')) or ''
    currency = _odoo_m2o_name(rec.get('currency_id')) or ''
    street = (rec.get('street') or '').strip()
    street2 = (rec.get('street2') or '').strip()
    city = (rec.get('city') or '').strip()
    zip_ = (rec.get('zip') or '').strip()
    return {
        'Display Name': partner_display_name(rec),
        'Company Name': rec.get('company_name') or (name if is_company else ''),
        'Salutation': '',
        'First Name': first,
        'Last Name': last,
        'Email': rec.get('email') or '',
        'Phone': rec.get('phone') or '',
        'MobilePhone': rec.get('mobile') or '',
        'Website': rec.get('website') or '',
        'Currency Code': currency,
        'Tax ID': rec.get('vat') or '',
        'Notes': (
            f"Imported from Odoo res.partner #{rec['id']}"
            + ('' if rec.get('active') else ' (archived in Odoo)')
        ),
        'Billing Attention': '' if is_company else name,
        'Billing Address': street, 'Billing Street2': street2,
        'Billing City': city, 'Billing State': state,
        'Billing Code': zip_, 'Billing Country': country,
        'Shipping Attention': '' if is_company else name,
        'Shipping Address': street, 'Shipping Street2': street2,
        'Shipping City': city, 'Shipping State': state,
        'Shipping Code': zip_, 'Shipping Country': country,
        'Contact Type': 'customer' if contact_type == 'customer' else 'vendor',
        'Reference Number': f"odoo:{rec['id']}",
    }


def _collect_partner_variant_map(odoo):
    """Return {partner_id: set('customer','vendor', ...)} from rank +
    transaction references. Mirrors the logic in phases/contacts.py."""
    needed = {}

    def add(pid, variant):
        if not pid:
            return
        needed.setdefault(pid, set()).add(variant)

    rank_rows = odoo.safe_search_read(
        'res.partner',
        ['|', ('customer_rank', '>', 0), ('supplier_rank', '>', 0),
         ('active', 'in', [True, False])],
        fields=['id', 'customer_rank', 'supplier_rank'],
    )
    for p in rank_rows:
        if (p.get('customer_rank') or 0) > 0:
            add(p['id'], 'customer')
        if (p.get('supplier_rank') or 0) > 0:
            add(p['id'], 'vendor')

    for move_type, variant in (
        ('out_invoice', 'customer'), ('out_refund', 'customer'),
        ('in_invoice', 'vendor'),    ('in_refund', 'vendor'),
    ):
        try:
            groups = odoo.read_group(
                'account.move',
                [('move_type', '=', move_type),
                 ('state', '=', 'posted'),
                 ('partner_id', '!=', False)],
                fields=['partner_id'], groupby=['partner_id'],
            )
        except Exception:
            groups = []
        for g in groups:
            add(_odoo_m2o_id(g.get('partner_id')), variant)

    for ptype, variant in (('inbound', 'customer'), ('outbound', 'vendor')):
        try:
            groups = odoo.read_group(
                'account.payment',
                [('payment_type', '=', ptype),
                 ('partner_id', '!=', False),
                 ('state', 'in', ['posted', 'paid', 'in_process',
                                  'reconciled'])],
                fields=['partner_id'], groupby=['partner_id'],
            )
        except Exception:
            groups = []
        for g in groups:
            add(_odoo_m2o_id(g.get('partner_id')), variant)
    return needed


def _read_self_partner_id(odoo):
    try:
        rows = odoo.safe_search_read(
            'res.company', [], ['partner_id'], limit=10,
        )
    except Exception:
        return None
    if not rows:
        return None
    return _odoo_m2o_id(rows[0].get('partner_id'))


def export_contacts(odoo, out_dir, chunk_size, logger, **_ctx):
    self_pid = _read_self_partner_id(odoo)
    needed = _collect_partner_variant_map(odoo)
    if self_pid:
        needed.pop(self_pid, None)
    if not needed:
        return {'customers': 0, 'vendors': 0, 'files': []}

    ids = sorted(needed.keys())
    cust = ChunkedXlsx(out_dir, 'customers', CONTACT_COLUMNS,
                       chunk_size=chunk_size, prefix='03_')
    vend = ChunkedXlsx(out_dir, 'vendors', CONTACT_COLUMNS,
                       chunk_size=chunk_size, prefix='04_')

    domain = [('id', 'in', ids), ('active', 'in', [True, False])]
    for rec in paginate(odoo, 'res.partner', domain, CONTACT_FIELDS):
        roles = needed.get(rec['id'], set())
        if 'customer' in roles:
            cust.write_row(_row_for_contact(rec, 'customer'))
        if 'vendor' in roles:
            vend.write_row(_row_for_contact(rec, 'vendor'))
    cust.close()
    vend.close()
    logger.info('contacts: %d customers, %d vendors',
                cust.total_rows, vend.total_rows)
    return {'customers': cust.total_rows, 'vendors': vend.total_rows,
            'files': cust.paths + vend.paths,
            'self_partner_skipped': self_pid}


# --- Projects --------------------------------------------------------------

PROJECT_FIELDS = ['id', 'name', 'partner_id', 'date_start', 'date',
                  'analytic_account_id']
ANALYTIC_FIELDS = ['id', 'name', 'partner_id', 'active']

PROJECT_COLUMNS = [
    'Project Name', 'Customer Name', 'Description', 'Billing Type',
    'Billing Rate', 'Start Date', 'End Date', 'Status', 'Reference Number',
]


def export_projects(odoo, out_dir, chunk_size, logger, **_ctx):
    w = ChunkedXlsx(out_dir, 'projects', PROJECT_COLUMNS,
                    chunk_size=chunk_size, prefix='05_')
    rows = 0
    # Track analytic accounts already covered as project.analytic_account_id
    # so we don't export them twice in the analytic-accounts pass.
    covered_analytic_ids = set()
    for rec in paginate(odoo, 'project.project', [], PROJECT_FIELDS):
        partner_id = _odoo_m2o_id(rec.get('partner_id'))
        cust_name = ''
        if partner_id:
            # We rely on the Customers file to have a matching Display Name.
            cust_name = f"{_odoo_m2o_name(rec.get('partner_id')) or ''} " \
                        f"[Odoo #{partner_id}]"
        w.write_row({
            'Project Name': project_display_name(rec),
            'Customer Name': cust_name,
            'Description': f"Imported from Odoo project.project #{rec['id']}",
            'Billing Type': 'based_on_project_hours',
            'Billing Rate': '',
            'Start Date': rec.get('date_start') or '',
            'End Date': rec.get('date') or '',
            'Status': 'Active',
            'Reference Number': f"odoo:project:{rec['id']}",
        })
        rows += 1
        aid = _odoo_m2o_id(rec.get('analytic_account_id'))
        if aid:
            covered_analytic_ids.add(aid)

    # Then export analytic accounts that aren't already a project.
    for rec in paginate(odoo, 'account.analytic.account',
                        [('active', 'in', [True, False])], ANALYTIC_FIELDS):
        if rec['id'] in covered_analytic_ids:
            continue
        partner_id = _odoo_m2o_id(rec.get('partner_id'))
        cust_name = ''
        if partner_id:
            cust_name = f"{_odoo_m2o_name(rec.get('partner_id')) or ''} " \
                        f"[Odoo #{partner_id}]"
        w.write_row({
            'Project Name': project_display_name(rec, prefix='Cost Center'),
            'Customer Name': cust_name,
            'Description': (
                f"Imported from Odoo account.analytic.account #{rec['id']}"
            ),
            'Billing Type': 'based_on_project_hours',
            'Billing Rate': '',
            'Start Date': '', 'End Date': '',
            'Status': 'Active' if rec.get('active') else 'Inactive',
            'Reference Number': f"odoo:analytic:{rec['id']}",
        })
        rows += 1
    w.close()
    logger.info('projects: %d rows', rows)
    return {'rows': rows, 'files': w.paths}


# --- Moves -----------------------------------------------------------------

MOVE_FIELDS = ['id', 'name', 'ref', 'move_type', 'state', 'partner_id',
               'date', 'invoice_date', 'invoice_date_due', 'currency_id',
               'amount_total', 'line_ids']
LINE_FIELDS = ['id', 'name', 'move_id', 'account_id', 'partner_id',
               'price_unit', 'quantity', 'tax_ids', 'debit', 'credit',
               'analytic_distribution', 'display_type']


INVOICE_COLUMNS = [
    'Invoice Number', 'Invoice Date', 'Due Date', 'Customer Name',
    'Currency Code', 'Reference Number', 'Status',
    'Item Name', 'Account', 'Item Description', 'Quantity',
    'Item Price', 'Discount', 'Item Tax', 'Project Name',
]
CREDIT_NOTE_COLUMNS = [
    'Credit Note Number', 'Credit Note Date', 'Customer Name',
    'Currency Code', 'Reference Number',
    'Item Name', 'Account', 'Item Description', 'Quantity',
    'Item Price', 'Discount', 'Item Tax', 'Project Name',
]
BILL_COLUMNS = [
    'Bill Number', 'Bill Date', 'Due Date', 'Vendor Name',
    'Currency Code', 'Reference Number',
    'Account', 'Item Description', 'Quantity',
    'Item Price', 'Item Tax', 'Project Name',
]
VENDOR_CREDIT_COLUMNS = BILL_COLUMNS  # same shape
JOURNAL_COLUMNS = [
    'Journal Date', 'Journal Number', 'Notes', 'Reference Number',
    'Account', 'Description', 'Contact Name', 'Debit', 'Credit',
    'Currency Code',
]


def _partner_name_for_zoho(odoo_id, display, partner_kind_index):
    """Format `<display_name> [Odoo #N]` only when we have the Odoo id.
    Fall back to display alone if no id available."""
    if odoo_id is None:
        return display or ''
    return f"{display or ''} [Odoo #{odoo_id}]"


def _read_lines(odoo, line_ids):
    if not line_ids:
        return []
    return odoo.safe_search_read('account.move.line',
                                 [('id', 'in', line_ids)],
                                 fields=LINE_FIELDS)


def _tax_names_for_line(line, tax_index):
    names = []
    for tid in (line.get('tax_ids') or []):
        n = tax_index.get(tid)
        if n:
            names.append(n)
    return ','.join(names)


def _project_name_for_line(line, project_index_by_analytic):
    distrib = line.get('analytic_distribution') or {}
    if not distrib:
        return ''
    try:
        first_key = next(iter(distrib))
        aid = int(first_key)
    except (StopIteration, ValueError, TypeError):
        return ''
    return project_index_by_analytic.get(aid, '')


def _build_tax_name_index(odoo):
    rows = odoo.safe_search_read(
        'account.tax',
        [('active', 'in', [True, False])],
        ['id', 'name'],
    )
    return {r['id']: tax_display_name(r) for r in rows}


def _build_account_name_index(odoo):
    rows = odoo.safe_search_read(
        'account.account', [], ['id', 'name', 'code'],
    )
    return {r['id']: account_display_name(r) for r in rows}


def _build_project_name_index_by_analytic(odoo):
    """analytic_account_id -> project display name (or
    cost-center display name if no project.project is linked)."""
    out = {}
    project_rows = odoo.safe_search_read(
        'project.project', [], ['id', 'name', 'analytic_account_id'],
    )
    for r in project_rows:
        aid = _odoo_m2o_id(r.get('analytic_account_id'))
        if aid:
            out[aid] = project_display_name(r)
    analytic_rows = odoo.safe_search_read(
        'account.analytic.account',
        [('active', 'in', [True, False])],
        ['id', 'name'],
    )
    for r in analytic_rows:
        if r['id'] not in out:
            out[r['id']] = project_display_name(r, prefix='Cost Center')
    return out


def _emit_invoice_lines(rec, lines, w, columns, num_col, date_col, due_col,
                       partner_col, partner_display,
                       account_index, tax_index, project_index,
                       *, kind):
    base = {
        num_col: invoice_number(rec, prefix=('CN' if kind == 'creditnote'
                                             else 'INV')) if kind != 'bill'
                                             else bill_number(rec),
        date_col: rec.get('invoice_date') or rec.get('date') or '',
        partner_col: partner_display,
        'Currency Code': _odoo_m2o_name(rec.get('currency_id')) or '',
        'Reference Number': f"odoo:{rec['id']}",
    }
    if due_col:
        base[due_col] = rec.get('invoice_date_due') or ''
    if 'Status' in columns:
        base['Status'] = 'Sent'
    wrote = False
    for line in lines:
        if line.get('display_type') in ('line_section', 'line_note'):
            continue
        aid = _odoo_m2o_id(line.get('account_id'))
        row = dict(base)
        row['Item Description'] = line.get('name') or ''
        row['Account'] = account_index.get(aid, '') if aid else ''
        row['Quantity'] = float(line.get('quantity') or 1.0)
        row['Item Price'] = float(line.get('price_unit') or 0.0)
        if 'Item Name' in columns:
            row['Item Name'] = (line.get('name') or '')[:100] or 'Item'
        if 'Item Tax' in columns:
            row['Item Tax'] = _tax_names_for_line(line, tax_index)
        if 'Project Name' in columns:
            row['Project Name'] = _project_name_for_line(line, project_index)
        w.write_row(row)
        wrote = True
    if not wrote:
        # Header-only emit so Zoho still creates the doc (line-items required
        # in most cases — but at least the user sees the doc didn't have
        # lines).
        row = dict(base)
        row['Item Description'] = '(no line items in Odoo)'
        row['Quantity'] = 0
        row['Item Price'] = float(rec.get('amount_total') or 0.0)
        w.write_row(row)


def _emit_journal_lines(rec, lines, w, account_index, partner_display):
    base = {
        'Journal Date': rec.get('date') or '',
        'Journal Number': rec.get('name') or f"JE/{rec['id']}",
        'Notes': f"Imported from Odoo account.move #{rec['id']}",
        'Reference Number': f"odoo:{rec['id']}",
        'Contact Name': partner_display or '',
        'Currency Code': _odoo_m2o_name(rec.get('currency_id')) or '',
    }
    wrote = False
    for line in lines:
        debit = float(line.get('debit') or 0.0)
        credit = float(line.get('credit') or 0.0)
        if debit == 0.0 and credit == 0.0:
            continue
        aid = _odoo_m2o_id(line.get('account_id'))
        row = dict(base)
        row['Account'] = account_index.get(aid, '') if aid else ''
        row['Description'] = line.get('name') or ''
        row['Debit'] = debit
        row['Credit'] = credit
        w.write_row(row)
        wrote = True
    return wrote


def export_moves(odoo, out_dir, chunk_size, logger, **_ctx):
    """One writer per move_type. Each line of a multi-line invoice becomes
    its own row; Zoho groups them back together by Invoice Number on import.
    """
    account_index = _build_account_name_index(odoo)
    tax_index = _build_tax_name_index(odoo)
    project_index = _build_project_name_index_by_analytic(odoo)
    self_pid = _read_self_partner_id(odoo)

    inv = ChunkedXlsx(out_dir, 'invoices', INVOICE_COLUMNS,
                      chunk_size=chunk_size, prefix='06_')
    cn  = ChunkedXlsx(out_dir, 'credit_notes', CREDIT_NOTE_COLUMNS,
                      chunk_size=chunk_size, prefix='07_')
    bill = ChunkedXlsx(out_dir, 'bills', BILL_COLUMNS,
                       chunk_size=chunk_size, prefix='08_')
    vc  = ChunkedXlsx(out_dir, 'vendor_credits', VENDOR_CREDIT_COLUMNS,
                      chunk_size=chunk_size, prefix='09_')
    je  = ChunkedXlsx(out_dir, 'manual_journals', JOURNAL_COLUMNS,
                      chunk_size=chunk_size, prefix='10_')
    counts = {'invoice': 0, 'credit_note': 0, 'bill': 0, 'vendor_credit': 0,
              'journal': 0, 'skipped_self': 0}

    domain = [('state', '=', 'posted')]
    for rec in paginate(odoo, 'account.move', domain, MOVE_FIELDS,
                        page_size=100):
        partner_id = _odoo_m2o_id(rec.get('partner_id'))
        if self_pid and partner_id == self_pid and rec.get('move_type') != 'entry':
            counts['skipped_self'] += 1
            continue
        partner_disp = ''
        if partner_id:
            pname = _odoo_m2o_name(rec.get('partner_id')) or ''
            partner_disp = f"{pname} [Odoo #{partner_id}]"
        lines = _read_lines(odoo, rec.get('line_ids') or [])
        mt = rec.get('move_type')
        if mt == 'out_invoice':
            _emit_invoice_lines(
                rec, lines, inv, INVOICE_COLUMNS,
                'Invoice Number', 'Invoice Date', 'Due Date',
                'Customer Name', partner_disp,
                account_index, tax_index, project_index, kind='invoice',
            )
            counts['invoice'] += 1
        elif mt == 'out_refund':
            _emit_invoice_lines(
                rec, lines, cn, CREDIT_NOTE_COLUMNS,
                'Credit Note Number', 'Credit Note Date', None,
                'Customer Name', partner_disp,
                account_index, tax_index, project_index, kind='creditnote',
            )
            counts['credit_note'] += 1
        elif mt == 'in_invoice':
            _emit_invoice_lines(
                rec, lines, bill, BILL_COLUMNS,
                'Bill Number', 'Bill Date', 'Due Date',
                'Vendor Name', partner_disp,
                account_index, tax_index, project_index, kind='bill',
            )
            counts['bill'] += 1
        elif mt == 'in_refund':
            _emit_invoice_lines(
                rec, lines, vc, VENDOR_CREDIT_COLUMNS,
                'Bill Number', 'Bill Date', 'Due Date',
                'Vendor Name', partner_disp,
                account_index, tax_index, project_index, kind='bill',
            )
            counts['vendor_credit'] += 1
        elif mt == 'entry':
            if _emit_journal_lines(rec, lines, je, account_index, partner_disp):
                counts['journal'] += 1

    for w in (inv, cn, bill, vc, je):
        w.close()
    files = inv.paths + cn.paths + bill.paths + vc.paths + je.paths
    logger.info('moves: %s', counts)
    return {'counts': counts, 'files': files}


# --- Payments --------------------------------------------------------------

PAYMENT_FIELDS = ['id', 'name', 'partner_id', 'partner_type', 'payment_type',
                  'amount', 'date', 'currency_id', 'state',
                  'reconciled_invoice_ids', 'reconciled_bill_ids',
                  'payment_method_id', 'ref']

CUSTOMER_PAYMENT_COLUMNS = [
    'Date', 'Customer Name', 'Amount Received', 'Currency Code',
    'Payment Mode', 'Reference Number', 'Invoice Number', 'Amount Applied',
    'Notes',
]
VENDOR_PAYMENT_COLUMNS = [
    'Date', 'Vendor Name', 'Amount', 'Currency Code', 'Payment Mode',
    'Reference Number', 'Bill Number', 'Amount Applied', 'Notes',
]


def _build_move_number_index(odoo):
    """account.move.id -> (name, move_type) so we can populate Invoice
    Number / Bill Number columns on payment rows."""
    rows = odoo.safe_search_read(
        'account.move',
        [('state', '=', 'posted')],
        ['id', 'name', 'ref', 'move_type'],
    )
    out = {}
    for r in rows:
        mt = r.get('move_type')
        if mt in ('in_invoice', 'in_refund'):
            num = bill_number(r)
        else:
            num = invoice_number(r,
                                 prefix='CN' if mt == 'out_refund' else 'INV')
        out[r['id']] = (num, mt)
    return out


def export_payments(odoo, out_dir, chunk_size, logger, **_ctx):
    move_index = _build_move_number_index(odoo)
    self_pid = _read_self_partner_id(odoo)
    cust = ChunkedXlsx(out_dir, 'customer_payments', CUSTOMER_PAYMENT_COLUMNS,
                       chunk_size=chunk_size, prefix='11_')
    vend = ChunkedXlsx(out_dir, 'vendor_payments', VENDOR_PAYMENT_COLUMNS,
                       chunk_size=chunk_size, prefix='12_')
    counts = {'customer': 0, 'vendor': 0, 'skipped_self': 0}
    domain = [('state', 'in', ['posted', 'paid', 'in_process', 'reconciled'])]
    for rec in paginate(odoo, 'account.payment', domain, PAYMENT_FIELDS):
        partner_id = _odoo_m2o_id(rec.get('partner_id'))
        if self_pid and partner_id == self_pid:
            counts['skipped_self'] += 1
            continue
        partner_disp = ''
        if partner_id:
            pname = _odoo_m2o_name(rec.get('partner_id')) or ''
            partner_disp = f"{pname} [Odoo #{partner_id}]"
        ptype = rec.get('payment_type')
        date = rec.get('date') or ''
        amt = float(rec.get('amount') or 0.0)
        ref = rec.get('name') or f"PMT-ODOO-{rec['id']}"
        currency = _odoo_m2o_name(rec.get('currency_id')) or ''
        # If multiple invoices/bills reconciled, emit one row per linkage so
        # Zoho can apply against each.
        if ptype == 'inbound':
            applied = rec.get('reconciled_invoice_ids') or []
            if applied:
                share = amt / len(applied)
                for inv_id in applied:
                    info = move_index.get(inv_id)
                    cust.write_row({
                        'Date': date, 'Customer Name': partner_disp,
                        'Amount Received': amt, 'Currency Code': currency,
                        'Payment Mode': 'banktransfer', 'Reference Number': ref,
                        'Invoice Number': info[0] if info else '',
                        'Amount Applied': share,
                        'Notes': f"Imported from Odoo account.payment #{rec['id']}",
                    })
            else:
                cust.write_row({
                    'Date': date, 'Customer Name': partner_disp,
                    'Amount Received': amt, 'Currency Code': currency,
                    'Payment Mode': 'banktransfer', 'Reference Number': ref,
                    'Invoice Number': '', 'Amount Applied': '',
                    'Notes': f"Imported from Odoo account.payment #{rec['id']}",
                })
            counts['customer'] += 1
        elif ptype == 'outbound':
            applied = rec.get('reconciled_bill_ids') or []
            if applied:
                share = amt / len(applied)
                for bid in applied:
                    info = move_index.get(bid)
                    vend.write_row({
                        'Date': date, 'Vendor Name': partner_disp,
                        'Amount': amt, 'Currency Code': currency,
                        'Payment Mode': 'banktransfer', 'Reference Number': ref,
                        'Bill Number': info[0] if info else '',
                        'Amount Applied': share,
                        'Notes': f"Imported from Odoo account.payment #{rec['id']}",
                    })
            else:
                vend.write_row({
                    'Date': date, 'Vendor Name': partner_disp,
                    'Amount': amt, 'Currency Code': currency,
                    'Payment Mode': 'banktransfer', 'Reference Number': ref,
                    'Bill Number': '', 'Amount Applied': '',
                    'Notes': f"Imported from Odoo account.payment #{rec['id']}",
                })
            counts['vendor'] += 1

    cust.close()
    vend.close()
    logger.info('payments: %s', counts)
    return {'counts': counts, 'files': cust.paths + vend.paths}


# --- Time entries ----------------------------------------------------------

ANALYTIC_LINE_FIELDS = ['id', 'name', 'date', 'unit_amount', 'amount',
                        'account_id', 'project_id', 'task_id', 'employee_id',
                        'user_id']

TIME_ENTRY_COLUMNS = [
    'Project Name', 'Date', 'Hours', 'Description',
    'User Name', 'Reference Number',
]


def export_time_entries(odoo, out_dir, chunk_size, logger, **_ctx):
    project_index = _build_project_name_index_by_analytic(odoo)
    w = ChunkedXlsx(out_dir, 'time_entries', TIME_ENTRY_COLUMNS,
                    chunk_size=chunk_size, prefix='13_')
    skipped_no_project = 0
    for rec in paginate(odoo, 'account.analytic.line',
                        [('unit_amount', '>', 0)], ANALYTIC_LINE_FIELDS):
        # Resolve project: prefer project_id, fall back to analytic account
        proj_name = ''
        pid = _odoo_m2o_id(rec.get('project_id'))
        if pid:
            # project.project rows are indexed via their analytic_account_id;
            # but we need to also look them up by direct id. Cheap: do an
            # in-place display-name resolution.
            proj_name = _odoo_m2o_name(rec.get('project_id')) or ''
            if proj_name:
                proj_name = f"{proj_name} [Odoo #{pid}]"
        if not proj_name:
            aid = _odoo_m2o_id(rec.get('account_id'))
            if aid:
                proj_name = project_index.get(aid, '')
        if not proj_name:
            skipped_no_project += 1
            continue
        user_name = _odoo_m2o_name(rec.get('user_id')) or ''
        emp_name = _odoo_m2o_name(rec.get('employee_id')) or ''
        # Keep the Odoo employee in the description so per-employee reporting
        # in Zoho is still possible via the Notes/description text.
        notes = rec.get('name') or ''
        if emp_name:
            notes = f"[{emp_name}] {notes}".strip()
        w.write_row({
            'Project Name': proj_name,
            'Date': rec.get('date') or '',
            'Hours': float(rec.get('unit_amount') or 0.0),
            'Description': notes,
            'User Name': user_name,
            'Reference Number': f"odoo:line:{rec['id']}",
        })
    w.close()
    logger.info('time_entries: %d rows, %d skipped (no project)',
                w.total_rows, skipped_no_project)
    return {'rows': w.total_rows,
            'skipped_no_project': skipped_no_project,
            'files': w.paths}
