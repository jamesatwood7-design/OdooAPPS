from datetime import date, timedelta
from flask import render_template, request, flash, redirect, url_for, current_app, jsonify
from accounting import bp
from accounting import services
from accounting import transactions
from auth.routes import permission_required


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
                           accounts=transactions.get_accounts(odoo),
                           analytics=transactions.get_analytic_accounts(odoo),
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
                           accounts=transactions.get_accounts(odoo),
                           analytics=transactions.get_analytic_accounts(odoo),
                           today=date.today().isoformat())


@bp.route('/payment/create', methods=['GET', 'POST'])
@permission_required('accounting', 'write')
def create_payment():
    odoo = current_app.odoo

    if request.method == 'POST':
        try:
            partner_id = request.form.get('partner_id', type=int)
            amount = request.form.get('amount', 0, type=float)
            payment_date = request.form.get('payment_date', date.today().isoformat())
            payment_type = request.form.get('payment_type', 'inbound')
            journal_id = request.form.get('journal_id', type=int)
            ref = request.form.get('ref', '')

            if not partner_id or not amount or not journal_id:
                flash('Please fill all required fields.', 'warning')
                return redirect(url_for('accounting.create_payment'))

            transactions.create_payment(
                odoo, partner_id, amount, payment_date, payment_type, journal_id, ref
            )
            flash('Payment recorded successfully.', 'success')
            return redirect(url_for('accounting.pnl'))
        except Exception as e:
            flash(f'Error: {e}', 'danger')

    return render_template('accounting/create_payment.html',
                           partners=transactions.get_partners(odoo),
                           journals=transactions.get_bank_journals(odoo),
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
    try:
        move = transactions.get_move(odoo, move_id)
        if not move:
            flash('Transaction not found.', 'warning')
            return redirect(url_for('accounting.trial_balance'))
    except Exception as e:
        flash(f'Error: {e}', 'danger')
        return redirect(url_for('accounting.trial_balance'))

    return render_template('accounting/view_move.html', move=move)


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
        name_key = f'line_name_{i}'
        if name_key not in form:
            break
        name = form.get(name_key, '')
        qty = float(form.get(f'line_qty_{i}', 1) or 1)
        price = float(form.get(f'line_price_{i}', 0) or 0)
        account_id = form.get(f'line_account_{i}', type=int)

        if name and price:
            line = {'name': name, 'quantity': qty, 'price_unit': price}
            if account_id:
                line['account_id'] = account_id
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
