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


def get_products(odoo):
    """Get products for invoice/bill lines."""
    return odoo.search_read(
        'product.product', [],
        fields=['id', 'name', 'list_price', 'standard_price'],
        order='name asc',
        limit=500,
    )


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


def get_analytic_accounts(odoo):
    """Get analytic accounts for tagging transactions to jobs."""
    return odoo.search_read(
        'account.analytic.account', [],
        fields=['id', 'name', 'code'],
        order='code asc',
    )


def create_invoice(odoo, partner_id, invoice_date, lines, journal_id=None,
                   ref=None, analytic_id=None):
    """Create a customer invoice (account.move with move_type='out_invoice').

    lines: [{'name': str, 'quantity': float, 'price_unit': float, 'account_id': int}, ...]
    """
    move_vals = {
        'move_type': 'out_invoice',
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': ref or '',
    }
    if journal_id:
        move_vals['journal_id'] = journal_id

    # Create invoice lines
    invoice_lines = []
    for line in lines:
        line_vals = {
            'name': line.get('name', ''),
            'quantity': line.get('quantity', 1),
            'price_unit': line.get('price_unit', 0),
        }
        if line.get('account_id'):
            line_vals['account_id'] = line['account_id']
        if analytic_id:
            line_vals['analytic_distribution'] = {str(analytic_id): 100}

        invoice_lines.append((0, 0, line_vals))

    move_vals['invoice_line_ids'] = invoice_lines

    return odoo.create('account.move', move_vals)


def create_bill(odoo, partner_id, invoice_date, lines, journal_id=None,
                ref=None, analytic_id=None):
    """Create a vendor bill (account.move with move_type='in_invoice')."""
    move_vals = {
        'move_type': 'in_invoice',
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': ref or '',
    }
    if journal_id:
        move_vals['journal_id'] = journal_id

    invoice_lines = []
    for line in lines:
        line_vals = {
            'name': line.get('name', ''),
            'quantity': line.get('quantity', 1),
            'price_unit': line.get('price_unit', 0),
        }
        if line.get('account_id'):
            line_vals['account_id'] = line['account_id']
        if analytic_id:
            line_vals['analytic_distribution'] = {str(analytic_id): 100}

        invoice_lines.append((0, 0, line_vals))

    move_vals['invoice_line_ids'] = invoice_lines

    return odoo.create('account.move', move_vals)


def create_payment(odoo, partner_id, amount, payment_date, payment_type,
                   journal_id, ref=None):
    """Create a payment record.

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

    return odoo.create('account.payment', vals)


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
