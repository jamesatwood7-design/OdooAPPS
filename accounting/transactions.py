"""Accounting transaction services - create invoices, bills, payments, journal entries."""

from common.utils import format_many2one


def get_partners(odoo, partner_type=None):
    """Get partners (customers/vendors) for dropdowns."""
    domain = []
    if partner_type == 'customer':
        domain = [('customer_rank', '>', 0)]
    elif partner_type == 'supplier':
        domain = [('supplier_rank', '>', 0)]

    return odoo.search_read(
        'res.partner', domain,
        fields=['id', 'name', 'email'],
        order='name asc',
        limit=500,
    )


def get_products(odoo, sale=True):
    """Get products for invoice/bill lines with their default taxes."""
    fields = ['id', 'name', 'list_price', 'standard_price',
              'taxes_id', 'supplier_taxes_id', 'default_code']
    products = odoo.safe_search_read(
        'product.product', [('sale_ok', '=', True)] if sale else [],
        fields=fields,
        order='name asc',
        limit=500,
    )
    for p in products:
        code = p.get('default_code', '')
        p['display_name'] = f"[{code}] {p['name']}" if code else p['name']
    return products


def get_journals(odoo, journal_type=None):
    """Get accounting journals."""
    domain = []
    if journal_type:
        domain = [('type', '=', journal_type)]
    return odoo.search_read(
        'account.journal', domain,
        fields=['id', 'name', 'type', 'code'],
        order='name asc',
    )


def get_accounts(odoo):
    """Get all accounts for journal entry lines."""
    return odoo.search_read(
        'account.account', [],
        fields=['id', 'code', 'name', 'account_type'],
        order='code asc',
    )


def get_taxes(odoo, tax_type=None):
    """Get available taxes.

    tax_type: 'sale' for customer taxes, 'purchase' for vendor taxes
    Filters to only show taxes of the correct type and removes duplicates.
    """
    domain = [('active', '=', True)]
    if tax_type:
        domain.append(('type_tax_use', '=', tax_type))

    taxes = odoo.search_read(
        'account.tax', domain,
        fields=['id', 'name', 'amount', 'amount_type', 'type_tax_use',
                'price_include', 'description'],
        order='sequence, name asc',
    )

    # Build display name: use description if available, otherwise name
    for t in taxes:
        desc = t.get('description') or ''
        name = t.get('name', '')
        amt_type = t.get('amount_type', 'percent')

        if amt_type == 'group':
            t['display_name'] = name
        elif desc:
            t['display_name'] = f"{name} ({desc})"
        else:
            t['display_name'] = f"{name} ({t.get('amount', 0)}%)"

    return taxes


def get_analytic_accounts(odoo):
    """Get analytic accounts for tagging transactions to jobs."""
    return odoo.search_read(
        'account.analytic.account', [],
        fields=['id', 'name', 'code'],
        order='code asc',
    )


def _build_move_lines(lines, analytic_id=None):
    """Build invoice_line_ids from parsed line data.

    When product_id is set, Odoo auto-fills account, taxes, description.
    """
    invoice_lines = []
    for line in lines:
        line_vals = {
            'quantity': line.get('quantity', 1),
            'price_unit': line.get('price_unit', 0),
        }
        if line.get('product_id'):
            line_vals['product_id'] = line['product_id']
        if line.get('name'):
            line_vals['name'] = line['name']
        if line.get('account_id'):
            line_vals['account_id'] = line['account_id']
        if line.get('tax_ids'):
            line_vals['tax_ids'] = [(6, 0, line['tax_ids'])]
        if analytic_id:
            line_vals['analytic_distribution'] = {str(analytic_id): 100}

        invoice_lines.append((0, 0, line_vals))
    return invoice_lines


def create_invoice(odoo, partner_id, invoice_date, lines, journal_id=None,
                   ref=None, analytic_id=None):
    """Create a customer invoice (account.move with move_type='out_invoice').

    When lines have product_id, Odoo auto-fills account, taxes, and description.
    """
    move_vals = {
        'move_type': 'out_invoice',
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': ref or '',
        'invoice_line_ids': _build_move_lines(lines, analytic_id),
    }
    if journal_id:
        move_vals['journal_id'] = journal_id

    return odoo.create('account.move', move_vals)


def create_bill(odoo, partner_id, invoice_date, lines, journal_id=None,
                ref=None, analytic_id=None):
    """Create a vendor bill (account.move with move_type='in_invoice')."""
    move_vals = {
        'move_type': 'in_invoice',
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': ref or '',
        'invoice_line_ids': _build_move_lines(lines, analytic_id),
    }
    if journal_id:
        move_vals['journal_id'] = journal_id

    return odoo.create('account.move', move_vals)


def create_payment(odoo, partner_id, amount, payment_date, payment_type,
                   journal_id, ref=None):
    """Create a standalone payment record.

    payment_type: 'inbound' (customer payment) or 'outbound' (vendor payment)
    """
    vals = {
        'partner_id': partner_id,
        'amount': amount,
        'date': payment_date,
        'payment_type': payment_type,
        'partner_type': 'customer' if payment_type == 'inbound' else 'supplier',
        'journal_id': journal_id,
        'ref': ref or '',
    }

    payment_id = odoo.create('account.payment', vals)

    # Auto-post the payment
    try:
        odoo.execute_kw('account.payment', 'action_post', [[payment_id]])
    except Exception:
        pass

    return payment_id


def register_payment_on_invoice(odoo, move_id, journal_id, amount, payment_date,
                                ref=None):
    """Register a payment against a specific invoice or bill.

    Uses Odoo's account.payment.register wizard which automatically
    reconciles the payment with the invoice.
    """
    # Get the invoice to determine payment type
    move = odoo.search_read(
        'account.move', [('id', '=', move_id)],
        fields=['move_type', 'partner_id', 'amount_residual'],
    )
    if not move:
        raise ValueError('Invoice/bill not found')

    move = move[0]
    move_type = move.get('move_type', '')

    if move_type in ('out_invoice', 'out_refund'):
        payment_type = 'inbound'
        partner_type = 'customer'
    else:
        payment_type = 'outbound'
        partner_type = 'supplier'

    partner_val = move.get('partner_id')
    partner_id = partner_val[0] if isinstance(partner_val, (list, tuple)) else partner_val

    # Create payment linked to the invoice context
    # Use the payment register wizard
    try:
        ctx = {'active_model': 'account.move', 'active_ids': [move_id]}
        wizard_id = odoo.execute_kw(
            'account.payment.register', 'create',
            [{'journal_id': journal_id, 'amount': amount, 'payment_date': payment_date,
              'communication': ref or ''}],
            {'context': ctx},
        )
        odoo.execute_kw(
            'account.payment.register', 'action_create_payments',
            [[wizard_id]],
            {'context': ctx},
        )
        return wizard_id
    except Exception:
        # Fallback: create standalone payment
        return create_payment(
            odoo, partner_id, amount, payment_date, payment_type, journal_id, ref
        )


def get_unpaid_invoices(odoo, partner_type=None):
    """Get unpaid/partially paid invoices and bills."""
    domain = [
        ('state', '=', 'posted'),
        ('payment_state', 'in', ('not_paid', 'partial')),
        ('amount_residual', '>', 0),
    ]
    if partner_type == 'customer':
        domain.append(('move_type', 'in', ('out_invoice',)))
    elif partner_type == 'supplier':
        domain.append(('move_type', 'in', ('in_invoice',)))
    else:
        domain.append(('move_type', 'in', ('out_invoice', 'in_invoice')))

    return odoo.safe_search_read(
        'account.move', domain,
        fields=['id', 'name', 'partner_id', 'invoice_date', 'amount_total',
                'amount_residual', 'move_type', 'ref'],
        order='invoice_date desc',
        limit=200,
    )


def create_journal_entry(odoo, journal_id, entry_date, lines, ref=None):
    """Create a manual journal entry.

    lines: [{'account_id': int, 'name': str, 'debit': float, 'credit': float,
             'partner_id': int|None, 'analytic_id': int|None}, ...]
    """
    move_lines = []
    for line in lines:
        line_vals = {
            'account_id': line['account_id'],
            'name': line.get('name', ''),
            'debit': line.get('debit', 0),
            'credit': line.get('credit', 0),
        }
        if line.get('partner_id'):
            line_vals['partner_id'] = line['partner_id']
        if line.get('analytic_id'):
            line_vals['analytic_distribution'] = {str(line['analytic_id']): 100}

        move_lines.append((0, 0, line_vals))

    vals = {
        'move_type': 'entry',
        'journal_id': journal_id,
        'date': entry_date,
        'ref': ref or '',
        'line_ids': move_lines,
    }

    return odoo.create('account.move', vals)


def get_moves(odoo, move_type=None, state=None, payment_state=None,
              partner_id=None, date_from=None, date_to=None, limit=200):
    """Get account.move records with filters."""
    domain = []

    if move_type == 'invoices':
        domain.append(('move_type', 'in', ('out_invoice', 'out_refund')))
    elif move_type == 'bills':
        domain.append(('move_type', 'in', ('in_invoice', 'in_refund')))
    elif move_type:
        domain.append(('move_type', '=', move_type))

    if state:
        domain.append(('state', '=', state))
    if payment_state:
        domain.append(('payment_state', '=', payment_state))
    if partner_id:
        domain.append(('partner_id', '=', partner_id))
    if date_from:
        domain.append(('invoice_date', '>=', date_from))
    if date_to:
        domain.append(('invoice_date', '<=', date_to))

    moves = odoo.safe_search_read(
        'account.move', domain,
        fields=['id', 'name', 'move_type', 'partner_id', 'invoice_date',
                'date', 'amount_total', 'amount_residual', 'state',
                'payment_state', 'ref', 'invoice_origin'],
        order='invoice_date desc, id desc',
        limit=limit,
    )

    for m in moves:
        m['partner_name'] = format_many2one(m.get('partner_id'))
        m['display_date'] = m.get('invoice_date') or m.get('date') or ''

    return moves


def get_move_attachments(odoo, move_id):
    """Get all attachments for a transaction."""
    attachments = odoo.search_read(
        'ir.attachment',
        [('res_model', '=', 'account.move'), ('res_id', '=', move_id)],
        fields=['id', 'name', 'mimetype', 'file_size', 'create_date', 'type',
                'datas'],
        order='create_date desc',
    )

    for a in attachments:
        size = a.get('file_size', 0) or 0
        if size > 1048576:
            a['size_display'] = f'{size / 1048576:.1f} MB'
        elif size > 1024:
            a['size_display'] = f'{size / 1024:.0f} KB'
        else:
            a['size_display'] = f'{size} B'

        a['is_pdf'] = 'pdf' in (a.get('mimetype') or '').lower()
        a['is_image'] = (a.get('mimetype') or '').startswith('image/')

    return attachments


def upload_attachment(odoo, move_id, filename, file_data_base64, mimetype='application/octet-stream'):
    """Upload an attachment to a transaction."""
    return odoo.create('ir.attachment', {
        'name': filename,
        'type': 'binary',
        'datas': file_data_base64,
        'res_model': 'account.move',
        'res_id': move_id,
        'mimetype': mimetype,
    })


def post_move(odoo, move_id):
    """Post (confirm) an account.move."""
    return odoo.execute_kw('account.move', 'action_post', [[move_id]])


def get_move(odoo, move_id):
    """Get a single account.move with its lines."""
    moves = odoo.safe_search_read(
        'account.move',
        [('id', '=', move_id)],
        fields=['id', 'name', 'move_type', 'partner_id', 'date',
                'invoice_date', 'amount_total', 'amount_residual',
                'state', 'payment_state', 'ref'],
    )
    if not moves:
        return None

    move = moves[0]
    move['partner_name'] = format_many2one(move.get('partner_id'))

    # Get lines
    move['lines'] = odoo.safe_search_read(
        'account.move.line',
        [('move_id', '=', move_id)],
        fields=['id', 'name', 'account_id', 'debit', 'credit',
                'balance', 'partner_id', 'date_maturity'],
        order='id asc',
    )

    return move


# ---------------------------------------------------------------------------
# Bank Reconciliation
# ---------------------------------------------------------------------------

def get_bank_journals(odoo):
    """Get bank and cash journals."""
    return odoo.search_read(
        'account.journal',
        [('type', 'in', ('bank', 'cash'))],
        fields=['id', 'name', 'type', 'code'],
        order='name asc',
    )


def get_unreconciled_lines(odoo, journal_id=None, limit=100):
    """Get unreconciled bank/cash journal entry lines."""
    domain = [
        ('parent_state', '=', 'posted'),
        ('reconciled', '=', False),
        ('balance', '!=', 0),
        ('account_id.account_type', 'in', ('asset_cash',)),
    ]
    if journal_id:
        domain.append(('journal_id', '=', journal_id))

    lines = odoo.safe_search_read(
        'account.move.line', domain,
        fields=['id', 'name', 'date', 'ref', 'debit', 'credit', 'balance',
                'partner_id', 'move_id', 'account_id'],
        order='date desc',
        limit=limit,
    )

    for l in lines:
        l['partner_name'] = format_many2one(l.get('partner_id'))
        l['move_name'] = format_many2one(l.get('move_id'))

    return lines


def get_suggested_matches(odoo, line, limit=5):
    """Find potential matching entries for a bank line.

    Matches by: amount (exact or close), partner, reference text.
    """
    amount = abs(line.get('balance', 0))
    partner_id = None
    partner_val = line.get('partner_id')
    if isinstance(partner_val, (list, tuple)):
        partner_id = partner_val[0]

    suggestions = []

    # Strategy 1: exact amount match on unreconciled invoices/bills
    domain = [
        ('parent_state', '=', 'posted'),
        ('reconciled', '=', False),
        ('account_id.account_type', 'in', ('asset_receivable', 'liability_payable')),
        ('balance', '!=', 0),
    ]

    # If we have a partner, filter by partner
    if partner_id:
        domain.append(('partner_id', '=', partner_id))

    candidates = odoo.safe_search_read(
        'account.move.line', domain,
        fields=['id', 'name', 'date', 'ref', 'debit', 'credit', 'balance',
                'partner_id', 'move_id', 'date_maturity'],
        order='date desc',
        limit=50,
    )

    for c in candidates:
        c_amount = abs(c.get('balance', 0))
        c['partner_name'] = format_many2one(c.get('partner_id'))
        c['move_name'] = format_many2one(c.get('move_id'))

        # Score the match
        score = 0
        if abs(c_amount - amount) < 0.01:
            score += 100  # Exact amount match
        elif abs(c_amount - amount) < amount * 0.05:
            score += 50  # Within 5%

        if partner_id and c.get('partner_id'):
            c_pid = c['partner_id'][0] if isinstance(c['partner_id'], (list, tuple)) else c['partner_id']
            if c_pid == partner_id:
                score += 30  # Partner match

        # Check ref/name overlap
        ref = (line.get('ref') or line.get('name') or '').lower()
        c_ref = (c.get('ref') or c.get('name') or '').lower()
        if ref and c_ref and (ref in c_ref or c_ref in ref):
            score += 20  # Reference match

        if score > 0:
            c['match_score'] = score
            suggestions.append(c)

    suggestions.sort(key=lambda x: x['match_score'], reverse=True)
    return suggestions[:limit]


def reconcile_lines(odoo, line_ids):
    """Reconcile a set of account.move.line IDs together."""
    return odoo.execute_kw(
        'account.move.line', 'reconcile', [line_ids]
    )
