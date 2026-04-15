from datetime import date, timedelta
from flask import render_template, request, flash, current_app
from accounting import bp
from accounting import services
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
