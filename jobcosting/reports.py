"""Financial reporting services for job costing.

Provides data for profitability dashboard, employee cost reports,
WIP reports, and job comparisons.
"""

from common.utils import format_duration, format_currency, format_many2one
from jobcosting.field_mapping import (
    resolve_status_field, resolve_dashboard_columns, format_odoo_value,
    get_custom_field_map, resolve_field,
)


def get_profitability_data(odoo):
    """Aggregate profitability data across all jobs.

    Returns revenue, costs, margins per job plus totals for charts.
    Uses batch queries for performance.
    """
    # Get all analytic accounts with custom financial fields
    field_map = get_custom_field_map(odoo)

    # Resolve key financial fields
    financial_labels = {
        'Sales Price': 'Current Sales Price',
        'Total Expenses': 'Total Expenses',
        'Current Margin': 'Current Margin',
        'Actual Profit': 'Actual Profit',
        'Actual Margin %': 'Actual Margin',
    }

    field_names = ['id', 'name', 'code']
    label_to_tech = {}
    for display, odoo_label in financial_labels.items():
        tech, _ = resolve_field(field_map, odoo_label)
        if tech:
            label_to_tech[display] = tech
            field_names.append(tech)

    # Get status field
    status_field, status_options = resolve_status_field(odoo)
    if status_field:
        field_names.append(status_field)

    status_sel_map = dict(status_options) if status_options else {}

    accounts = odoo.search_read(
        'account.analytic.account', [],
        fields=field_names,
        order='code asc',
    )

    # Get cost totals from analytic lines grouped by account
    cost_by_account = {}
    try:
        cost_groups = odoo.read_group(
            'account.analytic.line', [],
            ['account_id', 'amount', 'unit_amount'],
            ['account_id'],
        )
        for g in cost_groups:
            acct_val = g.get('account_id')
            acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
            cost_by_account[acct_id] = {
                'total_cost': abs(g.get('amount', 0) or 0),
                'total_hours': g.get('unit_amount', 0) or 0,
            }
    except Exception:
        pass

    jobs = []
    totals = {
        'revenue': 0, 'expenses': 0, 'margin': 0,
        'profit': 0, 'jobs_count': 0, 'active_count': 0,
    }

    for acct in accounts:
        raw_status = acct.get(status_field, '') if status_field else ''
        if isinstance(raw_status, (list, tuple)):
            status = raw_status[1] if len(raw_status) >= 2 else ''
        else:
            status = status_sel_map.get(raw_status, str(raw_status)) if raw_status else ''

        revenue = float(acct.get(label_to_tech.get('Sales Price', ''), 0) or 0)
        expenses = float(acct.get(label_to_tech.get('Total Expenses', ''), 0) or 0)
        margin = float(acct.get(label_to_tech.get('Current Margin', ''), 0) or 0)
        profit = float(acct.get(label_to_tech.get('Actual Profit', ''), 0) or 0)
        margin_pct = float(acct.get(label_to_tech.get('Actual Margin %', ''), 0) or 0)

        line_data = cost_by_account.get(acct['id'], {})

        job = {
            'id': acct['id'],
            'code': acct.get('code', ''),
            'name': acct.get('name', ''),
            'status': status,
            'revenue': revenue,
            'expenses': expenses,
            'margin': margin,
            'profit': profit,
            'margin_pct': margin_pct,
            'line_cost': line_data.get('total_cost', 0),
            'line_hours': line_data.get('total_hours', 0),
        }
        jobs.append(job)

        totals['revenue'] += revenue
        totals['expenses'] += expenses
        totals['margin'] += margin
        totals['profit'] += profit
        totals['jobs_count'] += 1
        if status == 'In Progress':
            totals['active_count'] += 1

    totals['margin_pct'] = (
        (totals['margin'] / totals['revenue'] * 100) if totals['revenue'] else 0
    )

    # Top 10 jobs by revenue for charts
    top_by_revenue = sorted(
        [j for j in jobs if j['revenue'] > 0],
        key=lambda x: x['revenue'], reverse=True,
    )[:10]

    # Jobs with negative margin (problem jobs)
    problem_jobs = [j for j in jobs if j['margin'] < 0]

    return {
        'jobs': jobs,
        'totals': totals,
        'top_by_revenue': top_by_revenue,
        'problem_jobs': problem_jobs,
    }


def get_employee_cost_data(odoo, date_from=None, date_to=None):
    """Get hours and costs per employee across all jobs.

    Groups analytic lines by employee, then by account.
    """
    domain = []
    if date_from:
        domain.append(('date', '>=', date_from))
    if date_to:
        domain.append(('date', '<=', date_to))

    # Group by employee
    try:
        emp_groups = odoo.read_group(
            'account.analytic.line', domain,
            ['employee_id', 'unit_amount', 'amount'],
            ['employee_id'],
        )
    except Exception:
        emp_groups = []

    employees = []
    total_hours = 0
    total_cost = 0

    for g in emp_groups:
        emp_val = g.get('employee_id')
        if not emp_val:
            continue
        emp_id = emp_val[0] if isinstance(emp_val, (list, tuple)) else emp_val
        emp_name = emp_val[1] if isinstance(emp_val, (list, tuple)) else str(emp_val)

        hours = g.get('unit_amount', 0) or 0
        cost = abs(g.get('amount', 0) or 0)

        employees.append({
            'id': emp_id,
            'name': emp_name,
            'hours': hours,
            'hours_fmt': format_duration(hours),
            'cost': cost,
        })
        total_hours += hours
        total_cost += cost

    employees.sort(key=lambda x: x['hours'], reverse=True)

    # Get per-job breakdown for each employee
    for emp in employees:
        try:
            job_groups = odoo.read_group(
                'account.analytic.line',
                domain + [('employee_id', '=', emp['id'])],
                ['account_id', 'unit_amount', 'amount'],
                ['account_id'],
            )
            emp['jobs'] = []
            for jg in job_groups:
                acct_val = jg.get('account_id')
                if not acct_val:
                    continue
                emp['jobs'].append({
                    'name': acct_val[1] if isinstance(acct_val, (list, tuple)) else str(acct_val),
                    'hours': jg.get('unit_amount', 0) or 0,
                    'hours_fmt': format_duration(jg.get('unit_amount', 0) or 0),
                    'cost': abs(jg.get('amount', 0) or 0),
                })
            emp['jobs'].sort(key=lambda x: x['hours'], reverse=True)
        except Exception:
            emp['jobs'] = []

    return {
        'employees': employees,
        'total_hours': total_hours,
        'total_hours_fmt': format_duration(total_hours),
        'total_cost': total_cost,
        'employee_count': len(employees),
    }


def get_wip_data(odoo):
    """Work in Progress report: costs incurred vs revenue billed per job.

    For each active job:
    - Costs incurred: sum of analytic line amounts
    - Revenue billed: sum of posted customer invoice amounts
    - Over/under billing = billed - costs
    """
    from jobcosting.services import get_account_invoices

    field_map = get_custom_field_map(odoo)
    status_field, status_options = resolve_status_field(odoo)
    status_sel_map = dict(status_options) if status_options else {}

    # Resolve sales price field
    sales_tech, _ = resolve_field(field_map, 'Current Sales Price')

    fields = ['id', 'name', 'code']
    if sales_tech:
        fields.append(sales_tech)
    if status_field:
        fields.append(status_field)

    accounts = odoo.search_read(
        'account.analytic.account', [],
        fields=fields,
        order='code asc',
    )

    # Batch get costs from analytic lines
    cost_by_account = {}
    try:
        cost_groups = odoo.read_group(
            'account.analytic.line', [],
            ['account_id', 'amount'],
            ['account_id'],
        )
        for g in cost_groups:
            acct_val = g.get('account_id')
            acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
            cost_by_account[acct_id] = abs(g.get('amount', 0) or 0)
    except Exception:
        pass

    jobs = []
    totals = {'contract_value': 0, 'costs': 0, 'billed': 0}

    for acct in accounts:
        raw_status = acct.get(status_field, '') if status_field else ''
        if isinstance(raw_status, (list, tuple)):
            status = raw_status[1] if len(raw_status) >= 2 else ''
        else:
            status = status_sel_map.get(raw_status, str(raw_status)) if raw_status else ''

        contract_value = float(acct.get(sales_tech, 0) or 0) if sales_tech else 0
        costs_incurred = cost_by_account.get(acct['id'], 0)

        # Get billed amount from invoices
        billed = 0
        try:
            invoices, _ = get_account_invoices(odoo, acct['id'])
            for inv in invoices:
                if inv.get('state') == 'posted':
                    billed += inv.get('amount_total', 0) or 0
        except Exception:
            pass

        over_under = billed - costs_incurred
        pct_complete = (costs_incurred / contract_value * 100) if contract_value > 0 else 0

        jobs.append({
            'id': acct['id'],
            'code': acct.get('code', ''),
            'name': acct.get('name', ''),
            'status': status,
            'contract_value': contract_value,
            'costs_incurred': costs_incurred,
            'billed': billed,
            'over_under': over_under,
            'pct_complete': pct_complete,
        })

        totals['contract_value'] += contract_value
        totals['costs'] += costs_incurred
        totals['billed'] += billed

    totals['over_under'] = totals['billed'] - totals['costs']

    return {'jobs': jobs, 'totals': totals}


def get_job_comparison_data(odoo, job_ids):
    """Compare 2-3 jobs side by side with key metrics."""
    field_map = get_custom_field_map(odoo)

    # Resolve fields we need
    compare_fields = {
        'Sales Price': 'Current Sales Price',
        'Total Expenses': 'Total Expenses',
        'Current Margin': 'Current Margin',
        'Actual Profit': 'Actual Profit',
        'Margin %': 'Actual Margin',
        'Square Footage': 'Square Footage',
        'Date Started': 'Date Started',
        'Date Completed': 'Date Completed',
    }

    field_names = ['id', 'name', 'code']
    label_to_tech = {}
    for display, odoo_label in compare_fields.items():
        tech, info = resolve_field(field_map, odoo_label)
        if tech:
            label_to_tech[display] = (tech, info)
            field_names.append(tech)

    accounts = odoo.search_read(
        'account.analytic.account',
        [('id', 'in', job_ids)],
        fields=field_names,
    )

    # Get line costs per job
    cost_by_account = {}
    try:
        cost_groups = odoo.read_group(
            'account.analytic.line',
            [('account_id', 'in', job_ids)],
            ['account_id', 'amount', 'unit_amount'],
            ['account_id'],
        )
        for g in cost_groups:
            acct_val = g.get('account_id')
            acct_id = acct_val[0] if isinstance(acct_val, (list, tuple)) else acct_val
            cost_by_account[acct_id] = {
                'cost': abs(g.get('amount', 0) or 0),
                'hours': g.get('unit_amount', 0) or 0,
            }
    except Exception:
        pass

    jobs = []
    for acct in accounts:
        metrics = []
        sq_ft = 0

        for display, (tech, info) in label_to_tech.items():
            raw = acct.get(tech, 0)
            val = float(raw) if isinstance(raw, (int, float)) else 0
            formatted = format_odoo_value(raw, info)
            metrics.append({'label': display, 'value': val, 'display': formatted})
            if display == 'Square Footage':
                sq_ft = val

        line_data = cost_by_account.get(acct['id'], {})
        line_cost = line_data.get('cost', 0)
        line_hours = line_data.get('hours', 0)

        sales = float(acct.get(label_to_tech.get('Sales Price', ('', None))[0], 0) or 0) if 'Sales Price' in label_to_tech else 0
        cost_per_sqft = (line_cost / sq_ft) if sq_ft > 0 else 0
        revenue_per_sqft = (sales / sq_ft) if sq_ft > 0 else 0

        metrics.append({'label': 'Total Line Hours', 'value': line_hours,
                        'display': format_duration(line_hours)})
        metrics.append({'label': 'Total Line Cost', 'value': line_cost,
                        'display': f'{line_cost:,.2f}'})
        metrics.append({'label': 'Cost per Sq Ft', 'value': cost_per_sqft,
                        'display': f'{cost_per_sqft:,.2f}'})
        metrics.append({'label': 'Revenue per Sq Ft', 'value': revenue_per_sqft,
                        'display': f'{revenue_per_sqft:,.2f}'})

        jobs.append({
            'id': acct['id'],
            'code': acct.get('code', ''),
            'name': acct.get('name', ''),
            'metrics': metrics,
        })

    # Build comparison rows (same metric across all jobs)
    metric_labels = jobs[0]['metrics'] if jobs else []
    rows = []
    for i, m in enumerate(metric_labels):
        row = {'label': m['label'], 'values': []}
        for job in jobs:
            if i < len(job['metrics']):
                row['values'].append(job['metrics'][i])
            else:
                row['values'].append({'value': 0, 'display': '-'})
        rows.append(row)

    return {'jobs': jobs, 'rows': rows}
