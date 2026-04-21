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


def get_payment_terms(odoo):
    """Payment terms (Due on Receipt, Net 15, Net 30, …) for the Terms dropdown."""
    try:
        return odoo.safe_search_read(
            'account.payment.term',
            [('active', '=', True)],
            fields=['id', 'name'],
            order='sequence asc, name asc',
        )
    except Exception:
        return []


def get_salespersons(odoo):
    """Internal users assignable as salesperson on a move."""
    try:
        return odoo.safe_search_read(
            'res.users',
            [('share', '=', False), ('active', '=', True)],
            fields=['id', 'name'],
            order='name asc',
        )
    except Exception:
        return []


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
        if line.get('discount'):
            line_vals['discount'] = line['discount']
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


SUBJECT_HEADER = 'Subject:\n'
TERMS_HEADER = 'Terms & Conditions:\n'


def _compose_narration(subject='', customer_notes='', terms=''):
    """Merge the three free-text fields into the single Odoo narration field.

    Uses explicit section headers so parse_narration() can reverse the
    operation when pre-filling the edit form.
    """
    parts = []
    subject = (subject or '').strip()
    customer_notes = (customer_notes or '').strip()
    terms = (terms or '').strip()
    if subject:
        parts.append(SUBJECT_HEADER + subject)
    if customer_notes:
        parts.append(customer_notes)
    if terms:
        parts.append(TERMS_HEADER + terms)
    return '\n\n'.join(parts)


def parse_narration(narration):
    """Split a narration string produced by _compose_narration() back into
    (subject, customer_notes, terms). Unknown chunks all collapse into
    customer_notes so we don't lose anything the operator typed.
    """
    subject = ''
    customer_notes_parts = []
    terms = ''
    if not narration:
        return subject, '', terms
    for chunk in [c.strip() for c in narration.split('\n\n') if c.strip()]:
        if chunk.startswith(SUBJECT_HEADER):
            subject = chunk[len(SUBJECT_HEADER):].strip()
        elif chunk.startswith(TERMS_HEADER):
            terms = chunk[len(TERMS_HEADER):].strip()
        else:
            customer_notes_parts.append(chunk)
    return subject, '\n\n'.join(customer_notes_parts), terms


def _create_move(odoo, move_type, partner_id, invoice_date, lines,
                 journal_id=None, ref=None, analytic_id=None,
                 name=None, payment_term_id=None, date_due=None,
                 user_id=None, subject='', customer_notes='', terms=''):
    """Create an account.move draft with the extended field set the Zoho-style
    form collects. Used by create_invoice and create_bill.
    """
    narration = _compose_narration(subject, customer_notes, terms)
    move_vals = {
        'move_type': move_type,
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': ref or '',
        'invoice_line_ids': _build_move_lines(lines, analytic_id),
    }
    if journal_id:
        move_vals['journal_id'] = journal_id
    if name:
        move_vals['name'] = name
    if payment_term_id:
        move_vals['invoice_payment_term_id'] = payment_term_id
    if date_due:
        move_vals['invoice_date_due'] = date_due
    if user_id:
        move_vals['user_id'] = user_id
    if narration:
        move_vals['narration'] = narration

    return odoo.create('account.move', move_vals)


def create_invoice(odoo, partner_id, invoice_date, lines, **kwargs):
    """Create a customer invoice (account.move with move_type='out_invoice').

    Accepts the extended keyword set — name, payment_term_id, date_due,
    user_id, subject, customer_notes, terms — as well as the original
    journal_id / ref / analytic_id.
    """
    return _create_move(odoo, 'out_invoice', partner_id, invoice_date,
                        lines, **kwargs)


def format_progress_summary(contract, previously_billed, previously_paid,
                            this_invoice):
    """Render the Progress Billing Summary that will appear on the PDF.

    Lives in the invoice's narration / Customer Notes, which Odoo prints at
    the bottom of the default invoice template. All figures are computed
    server-side at the moment the invoice is created, so the customer sees
    a consistent snapshot.
    """
    total_billed = (previously_billed or 0) + (this_invoice or 0)
    outstanding = total_billed - (previously_paid or 0)
    remaining = (contract or 0) - total_billed

    def pct(n):
        if not contract:
            return '—'
        return f'{(n / contract * 100):.1f}%'

    def dol(n):
        return f'${n:,.2f}'

    sep = '—' * 38
    lines = [
        'Progress Billing Summary',
        sep,
        f'Contract Total:        {dol(contract)}',
        f'Previously Billed:     {dol(previously_billed)}  ({pct(previously_billed)})',
        f'Previously Paid:       {dol(previously_paid)}  ({pct(previously_paid)})',
        f'This Invoice:          {dol(this_invoice)}  ({pct(this_invoice)})',
        sep,
        f'Total Billed to Date:  {dol(total_billed)}  ({pct(total_billed)})',
        f'Outstanding Balance:   {dol(outstanding)}  ({pct(outstanding)})',
        f'Remaining on Contract: {dol(remaining)}  ({pct(remaining)})',
    ]
    return '\n'.join(lines)


def create_progress_bill(odoo, partner_id, analytic_id, milestone, amount,
                         invoice_date, contract, previously_billed,
                         previously_paid, extra_notes=''):
    """Create a draft customer invoice for one progress-billing milestone.

    Produces a single-line invoice ("Progress Billing — <milestone>") for the
    chosen amount, tagged to the job's analytic account, with the progress
    summary baked into Customer Notes so it prints on the PDF.
    """
    summary = format_progress_summary(
        contract, previously_billed, previously_paid, amount,
    )
    notes_parts = [summary]
    if extra_notes and extra_notes.strip():
        notes_parts.append(extra_notes.strip())
    customer_notes = '\n\n'.join(notes_parts)

    lines = [{
        'quantity': 1.0,
        'price_unit': amount,
        'name': f'Progress Billing — {milestone}',
    }]

    return create_invoice(
        odoo, partner_id, invoice_date, lines,
        analytic_id=analytic_id,
        customer_notes=customer_notes,
    )


def create_bill(odoo, partner_id, invoice_date, lines, **kwargs):
    """Create a vendor bill (account.move with move_type='in_invoice')."""
    return _create_move(odoo, 'in_invoice', partner_id, invoice_date,
                        lines, **kwargs)


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


def _move_type_domain(move_type):
    if move_type == 'invoices':
        return [('move_type', 'in', ('out_invoice', 'out_refund'))]
    if move_type == 'bills':
        return [('move_type', 'in', ('in_invoice', 'in_refund'))]
    if move_type:
        return [('move_type', '=', move_type)]
    return []


def get_moves(odoo, move_type=None, state=None, payment_state=None,
              partner_id=None, date_from=None, date_to=None, limit=200):
    """Backwards-compatible wrapper around the older single-call signature.

    Kept for tests / callers that don't need pagination. New list routes
    use get_moves_list() plus common.list_query.parse_list_query().
    """
    domain = _move_type_domain(move_type)
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


def get_moves_list(odoo, move_type, domain=None, order=None,
                   offset=0, limit=50):
    """Paginated account.move fetch used by the Invoices / Bills list pages.

    Returns (moves, full_domain). The caller reuses full_domain with
    compute_list_totals() so the footer reflects the full filtered set.
    """
    full_domain = _move_type_domain(move_type) + list(domain or [])
    moves = odoo.safe_search_read(
        'account.move', full_domain,
        fields=['id', 'name', 'move_type', 'partner_id', 'invoice_date',
                'date', 'amount_total', 'amount_residual', 'state',
                'payment_state', 'ref', 'invoice_origin'],
        order=order or 'invoice_date desc, id desc',
        offset=offset,
        limit=limit,
    )
    for m in moves:
        m['partner_name'] = format_many2one(m.get('partner_id'))
        m['display_date'] = m.get('invoice_date') or m.get('date') or ''
    return moves, full_domain


def get_move_attachments(odoo, move_id):
    """Return ir.attachment records for a move, annotated with display helpers
    and a ``is_main`` flag that identifies the PDF Odoo will send to the
    customer (account.move.message_main_attachment_id).

    Collects from two places, deduped by id:
      1. Attachments pointing at this move directly
         (res_model='account.move', res_id=<move_id>).
      2. Attachments on chatter messages for this move — these can sit
         under res_model='mail.compose.message' for certain send flows,
         so they'd be invisible otherwise.
    """
    attachment_ids = set()

    try:
        direct_ids = odoo.search(
            'ir.attachment',
            [('res_model', '=', 'account.move'), ('res_id', '=', move_id)],
        )
        attachment_ids.update(direct_ids)
    except Exception:
        pass

    try:
        messages = odoo.search_read(
            'mail.message',
            [('model', '=', 'account.move'), ('res_id', '=', move_id)],
            fields=['attachment_ids'],
        )
        for msg in messages:
            for aid in msg.get('attachment_ids') or []:
                attachment_ids.add(aid)
    except Exception:
        pass

    main_id = None
    try:
        rows = odoo.search_read(
            'account.move', [('id', '=', move_id)],
            fields=['message_main_attachment_id'],
        )
        if rows:
            main = rows[0].get('message_main_attachment_id')
            if isinstance(main, (list, tuple)) and main:
                main_id = main[0]
                attachment_ids.add(main_id)
    except Exception:
        pass

    if not attachment_ids:
        return []

    attachments = odoo.search_read(
        'ir.attachment',
        [('id', 'in', list(attachment_ids))],
        fields=['id', 'name', 'mimetype', 'file_size', 'create_date', 'type'],
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

        mimetype = (a.get('mimetype') or '').lower()
        a['is_pdf'] = 'pdf' in mimetype
        a['is_image'] = mimetype.startswith('image/')
        a['is_previewable'] = a['is_pdf'] or a['is_image']
        a['is_main'] = a['id'] == main_id

    return attachments


def delete_attachment(odoo, attachment_id, move_id):
    """Delete an ir.attachment, verifying it belongs to the given move.

    Returning whether deletion succeeded. We read first to make sure the
    attachment really is scoped to account.move.<move_id> so the route
    can't be abused to delete arbitrary attachments by id.
    """
    records = odoo.search_read(
        'ir.attachment',
        [('id', '=', attachment_id),
         ('res_model', '=', 'account.move'),
         ('res_id', '=', move_id)],
        fields=['id'],
    )
    if not records:
        return False
    odoo.unlink('ir.attachment', [attachment_id])
    return True


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


def reset_move_to_draft(odoo, move_id):
    """Reset a posted move back to draft so it can be edited."""
    return odoo.execute_kw('account.move', 'button_draft', [[move_id]])


def get_move(odoo, move_id):
    """Fetch a single account.move with enriched header + line data.

    Returns a dict with:
      - Header: name, move_type, partner_id/partner_name, date, invoice_date,
        invoice_date_due, invoice_payment_term_id, user_id, ref,
        invoice_origin, amount_total, amount_untaxed, amount_tax,
        amount_residual, state, payment_state, narration.
      - `invoice_lines`: the product/service lines shown on the printed
        invoice (subset of move.line_ids where display_type is not a
        section/header and excluding tax/receivable lines).
      - `journal_lines`: every account.move.line — the accounting view.
    """
    moves = odoo.safe_search_read(
        'account.move',
        [('id', '=', move_id)],
        fields=['id', 'name', 'move_type', 'partner_id', 'date',
                'invoice_date', 'invoice_date_due',
                'invoice_payment_term_id', 'user_id',
                'amount_total', 'amount_untaxed', 'amount_tax',
                'amount_residual', 'state', 'payment_state',
                'ref', 'invoice_origin', 'narration',
                'invoice_line_ids'],
    )
    if not moves:
        return None

    move = moves[0]
    move['partner_name'] = format_many2one(move.get('partner_id'))
    move['payment_term_name'] = format_many2one(move.get('invoice_payment_term_id'))
    move['salesperson_name'] = format_many2one(move.get('user_id'))

    # Invoice-style lines: exclude tax lines, receivable/payable lines, and
    # section/note display lines.
    invoice_lines = []
    line_ids = move.get('invoice_line_ids') or []
    if line_ids:
        invoice_lines = odoo.safe_search_read(
            'account.move.line',
            [('id', 'in', line_ids)],
            fields=['id', 'name', 'product_id', 'quantity', 'price_unit',
                    'discount', 'tax_ids', 'price_subtotal', 'price_total',
                    'account_id', 'analytic_distribution', 'display_type'],
            order='sequence asc, id asc',
        )
        for line in invoice_lines:
            line['product_name'] = format_many2one(line.get('product_id'))
            line['account_name'] = format_many2one(line.get('account_id'))
            line['tax_label'] = ''
            if line.get('tax_ids'):
                try:
                    taxes = odoo.safe_search_read(
                        'account.tax',
                        [('id', 'in', line['tax_ids'])],
                        fields=['name'],
                    )
                    line['tax_label'] = ', '.join(t['name'] for t in taxes)
                except Exception:
                    pass
    move['invoice_lines'] = invoice_lines

    # Full accounting detail for the collapsible Journal Items view.
    move['journal_lines'] = odoo.safe_search_read(
        'account.move.line',
        [('move_id', '=', move_id)],
        fields=['id', 'name', 'account_id', 'debit', 'credit',
                'balance', 'partner_id', 'date_maturity'],
        order='id asc',
    )

    return move


def update_move(odoo, move_id, partner_id, invoice_date, lines, **kwargs):
    """Update an existing draft move. Replaces invoice_line_ids wholesale.

    Same keyword set as create_invoice / create_bill (name, ref, analytic_id,
    payment_term_id, date_due, user_id, subject, customer_notes, terms).
    Odoo's action_post refuses to edit non-draft moves, so callers should
    ensure state=='draft' before calling.
    """
    subject = kwargs.get('subject', '')
    customer_notes = kwargs.get('customer_notes', '')
    terms = kwargs.get('terms', '')
    narration = _compose_narration(subject, customer_notes, terms)

    line_commands = [(5, 0, 0)] + _build_move_lines(
        lines, kwargs.get('analytic_id'),
    )

    vals = {
        'partner_id': partner_id,
        'invoice_date': invoice_date,
        'ref': kwargs.get('ref') or '',
        'invoice_line_ids': line_commands,
    }
    if kwargs.get('name') is not None:
        vals['name'] = kwargs['name']
    if kwargs.get('payment_term_id'):
        vals['invoice_payment_term_id'] = kwargs['payment_term_id']
    if kwargs.get('date_due'):
        vals['invoice_date_due'] = kwargs['date_due']
    if kwargs.get('user_id'):
        vals['user_id'] = kwargs['user_id']
    if narration:
        vals['narration'] = narration

    return odoo.write('account.move', [move_id], vals)


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
