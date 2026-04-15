"""Accounting services - fetch financial data from Odoo for reports."""

from datetime import date, timedelta
from common.utils import format_currency, format_many2one


# Odoo 17 account types mapping
INCOME_TYPES = ('income', 'income_other')
EXPENSE_TYPES = ('expense', 'expense_depreciation', 'expense_direct_cost')
ASSET_TYPES = (
    'asset_receivable', 'asset_cash', 'asset_current',
    'asset_non_current', 'asset_prepayments', 'asset_fixed',
)
LIABILITY_TYPES = (
    'liability_payable', 'liability_credit_card', 'liability_current',
    'liability_non_current',
)
EQUITY_TYPES = ('equity', 'equity_unaffected')
RECEIVABLE_TYPE = 'asset_receivable'
PAYABLE_TYPE = 'liability_payable'
BANK_TYPES = ('asset_cash',)


def get_chart_of_accounts(odoo):
    """Fetch all accounts from the chart of accounts."""
    return odoo.search_read(
        'account.account', [],
        fields=['id', 'code', 'name', 'account_type', 'reconcile'],
        order='code asc',
    )


def get_trial_balance(odoo, date_from=None, date_to=None, posted_only=True):
    """Compute trial balance: debit, credit, balance per account.

    Uses read_group on account.move.line for server-side aggregation.
    """
    domain = []
    if date_from:
        domain.append(('date', '>=', date_from))
    if date_to:
        domain.append(('date', '<=', date_to))
    if posted_only:
        domain.append(('parent_state', '=', 'posted'))

    try:
        groups = odoo.read_group(
            'account.move.line', domain,
            ['account_id', 'debit', 'credit', 'balance'],
            ['account_id'],
        )
    except Exception:
        groups = []

    # Get account details for display
    accounts = get_chart_of_accounts(odoo)
    acct_map = {a['id']: a for a in accounts}

    rows = []
    total_debit = 0
    total_credit = 0

    for g in groups:
        acct_val = g.get('account_id')
        if not acct_val:
            continue
        acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
        acct = acct_map.get(acct_id, {})

        debit = g.get('debit', 0) or 0
        credit = g.get('credit', 0) or 0
        balance = debit - credit

        if debit == 0 and credit == 0:
            continue

        rows.append({
            'account_id': acct_id,
            'code': acct.get('code', ''),
            'name': acct.get('name', acct_val[1] if isinstance(acct_val, (list, tuple)) else ''),
            'account_type': acct.get('account_type', ''),
            'debit': debit,
            'credit': credit,
            'balance': balance,
        })
        total_debit += debit
        total_credit += credit

    rows.sort(key=lambda r: r['code'])

    return {
        'rows': rows,
        'total_debit': total_debit,
        'total_credit': total_credit,
        'total_balance': total_debit - total_credit,
    }


def get_pnl(odoo, date_from=None, date_to=None, posted_only=True):
    """Profit & Loss statement.

    Groups income and expense accounts with subtotals.
    """
    domain = []
    if date_from:
        domain.append(('date', '>=', date_from))
    if date_to:
        domain.append(('date', '<=', date_to))
    if posted_only:
        domain.append(('parent_state', '=', 'posted'))

    # Get accounts of income/expense types
    accounts = odoo.search_read(
        'account.account',
        [('account_type', 'in', list(INCOME_TYPES + EXPENSE_TYPES))],
        fields=['id', 'code', 'name', 'account_type'],
        order='code asc',
    )
    acct_ids = [a['id'] for a in accounts]
    acct_map = {a['id']: a for a in accounts}

    if not acct_ids:
        return {'income': [], 'expenses': [], 'totals': {}}

    # Get balances
    line_domain = domain + [('account_id', 'in', acct_ids)]
    try:
        groups = odoo.read_group(
            'account.move.line', line_domain,
            ['account_id', 'debit', 'credit', 'balance'],
            ['account_id'],
        )
    except Exception:
        groups = []

    balance_map = {}
    for g in groups:
        acct_val = g.get('account_id')
        acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
        balance_map[acct_id] = {
            'debit': g.get('debit', 0) or 0,
            'credit': g.get('credit', 0) or 0,
            'balance': g.get('balance', 0) or 0,
        }

    income_rows = []
    expense_rows = []
    total_income = 0
    total_expenses = 0

    for acct in accounts:
        bal = balance_map.get(acct['id'], {})
        if not bal:
            continue

        # In Odoo, income has negative balance (credit > debit)
        amount = abs(bal.get('balance', 0))
        if amount == 0:
            continue

        row = {
            'code': acct['code'],
            'name': acct['name'],
            'amount': amount,
            'account_type': acct['account_type'],
        }

        if acct['account_type'] in INCOME_TYPES:
            income_rows.append(row)
            total_income += amount
        else:
            expense_rows.append(row)
            total_expenses += amount

    net_profit = total_income - total_expenses

    return {
        'income': income_rows,
        'expenses': expense_rows,
        'totals': {
            'income': total_income,
            'expenses': total_expenses,
            'net_profit': net_profit,
            'margin_pct': (net_profit / total_income * 100) if total_income > 0 else 0,
        },
    }


def get_balance_sheet(odoo, as_of_date=None, posted_only=True):
    """Balance Sheet as of a specific date."""
    if not as_of_date:
        as_of_date = date.today().isoformat()

    domain = [('date', '<=', as_of_date)]
    if posted_only:
        domain.append(('parent_state', '=', 'posted'))

    accounts = odoo.search_read(
        'account.account',
        [('account_type', 'in', list(ASSET_TYPES + LIABILITY_TYPES + EQUITY_TYPES))],
        fields=['id', 'code', 'name', 'account_type'],
        order='code asc',
    )
    acct_ids = [a['id'] for a in accounts]
    acct_map = {a['id']: a for a in accounts}

    if not acct_ids:
        return {'assets': [], 'liabilities': [], 'equity': [], 'totals': {}}

    line_domain = domain + [('account_id', 'in', acct_ids)]
    try:
        groups = odoo.read_group(
            'account.move.line', line_domain,
            ['account_id', 'balance'],
            ['account_id'],
        )
    except Exception:
        groups = []

    balance_map = {}
    for g in groups:
        acct_val = g.get('account_id')
        acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
        balance_map[acct_id] = g.get('balance', 0) or 0

    assets = []
    liabilities = []
    equity = []
    total_assets = 0
    total_liabilities = 0
    total_equity = 0

    for acct in accounts:
        balance = balance_map.get(acct['id'], 0)
        if balance == 0:
            continue

        row = {'code': acct['code'], 'name': acct['name'], 'balance': abs(balance)}

        if acct['account_type'] in ASSET_TYPES:
            assets.append(row)
            total_assets += balance  # Assets have positive (debit) balance
        elif acct['account_type'] in LIABILITY_TYPES:
            liabilities.append(row)
            total_liabilities += abs(balance)  # Liabilities have negative (credit) balance
        elif acct['account_type'] in EQUITY_TYPES:
            equity.append(row)
            total_equity += abs(balance)

    return {
        'assets': assets,
        'liabilities': liabilities,
        'equity': equity,
        'totals': {
            'assets': total_assets,
            'liabilities': total_liabilities,
            'equity': total_equity,
        },
    }


def get_aged_report(odoo, account_type, as_of_date=None):
    """Aged receivable or payable report.

    Groups outstanding balances by partner and aging buckets.
    """
    if not as_of_date:
        as_of_date = date.today()
    elif isinstance(as_of_date, str):
        as_of_date = date.fromisoformat(as_of_date)

    # Buckets
    buckets = [
        ('Current', 0),
        ('1-30', 30),
        ('31-60', 60),
        ('61-90', 90),
        ('90+', None),
    ]

    # Get unreconciled lines for receivable/payable accounts
    domain = [
        ('account_id.account_type', '=', account_type),
        ('parent_state', '=', 'posted'),
        ('reconciled', '=', False),
        ('balance', '!=', 0),
    ]

    try:
        lines = odoo.search_read(
            'account.move.line', domain,
            fields=['partner_id', 'date_maturity', 'date', 'balance',
                    'move_id', 'name', 'ref'],
            order='partner_id, date_maturity',
            limit=2000,
        )
    except Exception:
        lines = []

    # Group by partner with aging
    partners = {}
    for line in lines:
        partner_val = line.get('partner_id')
        partner_name = format_many2one(partner_val)
        partner_id = partner_val[0] if isinstance(partner_val, (list, tuple)) else (partner_val or 0)

        if partner_id not in partners:
            partners[partner_id] = {
                'name': partner_name,
                'current': 0, 'b1_30': 0, 'b31_60': 0,
                'b61_90': 0, 'b90_plus': 0, 'total': 0,
            }

        due_date_str = line.get('date_maturity') or line.get('date')
        if due_date_str:
            try:
                due = date.fromisoformat(due_date_str) if isinstance(due_date_str, str) else due_date_str
                days_overdue = (as_of_date - due).days
            except (ValueError, TypeError):
                days_overdue = 0
        else:
            days_overdue = 0

        amount = abs(line.get('balance', 0))
        p = partners[partner_id]
        p['total'] += amount

        if days_overdue <= 0:
            p['current'] += amount
        elif days_overdue <= 30:
            p['b1_30'] += amount
        elif days_overdue <= 60:
            p['b31_60'] += amount
        elif days_overdue <= 90:
            p['b61_90'] += amount
        else:
            p['b90_plus'] += amount

    rows = sorted(partners.values(), key=lambda x: x['total'], reverse=True)

    totals = {
        'current': sum(r['current'] for r in rows),
        'b1_30': sum(r['b1_30'] for r in rows),
        'b31_60': sum(r['b31_60'] for r in rows),
        'b61_90': sum(r['b61_90'] for r in rows),
        'b90_plus': sum(r['b90_plus'] for r in rows),
        'total': sum(r['total'] for r in rows),
    }

    return {'rows': rows, 'totals': totals}


def get_cash_flow(odoo, date_from=None, date_to=None):
    """Cash flow: bank/cash account transactions over time."""
    if not date_from:
        date_from = (date.today() - timedelta(days=90)).isoformat()
    if not date_to:
        date_to = date.today().isoformat()

    # Get bank/cash accounts
    bank_accounts = odoo.search_read(
        'account.account',
        [('account_type', 'in', list(BANK_TYPES))],
        fields=['id', 'code', 'name'],
    )
    bank_ids = [a['id'] for a in bank_accounts]

    if not bank_ids:
        return {'entries': [], 'totals': {}}

    # Get daily totals
    try:
        groups = odoo.read_group(
            'account.move.line',
            [
                ('account_id', 'in', bank_ids),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
                ('parent_state', '=', 'posted'),
            ],
            ['date', 'debit', 'credit', 'balance'],
            ['date:day'],
        )
    except Exception:
        groups = []

    entries = []
    running_balance = 0
    total_inflow = 0
    total_outflow = 0

    for g in groups:
        debit = g.get('debit', 0) or 0
        credit = g.get('credit', 0) or 0
        net = debit - credit
        running_balance += net
        total_inflow += debit
        total_outflow += credit

        date_label = g.get('date:day', '')

        entries.append({
            'date': date_label,
            'inflow': debit,
            'outflow': credit,
            'net': net,
            'balance': running_balance,
        })

    return {
        'entries': entries,
        'totals': {
            'inflow': total_inflow,
            'outflow': total_outflow,
            'net': total_inflow - total_outflow,
        },
    }
