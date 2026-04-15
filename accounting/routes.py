from datetime import date, timedelta
from flask import render_template, request, flash, redirect, url_for, current_app, jsonify
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

@bp.route('/invoices')
@permission_required('accounting', 'read')
def invoice_list():
    odoo = current_app.odoo
    state = request.args.get('state', '')
    payment_state = request.args.get('payment_state', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    moves = []
    try:
        moves = transactions.get_moves(
            odoo, move_type='invoices',
            state=state or None,
            payment_state=payment_state or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/move_list.html',
                           moves=moves, title='Customer Invoices',
                           list_type='invoices',
                           state=state, payment_state=payment_state,
                           date_from=date_from, date_to=date_to)


@bp.route('/bills')
@permission_required('accounting', 'read')
def bill_list():
    odoo = current_app.odoo
    state = request.args.get('state', '')
    payment_state = request.args.get('payment_state', '')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    moves = []
    try:
        moves = transactions.get_moves(
            odoo, move_type='bills',
            state=state or None,
            payment_state=payment_state or None,
            date_from=date_from or None,
            date_to=date_to or None,
        )
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template('accounting/move_list.html',
                           moves=moves, title='Vendor Bills',
                           list_type='bills',
                           state=state, payment_state=payment_state,
                           date_from=date_from, date_to=date_to)


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

@bp.route('/invoice/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_invoice():
    odoo = current_app.odoo

    if request.method == 'POST':
        try:
            partner_id = request.form.get('partner_id', type=int)
            invoice_date = request.form.get('invoice_date', date.today().isoformat())
            ref = request.form.get('ref', '')
            analytic_id = request.form.get('analytic_id', type=int)

            lines = _parse_lines(request.form)
            if not lines:
                flash('Please add at least one line.', 'warning')
                return redirect(url_for('accounting.create_invoice'))

            move_id = transactions.create_invoice(
                odoo, partner_id, invoice_date, lines, ref=ref, analytic_id=analytic_id
            )
            flash(f'Invoice created successfully.', 'success')
            return redirect(url_for('accounting.view_move', move_id=move_id))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    return render_template('accounting/create_move.html',
                           move_type='invoice',
                           title='Create Customer Invoice',
                           partners=transactions.get_partners(odoo, 'customer'),
                           products=transactions.get_products(odoo, sale=True),
                           accounts=transactions.get_accounts(odoo),
                           analytics=transactions.get_analytic_accounts(odoo),
                           taxes=transactions.get_taxes(odoo, 'sale'),
                           today=date.today().isoformat())


@bp.route('/bill/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_bill():
    odoo = current_app.odoo

    if request.method == 'POST':
        try:
            partner_id = request.form.get('partner_id', type=int)
            invoice_date = request.form.get('invoice_date', date.today().isoformat())
            ref = request.form.get('ref', '')
            analytic_id = request.form.get('analytic_id', type=int)

            lines = _parse_lines(request.form)
            if not lines:
                flash('Please add at least one line.', 'warning')
                return redirect(url_for('accounting.create_bill'))

            move_id = transactions.create_bill(
                odoo, partner_id, invoice_date, lines, ref=ref, analytic_id=analytic_id
            )
            flash(f'Bill created successfully.', 'success')
            return redirect(url_for('accounting.view_move', move_id=move_id))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    return render_template('accounting/create_move.html',
                           move_type='bill',
                           title='Create Vendor Bill',
                           partners=transactions.get_partners(odoo, 'supplier'),
                           products=transactions.get_products(odoo, sale=False),
                           accounts=transactions.get_accounts(odoo),
                           analytics=transactions.get_analytic_accounts(odoo),
                           taxes=transactions.get_taxes(odoo, 'purchase'),
                           today=date.today().isoformat())


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

    return render_template('accounting/view_move.html', move=move,
                           attachments=attachments)


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


@bp.route('/attachment/<int:attachment_id>')
@permission_required('accounting', 'read')
def download_attachment(attachment_id):
    """Download/view an attachment."""
    odoo = current_app.odoo
    import base64

    try:
        atts = odoo.search_read(
            'ir.attachment',
            [('id', '=', attachment_id)],
            fields=['name', 'datas', 'mimetype'],
        )
        if not atts:
            flash('Attachment not found.', 'warning')
            return redirect(url_for('accounting.trial_balance'))

        att = atts[0]
        data = base64.b64decode(att['datas'])

        response = make_response(data)
        response.headers['Content-Type'] = att.get('mimetype', 'application/octet-stream')
        response.headers['Content-Disposition'] = f'inline; filename="{att["name"]}"'
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
    """Parse invoice/bill lines from form data."""
    lines = []
    i = 0
    while True:
        # Check for either product or name based line
        if f'line_name_{i}' not in form and f'line_product_{i}' not in form:
            break

        product_id = form.get(f'line_product_{i}', type=int)
        name = form.get(f'line_name_{i}', '')
        qty = float(form.get(f'line_qty_{i}', 1) or 1)
        price = float(form.get(f'line_price_{i}', 0) or 0)
        tax_id = form.get(f'line_tax_{i}', type=int)

        if name or product_id:
            line = {'name': name, 'quantity': qty, 'price_unit': price}
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
