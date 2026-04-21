from datetime import date, timedelta
from flask import (
    render_template, request, flash, redirect, url_for, current_app,
    jsonify, session, make_response,
)
from accounting import bp
from accounting import services
from accounting import transactions
from auth.routes import permission_required
from common.utils import format_many2one


@bp.route('/trial-balance')
@permission_required('accounting', 'read')
def trial_balance():
    odoo = current_app.odoo
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if not date_from:
        date_from = date(date.today().year, 1, 1).isoformat()
    if not date_to:
        date_to = date.today().isoformat()

    data = {'rows': [], 'total_debit': 0, 'total_credit': 0}
    try:
        data = services.get_trial_balance(odoo, date_from, date_to)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/trial_balance.html',
                           data=data, date_from=date_from, date_to=date_to)


@bp.route('/pnl')
@permission_required('accounting', 'read')
def pnl():
    odoo = current_app.odoo
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if not date_from:
        date_from = date(date.today().year, 1, 1).isoformat()
    if not date_to:
        date_to = date.today().isoformat()

    data = {'income': [], 'expenses': [], 'totals': {}}
    try:
        data = services.get_pnl(odoo, date_from, date_to)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/pnl.html',
                           data=data, date_from=date_from, date_to=date_to)


@bp.route('/balance-sheet')
@permission_required('accounting', 'read')
def balance_sheet():
    odoo = current_app.odoo
    as_of = request.args.get('as_of', date.today().isoformat())

    data = {'assets': [], 'liabilities': [], 'equity': [], 'totals': {}}
    try:
        data = services.get_balance_sheet(odoo, as_of)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/balance_sheet.html',
                           data=data, as_of=as_of)


@bp.route('/aged-receivable')
@permission_required('accounting', 'read')
def aged_receivable():
    odoo = current_app.odoo
    as_of = request.args.get('as_of', date.today().isoformat())

    data = {'rows': [], 'totals': {}}
    try:
        data = services.get_aged_report(odoo, 'asset_receivable', as_of)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/aged_report.html',
                           data=data, as_of=as_of,
                           title='Aged Receivables', report_type='receivable')


@bp.route('/aged-payable')
@permission_required('accounting', 'read')
def aged_payable():
    odoo = current_app.odoo
    as_of = request.args.get('as_of', date.today().isoformat())

    data = {'rows': [], 'totals': {}}
    try:
        data = services.get_aged_report(odoo, 'liability_payable', as_of)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/aged_report.html',
                           data=data, as_of=as_of,
                           title='Aged Payables', report_type='payable')


@bp.route('/cash-flow')
@permission_required('accounting', 'read')
def cash_flow():
    odoo = current_app.odoo
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    if not date_from:
        date_from = (date.today() - timedelta(days=90)).isoformat()
    if not date_to:
        date_to = date.today().isoformat()

    data = {'entries': [], 'totals': {}}
    try:
        data = services.get_cash_flow(odoo, date_from, date_to)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/cash_flow.html',
                           data=data, date_from=date_from, date_to=date_to)


# ---------------------------------------------------------------------------
# Transaction List
# ---------------------------------------------------------------------------

from common.list_query import (
    parse_list_query, search_facet, select_facet, date_range_facet,
)
from common.list_totals import compute_list_totals


def _move_facets(partner_label):
    return [
        search_facet(
            'q', ['name', 'partner_id.name', 'ref', 'invoice_origin'],
            placeholder=f'Search number, {partner_label.lower()}, source…',
        ),
        select_facet('state', 'state', [
            ('draft', 'Draft'),
            ('posted', 'Posted'),
            ('cancel', 'Cancelled'),
        ], label='Status'),
        select_facet('payment_state', 'payment_state', [
            ('not_paid', 'Unpaid'),
            ('partial', 'Partial'),
            ('paid', 'Paid'),
            ('in_payment', 'In Payment'),
        ], label='Payment'),
        date_range_facet('date_from', 'date_to', 'invoice_date'),
    ]


MOVE_SORT_MAP = {
    'date': 'invoice_date',
    'name': 'name',
    'partner': 'partner_id',
    'amount': 'amount_total',
    'residual': 'amount_residual',
    'state': 'state',
    'payment': 'payment_state',
}


def _render_move_list(move_type, title, partner_label):
    odoo = current_app.odoo
    facets = _move_facets(partner_label)
    query = parse_list_query(
        request.args, facets, MOVE_SORT_MAP,
        default_sort='date_desc',
    )
    moves = []
    totals = {'count': 0, 'sums': {'amount_total': 0.0, 'amount_residual': 0.0}}
    try:
        moves, full_domain = transactions.get_moves_list(
            odoo, move_type,
            domain=query['domain'],
            order=query['order'],
            offset=query['offset'],
            limit=query['limit'],
        )
        totals = compute_list_totals(
            odoo, 'account.move', full_domain,
            sum_fields=['amount_total', 'amount_residual'],
        )
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template(
        'accounting/move_list.html',
        moves=moves,
        title=title,
        list_type=move_type,
        partner_label=partner_label,
        facets=facets,
        query=query,
        totals=totals,
    )


@bp.route('/invoices')
@permission_required('accounting', 'read')
def invoice_list():
    return _render_move_list('invoices', 'Customer Invoices', 'Customer')


@bp.route('/bills')
@permission_required('accounting', 'read')
def bill_list():
    return _render_move_list('bills', 'Vendor Bills', 'Vendor')


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def _pick_dominant_analytic(invoice_lines):
    """Delegate to the shared tally helper so SO import and invoice view
    agree on which job an invoice belongs to."""
    return transactions._tally_analytic_distribution(invoice_lines)


def _handle_move_create(kind, move=None):
    """Shared POST/GET handler for create AND edit of invoices and bills.

    When ``move`` is supplied, the page runs in edit mode: form submissions
    update the existing record via Odoo write() rather than creating a new
    one, and the template pre-fills every input with the current values.
    Edit is only meaningful on draft moves (posted moves must be reset
    first).
    """
    odoo = current_app.odoo
    is_invoice = (kind == 'invoice')
    is_edit = move is not None

    if request.method == 'POST':
        import base64

        try:
            partner_id = request.form.get('partner_id', type=int)
            if not partner_id:
                flash(f'Please select a {"customer" if is_invoice else "vendor"}.', 'warning')
                return redirect(request.path)

            invoice_date = request.form.get('invoice_date', date.today().isoformat())
            name = (request.form.get('name') or '').strip() or None
            ref = request.form.get('ref', '')
            analytic_id = request.form.get('analytic_id', type=int)
            payment_term_id = request.form.get('payment_term_id', type=int)
            date_due = request.form.get('date_due') or None
            user_id = request.form.get('user_id', type=int)
            subject = request.form.get('subject', '')
            customer_notes = request.form.get('customer_notes', '')
            terms = request.form.get('terms', '')
            action = request.form.get('action', 'draft')

            lines = _parse_lines(request.form)
            if not lines:
                flash('Please add at least one line.', 'warning')
                return redirect(request.path)

            kwargs = dict(
                ref=ref, analytic_id=analytic_id,
                name=name, payment_term_id=payment_term_id,
                date_due=date_due, user_id=user_id,
                subject=subject, customer_notes=customer_notes, terms=terms,
            )

            if is_edit:
                move_id = move['id']
                transactions.update_move(
                    odoo, move_id, partner_id, invoice_date, lines, **kwargs,
                )
            else:
                creator = transactions.create_invoice if is_invoice else transactions.create_bill
                move_id = creator(odoo, partner_id, invoice_date, lines, **kwargs)

            files = request.files.getlist('attachments')
            for f in files:
                if not f or not f.filename:
                    continue
                try:
                    data = base64.b64encode(f.read()).decode('utf-8')
                    transactions.upload_attachment(
                        odoo, move_id, f.filename, data,
                        f.mimetype or 'application/octet-stream',
                    )
                except Exception as upload_err:
                    current_app.logger.warning(
                        'Attachment upload failed on move %s: %s',
                        move_id, upload_err,
                    )
                    flash(f'"{f.filename}" could not be uploaded: {upload_err}', 'warning')

            label = 'Invoice' if is_invoice else 'Bill'
            if action == 'send':
                try:
                    transactions.post_move(odoo, move_id)
                    flash(f'{label} {"updated" if is_edit else "created"} and posted.', 'success')
                except Exception as post_err:
                    flash(f'{label} {"updated" if is_edit else "created"} but could not be posted: {post_err}', 'warning')
            else:
                flash(
                    f'{label} {"updated" if is_edit else "saved as draft"}.',
                    'success',
                )

            return redirect(url_for('accounting.view_move', move_id=move_id))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    subject, customer_notes, terms = ('', '', '')
    if is_edit:
        subject, customer_notes, terms = transactions.parse_narration(
            move.get('narration') or '',
        )

    if is_edit:
        title = f'Edit {"Invoice" if is_invoice else "Bill"} {move.get("name") or ""}'.strip()
    else:
        title = 'Create Customer Invoice' if is_invoice else 'Create Vendor Bill'

    # Only sales orders are relevant on customer invoices — bills pull from
    # purchase orders (not implemented here yet).
    sales_orders = transactions.get_open_sales_orders(odoo) if is_invoice else []

    return render_template(
        'accounting/create_move.html',
        move_type=kind,
        title=title,
        is_edit=is_edit,
        move=move,
        prefill_subject=subject,
        prefill_customer_notes=customer_notes,
        prefill_terms=terms,
        partners=transactions.get_partners(odoo, 'customer' if is_invoice else 'supplier'),
        products=transactions.get_products(odoo, sale=is_invoice),
        accounts=transactions.get_accounts(odoo),
        analytics=transactions.get_analytic_accounts(odoo),
        taxes=transactions.get_taxes(odoo, 'sale' if is_invoice else 'purchase'),
        payment_terms=transactions.get_payment_terms(odoo),
        salespersons=transactions.get_salespersons(odoo),
        sales_orders=sales_orders,
        today=date.today().isoformat(),
    )


@bp.route('/api/sale-order/<int:so_id>')
@permission_required('accounting', 'read')
def api_sale_order(so_id):
    """JSON detail for a single SO — used by the Create Invoice form's
    "From Sales Order" picker to pre-fill customer and job."""
    odoo = current_app.odoo
    try:
        data = transactions.get_sale_order_detail(odoo, so_id)
        if not data:
            return jsonify({'error': 'Not found'}), 404
        return jsonify(data)
    except Exception as e:
        current_app.logger.warning('SO fetch failed: %s', e)
        return jsonify({'error': str(e)}), 500


@bp.route('/move/<int:move_id>/edit', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def edit_move(move_id):
    odoo = current_app.odoo
    try:
        move = transactions.get_move(odoo, move_id)
    except Exception as e:
        flash(f'Error loading transaction: {e}', 'danger')
        return redirect(url_for('accounting.invoice_list'))

    if not move:
        flash('Transaction not found.', 'warning')
        return redirect(url_for('accounting.invoice_list'))

    if move.get('state') != 'draft':
        flash('Only draft transactions can be edited. Use "Reset to Draft" first.',
              'warning')
        return redirect(url_for('accounting.view_move', move_id=move_id))

    kind = 'invoice' if move.get('move_type') in ('out_invoice', 'out_refund') else 'bill'
    return _handle_move_create(kind, move=move)


@bp.route('/move/<int:move_id>/reset-draft', methods=['POST'])
@permission_required('accounting', 'write')
def reset_move_to_draft(move_id):
    odoo = current_app.odoo
    try:
        transactions.reset_move_to_draft(odoo, move_id)
        flash('Transaction reset to draft — you can now edit it.', 'success')
    except Exception as e:
        flash(f'Could not reset to draft: {e}', 'danger')
    return redirect(url_for('accounting.view_move', move_id=move_id))


@bp.route('/invoice/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_invoice():
    return _handle_move_create('invoice')


@bp.route('/bill/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_bill():
    return _handle_move_create('bill')


@bp.route('/payment/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_payment():
    odoo = current_app.odoo
    move_id = request.args.get('move_id', type=int)

    if request.method == 'POST':
        try:
            amount = request.form.get('amount', 0, type=float)
            payment_date = request.form.get('payment_date', date.today().isoformat())
            journal_id = request.form.get('journal_id', type=int)
            ref = request.form.get('ref', '')
            linked_move_id = request.form.get('move_id', type=int)

            if not amount or not journal_id:
                flash('Please fill amount and journal.', 'warning')
                return redirect(url_for('accounting.create_payment', move_id=linked_move_id))

            if linked_move_id:
                # Register payment against specific invoice/bill
                transactions.register_payment_on_invoice(
                    odoo, linked_move_id, journal_id, amount, payment_date, ref
                )
                flash('Payment registered and linked to invoice/bill.', 'success')
                return redirect(url_for('accounting.view_move', move_id=linked_move_id))
            else:
                # Standalone payment
                partner_id = request.form.get('partner_id', type=int)
                payment_type = request.form.get('payment_type', 'inbound')
                transactions.create_payment(
                    odoo, partner_id, amount, payment_date, payment_type, journal_id, ref
                )
                flash('Payment recorded successfully.', 'success')
                return redirect(url_for('accounting.pnl'))

        except Exception as e:
            flash(f'Error: {e}', 'danger')

    # Pre-fill from invoice if move_id provided
    linked_move = None
    if move_id:
        try:
            linked_move = transactions.get_move(odoo, move_id)
        except Exception:
            pass

    unpaid = []
    try:
        unpaid = transactions.get_unpaid_invoices(odoo)
        for u in unpaid:
            u['partner_name'] = format_many2one(u.get('partner_id'))
    except Exception:
        pass

    return render_template('accounting/create_payment.html',
                           partners=transactions.get_partners(odoo),
                           journals=transactions.get_bank_journals(odoo),
                           unpaid=unpaid,
                           linked_move=linked_move,
                           today=date.today().isoformat())


@bp.route('/journal-entry/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_journal_entry():
    odoo = current_app.odoo

    if request.method == 'POST':
        try:
            journal_id = request.form.get('journal_id', type=int)
            entry_date = request.form.get('entry_date', date.today().isoformat())
            ref = request.form.get('ref', '')

            lines = _parse_je_lines(request.form)
            if not lines:
                flash('Please add at least two lines.', 'warning')
                return redirect(url_for('accounting.create_journal_entry'))

            total_debit = sum(l.get('debit', 0) for l in lines)
            total_credit = sum(l.get('credit', 0) for l in lines)
            if abs(total_debit - total_credit) > 0.01:
                flash(f'Debits (${total_debit:.2f}) must equal Credits (${total_credit:.2f}).', 'danger')
                return redirect(url_for('accounting.create_journal_entry'))

            move_id = transactions.create_journal_entry(
                odoo, journal_id, entry_date, lines, ref=ref
            )
            flash('Journal entry created successfully.', 'success')
            return redirect(url_for('accounting.view_move', move_id=move_id))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    return render_template('accounting/create_journal_entry.html',
                           accounts=transactions.get_accounts(odoo),
                           journals=transactions.get_journals(odoo, 'general'),
                           analytics=transactions.get_analytic_accounts(odoo),
                           partners=transactions.get_partners(odoo),
                           today=date.today().isoformat())


@bp.route('/move/<int:move_id>')
@permission_required('accounting', 'read')
def view_move(move_id):
    odoo = current_app.odoo
    move = None
    attachments = []
    try:
        move = transactions.get_move(odoo, move_id)
        if not move:
            flash('Transaction not found.', 'warning')
            return redirect(url_for('accounting.trial_balance'))
        attachments = transactions.get_move_attachments(odoo, move_id)
    except Exception as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('accounting.trial_balance'))

    from auth.db import has_permission
    can_write = has_permission(session.get('permissions', {}),
                               'accounting', 'write')

    subject, customer_notes, terms = transactions.parse_narration(
        move.get('narration') or '',
    )
    is_invoice = move.get('move_type') in ('out_invoice', 'out_refund')
    kind = 'invoice' if is_invoice else 'bill'

    # If this invoice is tied to a job, compute the progress-billing context
    # so the same Contract/Billed/Paid/Outstanding/Remaining card appears here.
    billing_summary = None
    if is_invoice:
        analytic_id = _pick_dominant_analytic(move.get('invoice_lines') or [])
        if analytic_id:
            try:
                from jobcosting import services as jc_services
                billing_summary = jc_services.get_billing_summary(
                    odoo, analytic_id,
                )
                billing_summary['analytic_id'] = analytic_id
            except Exception as bs_err:
                current_app.logger.warning(
                    'Billing summary failed for move %s: %s',
                    move_id, bs_err,
                )

    return render_template(
        'accounting/create_move.html',
        mode='view',
        move_type=kind,
        title=move.get('name') or 'Transaction',
        move=move,
        attachments=attachments,
        can_write=can_write,
        prefill_subject=subject,
        prefill_customer_notes=customer_notes,
        prefill_terms=terms,
        analytics=transactions.get_analytic_accounts(odoo),
        partners=[],
        products=[],
        accounts=[],
        taxes=[],
        payment_terms=[],
        salespersons=[],
        sales_orders=[],
        billing_summary=billing_summary,
        today=date.today().isoformat(),
    )


@bp.route('/move/<int:move_id>/upload', methods=['POST'])
@permission_required('accounting', 'write')
def upload_attachment(move_id):
    odoo = current_app.odoo
    import base64

    file = request.files.get('file')
    if not file or not file.filename:
        flash('No file selected.', 'warning')
        return redirect(url_for('accounting.view_move', move_id=move_id))

    try:
        file_data = base64.b64encode(file.read()).decode('utf-8')
        transactions.upload_attachment(
            odoo, move_id, file.filename, file_data, file.mimetype
        )
        flash(f'"{file.filename}" uploaded successfully.', 'success')
    except Exception as e:
        flash(f'Upload error: {e}', 'danger')

    return redirect(url_for('accounting.view_move', move_id=move_id))


@bp.route('/move/<int:move_id>/attachment/<int:attachment_id>/delete',
          methods=['POST'])
@permission_required('accounting', 'write')
def delete_move_attachment(move_id, attachment_id):
    """Delete an attachment on a specific move.

    Deleting the "main" (cached) PDF here is the documented workaround
    for Odoo caching the rendered invoice: the next Send & Print triggers
    a fresh render from the current invoice data.
    """
    odoo = current_app.odoo
    try:
        ok = transactions.delete_attachment(odoo, attachment_id, move_id)
        if ok:
            flash('Attachment deleted. Odoo will regenerate the PDF the '
                  'next time you send the invoice.', 'success')
        else:
            flash('Attachment not found for this document.', 'warning')
    except Exception as e:
        flash(f'Delete failed: {e}', 'danger')
    return redirect(url_for('accounting.view_move', move_id=move_id))


@bp.route('/attachment/<int:attachment_id>')
@permission_required('accounting', 'read')
def download_attachment(attachment_id):
    """Serve an ir.attachment inline (preview) or as a forced download.

    ``?download=1`` switches to ``Content-Disposition: attachment`` so the
    browser saves the file instead of rendering it. Default is inline so
    PDFs/images open in the browser tab.
    """
    odoo = current_app.odoo
    import base64
    from urllib.parse import quote

    force_download = request.args.get('download') in ('1', 'true', 'yes')

    try:
        atts = odoo.search_read(
            'ir.attachment',
            [('id', '=', attachment_id)],
            fields=['name', 'datas', 'mimetype'],
        )
        if not atts or not atts[0].get('datas'):
            flash('Attachment not found or empty.', 'warning')
            return redirect(url_for('accounting.trial_balance'))

        att = atts[0]
        data = base64.b64decode(att['datas'])

        disposition = 'attachment' if force_download else 'inline'
        filename = att['name'] or f'attachment-{attachment_id}'
        # RFC 5987: quote non-ASCII filenames for broad browser support.
        quoted = quote(filename)

        response = make_response(data)
        response.headers['Content-Type'] = att.get('mimetype') or 'application/octet-stream'
        response.headers['Content-Disposition'] = (
            f"{disposition}; filename=\"{filename}\"; filename*=UTF-8''{quoted}"
        )
        response.headers['Content-Length'] = str(len(data))
        return response
    except Exception as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('accounting.trial_balance'))


@bp.route('/move/<int:move_id>/post', methods=['POST'])
@permission_required('accounting', 'write')
def post_move(move_id):
    odoo = current_app.odoo
    try:
        transactions.post_move(odoo, move_id)
        flash('Transaction posted successfully.', 'success')
    except Exception as e:
        flash(f'Error posting: {e}', 'danger')
    return redirect(url_for('accounting.view_move', move_id=move_id))


# ---------------------------------------------------------------------------
# Bank Reconciliation
# ---------------------------------------------------------------------------

@bp.route('/reconcile')
@permission_required('accounting', 'write')
def reconcile():
    odoo = current_app.odoo
    journal_id = request.args.get('journal_id', type=int)

    journals = []
    unreconciled = []
    try:
        journals = transactions.get_bank_journals(odoo)
        if not journal_id and journals:
            journal_id = journals[0]['id']
        if journal_id:
            unreconciled = transactions.get_unreconciled_lines(odoo, journal_id)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/reconcile.html',
                           journals=journals,
                           selected_journal=journal_id,
                           unreconciled=unreconciled)


@bp.route('/reconcile/suggest/<int:line_id>')
@permission_required('accounting', 'write')
def reconcile_suggest(line_id):
    """API: get suggested matches for a bank line."""
    odoo = current_app.odoo
    try:
        lines = odoo.safe_search_read(
            'account.move.line',
            [('id', '=', line_id)],
            fields=['id', 'name', 'date', 'ref', 'debit', 'credit', 'balance',
                    'partner_id', 'move_id'],
        )
        if not lines:
            return jsonify([])

        suggestions = transactions.get_suggested_matches(odoo, lines[0])
        return jsonify(suggestions)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@bp.route('/reconcile/match', methods=['POST'])
@permission_required('accounting', 'write')
def reconcile_match():
    """API: reconcile selected line IDs together."""
    odoo = current_app.odoo
    data = request.get_json()
    line_ids = data.get('line_ids', [])

    if len(line_ids) < 2:
        return jsonify({'error': 'Select at least 2 lines to reconcile'}), 400

    try:
        transactions.reconcile_lines(odoo, line_ids)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_lines(form):
    """Parse invoice/bill lines from form data. Includes per-line discount."""
    lines = []
    i = 0
    while True:
        if f'line_name_{i}' not in form and f'line_product_{i}' not in form:
            break

        product_id = form.get(f'line_product_{i}', type=int)
        name = form.get(f'line_name_{i}', '')
        qty = float(form.get(f'line_qty_{i}', 1) or 1)
        price = float(form.get(f'line_price_{i}', 0) or 0)
        discount = float(form.get(f'line_discount_{i}', 0) or 0)
        tax_id = form.get(f'line_tax_{i}', type=int)

        if name or product_id:
            line = {'name': name, 'quantity': qty, 'price_unit': price}
            if discount:
                line['discount'] = discount
            if product_id:
                line['product_id'] = product_id
            if tax_id:
                line['tax_ids'] = [tax_id]
            lines.append(line)
        i += 1
    return lines


def _parse_je_lines(form):
    """Parse journal entry lines from form data."""
    lines = []
    i = 0
    while True:
        acct_key = f'je_account_{i}'
        if acct_key not in form:
            break
        account_id = form.get(acct_key, type=int)
        name = form.get(f'je_name_{i}', '')
        debit = float(form.get(f'je_debit_{i}', 0) or 0)
        credit = float(form.get(f'je_credit_{i}', 0) or 0)
        partner_id = form.get(f'je_partner_{i}', type=int)
        analytic_id = form.get(f'je_analytic_{i}', type=int)

        if account_id and (debit or credit):
            line = {
                'account_id': account_id,
                'name': name,
                'debit': debit,
                'credit': credit,
            }
            if partner_id:
                line['partner_id'] = partner_id
            if analytic_id:
                line['analytic_id'] = analytic_id
            lines.append(line)
        i += 1
    return lines
