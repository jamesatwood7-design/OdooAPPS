import logging

from common.utils import date_to_odoo, odoo_to_date, format_duration, format_many2one
from jobcosting.field_mapping import (
    resolve_dashboard_columns, resolve_detail_sections, format_odoo_value,
    resolve_status_field, get_custom_field_map, resolve_field,
)

logger = logging.getLogger(__name__)

PO_OPEN_STATES = ('purchase', 'done')


def _distribution_pct(account_id, dist):
    """Return the percentage this analytic account gets from a distribution dict.

    Handles Odoo 17 compound keys used when Analytic Plans are enabled —
    e.g. ``{"24,42": 100.0}`` means this line is tagged to account 24 AND
    account 42 simultaneously, each receiving 100% of the line's value.
    Each comma-separated part is matched independently so a prefix like
    "24" does not false-match "242" or "24,42"-as-a-whole.
    """
    if not isinstance(dist, dict):
        return 0.0
    key = str(account_id)
    total = 0.0
    for compound_key, pct in dist.items():
        parts = [part.strip() for part in str(compound_key).split(',')]
        if key not in parts:
            continue
        try:
            total += float(pct)
        except (TypeError, ValueError):
            continue
    return total


def get_analytic_accounts(odoo, domain=None):
    """List analytic accounts with balances."""
    if domain is None:
        domain = []
    return odoo.safe_search_read(
        'account.analytic.account', domain,
        fields=['id', 'name', 'code', 'balance', 'debit', 'credit'],
        order='name asc',
    )


def get_projects(odoo):
    """List all projects with their analytic account links."""
    return odoo.safe_search_read(
        'project.project', [],
        fields=[
            'id', 'name', 'analytic_account_id',
            'date_start', 'date', 'task_count',
        ],
        order='name asc',
    )


def get_project(odoo, project_id):
    """Get a single project by ID."""
    records = odoo.safe_search_read(
        'project.project',
        [('id', '=', project_id)],
        fields=[
            'id', 'name', 'analytic_account_id',
            'date_start', 'date', 'task_count',
        ],
    )
    return records[0] if records else None


def get_tasks_for_project(odoo, project_id):
    """Get all tasks for a project with planned/effective hours."""
    return odoo.safe_search_read(
        'project.task',
        [('project_id', '=', project_id)],
        fields=[
            'id', 'name', 'planned_hours', 'effective_hours',
            'remaining_hours', 'stage_id',
        ],
        order='name asc',
    )


def get_analytic_lines(odoo, account_id=None, project_id=None,
                       date_from=None, date_to=None, limit=100):
    """Backwards-compatible single-call fetch of analytic items.

    Kept for tests and callers that don't need pagination. The Entries
    list page uses get_analytic_lines_paginated() instead.
    """
    domain = []
    if account_id:
        domain.append(('account_id', '=', account_id))
    if project_id:
        domain.append(('project_id', '=', project_id))
    if date_from:
        domain.append(('date', '>=', date_to_odoo(date_from)))
    if date_to:
        domain.append(('date', '<=', date_to_odoo(date_to)))

    records = odoo.safe_search_read(
        'account.analytic.line', domain,
        fields=[
            'id', 'name', 'date', 'amount', 'unit_amount',
            'employee_id', 'project_id', 'task_id', 'account_id',
        ],
        order='date desc',
        limit=limit,
    )
    for rec in records:
        rec['unit_amount_fmt'] = format_duration(rec.get('unit_amount'))
        rec['date_obj'] = odoo_to_date(rec.get('date'))
    return records


def get_analytic_lines_paginated(odoo, domain=None, order=None,
                                 offset=0, limit=50):
    """Paginated analytic items for the Entries list page.

    Returns (records, domain_used). The caller feeds domain_used to
    compute_list_totals() for the footer totals.
    """
    full_domain = list(domain or [])
    records = odoo.safe_search_read(
        'account.analytic.line', full_domain,
        fields=[
            'id', 'name', 'date', 'amount', 'unit_amount',
            'employee_id', 'project_id', 'task_id', 'account_id',
        ],
        order=order or 'date desc',
        offset=offset,
        limit=limit,
    )
    for rec in records:
        rec['unit_amount_fmt'] = format_duration(rec.get('unit_amount'))
        rec['date_obj'] = odoo_to_date(rec.get('date'))
    return records, full_domain


def get_employees(odoo):
    """Get employees for dropdown selections."""
    return odoo.safe_search_read(
        'hr.employee', [],
        fields=['id', 'name'],
        order='name asc',
    )


def create_time_entry(odoo, account_id, project_id, task_id, employee_id,
                      entry_date, hours, description, hourly_rate=0):
    """Create an analytic line for a time entry.

    Amount is calculated as -(hours * hourly_rate) following Odoo convention
    where costs are negative.
    """
    amount = -(hours * hourly_rate) if hourly_rate else 0

    values = {
        'name': description,
        'account_id': account_id,
        'date': date_to_odoo(entry_date),
        'unit_amount': hours,
        'amount': amount,
    }

    if project_id:
        values['project_id'] = project_id
    if task_id:
        values['task_id'] = task_id
    if employee_id:
        values['employee_id'] = employee_id

    return odoo.create('account.analytic.line', values)


def create_expense_entry(odoo, account_id, entry_date, amount, description,
                         project_id=None):
    """Create an analytic line for an expense entry."""
    values = {
        'name': description,
        'account_id': account_id,
        'date': date_to_odoo(entry_date),
        'amount': -abs(amount),  # costs are negative in Odoo
    }

    if project_id:
        values['project_id'] = project_id

    return odoo.create('account.analytic.line', values)


def get_project_detail(odoo, project_id):
    """Get full project detail: project info, tasks, and recent analytic lines."""
    project = get_project(odoo, project_id)
    if not project:
        return None

    tasks = get_tasks_for_project(odoo, project_id)
    lines = get_analytic_lines(odoo, project_id=project_id, limit=50)

    total_budgeted = sum(t.get('planned_hours', 0) or 0 for t in tasks)
    total_actual = sum(t.get('effective_hours', 0) or 0 for t in tasks)
    total_cost = sum(abs(l.get('amount', 0) or 0) for l in lines)

    variance_hours = total_budgeted - total_actual
    variance_pct = ((variance_hours / total_budgeted) * 100) if total_budgeted > 0 else 0

    return {
        'project': project,
        'tasks': tasks,
        'lines': lines,
        'totals': {
            'budgeted_hours': total_budgeted,
            'budgeted_hours_fmt': format_duration(total_budgeted),
            'actual_hours': total_actual,
            'actual_hours_fmt': format_duration(total_actual),
            'variance_hours': variance_hours,
            'variance_hours_fmt': format_duration(abs(variance_hours)),
            'variance_sign': 'under' if variance_hours >= 0 else 'over',
            'variance_pct': abs(variance_pct),
            'total_cost': total_cost,
        },
    }


def get_job_cost_report(odoo, project_id):
    """Generate a budget vs actual report for a project.

    Returns per-task breakdown and totals.
    """
    project = get_project(odoo, project_id)
    if not project:
        return None

    tasks = get_tasks_for_project(odoo, project_id)

    # Get analytic lines grouped by task using read_group for efficiency
    try:
        grouped = odoo.read_group(
            'account.analytic.line',
            [('project_id', '=', project_id)],
            ['task_id', 'unit_amount', 'amount'],
            ['task_id'],
        )
        lines_by_task = {}
        for g in grouped:
            task_val = g.get('task_id')
            task_id = task_val[0] if isinstance(task_val, (list, tuple)) else task_val
            lines_by_task[task_id] = {
                'actual_hours': g.get('unit_amount', 0) or 0,
                'actual_cost': abs(g.get('amount', 0) or 0),
                'count': g.get('__count', 0),
            }
    except Exception:
        # Fallback: fetch all lines and aggregate in Python
        lines = get_analytic_lines(odoo, project_id=project_id, limit=None)
        lines_by_task = {}
        for l in lines:
            task_val = l.get('task_id')
            task_id = task_val[0] if isinstance(task_val, (list, tuple)) else (task_val or 0)
            if task_id not in lines_by_task:
                lines_by_task[task_id] = {'actual_hours': 0, 'actual_cost': 0, 'count': 0}
            lines_by_task[task_id]['actual_hours'] += l.get('unit_amount', 0) or 0
            lines_by_task[task_id]['actual_cost'] += abs(l.get('amount', 0) or 0)
            lines_by_task[task_id]['count'] += 1

    # Build per-task report rows
    task_rows = []
    total_budgeted = 0
    total_actual_hours = 0
    total_actual_cost = 0

    for task in tasks:
        budgeted = task.get('planned_hours', 0) or 0
        task_data = lines_by_task.get(task['id'], {})
        actual_hours = task_data.get('actual_hours', 0)
        actual_cost = task_data.get('actual_cost', 0)

        variance = budgeted - actual_hours
        total_budgeted += budgeted
        total_actual_hours += actual_hours
        total_actual_cost += actual_cost

        task_rows.append({
            'id': task['id'],
            'name': task['name'],
            'stage': task.get('stage_id', [None, 'N/A']),
            'budgeted_hours': budgeted,
            'budgeted_hours_fmt': format_duration(budgeted),
            'actual_hours': actual_hours,
            'actual_hours_fmt': format_duration(actual_hours),
            'variance_hours': variance,
            'variance_hours_fmt': format_duration(abs(variance)),
            'variance_sign': 'under' if variance >= 0 else 'over',
            'actual_cost': actual_cost,
            'entry_count': task_data.get('count', 0),
        })

    # Handle unassigned lines (no task)
    unassigned = lines_by_task.get(0, lines_by_task.get(False, {}))
    if unassigned:
        task_rows.append({
            'id': None,
            'name': '(Unassigned)',
            'stage': [None, '-'],
            'budgeted_hours': 0,
            'budgeted_hours_fmt': format_duration(0),
            'actual_hours': unassigned.get('actual_hours', 0),
            'actual_hours_fmt': format_duration(unassigned.get('actual_hours', 0)),
            'variance_hours': -unassigned.get('actual_hours', 0),
            'variance_hours_fmt': format_duration(unassigned.get('actual_hours', 0)),
            'variance_sign': 'over',
            'actual_cost': unassigned.get('actual_cost', 0),
            'entry_count': unassigned.get('count', 0),
        })
        total_actual_hours += unassigned.get('actual_hours', 0)
        total_actual_cost += unassigned.get('actual_cost', 0)

    total_variance = total_budgeted - total_actual_hours

    return {
        'project': project,
        'task_rows': task_rows,
        'totals': {
            'budgeted_hours': total_budgeted,
            'budgeted_hours_fmt': format_duration(total_budgeted),
            'actual_hours': total_actual_hours,
            'actual_hours_fmt': format_duration(total_actual_hours),
            'variance_hours': total_variance,
            'variance_hours_fmt': format_duration(abs(total_variance)),
            'variance_sign': 'under' if total_variance >= 0 else 'over',
            'variance_pct': abs((total_variance / total_budgeted) * 100) if total_budgeted > 0 else 0,
            'total_cost': total_actual_cost,
        },
    }


def get_cost_summary_by_project(odoo):
    """Summary across all projects using batch queries.

    Uses only 3 API calls total (projects + task hours grouped + costs grouped)
    instead of 2 calls per project, which was causing timeouts on cloud Odoo.
    """
    projects = get_projects(odoo)
    if not projects:
        return []

    project_ids = [p['id'] for p in projects]

    # Batch: get planned + effective hours grouped by project (1 API call)
    hours_by_project = {}
    try:
        task_groups = odoo.read_group(
            'project.task',
            [('project_id', 'in', project_ids)],
            ['project_id', 'planned_hours', 'effective_hours'],
            ['project_id'],
        )
        for g in task_groups:
            proj_val = g.get('project_id')
            proj_id = proj_val[0] if isinstance(proj_val, (list, tuple)) else proj_val
            hours_by_project[proj_id] = {
                'budgeted': g.get('planned_hours', 0) or 0,
                'actual': g.get('effective_hours', 0) or 0,
            }
    except Exception:
        pass

    # Batch: get total cost grouped by project (1 API call)
    cost_by_project = {}
    try:
        cost_groups = odoo.read_group(
            'account.analytic.line',
            [('project_id', 'in', project_ids)],
            ['project_id', 'amount'],
            ['project_id'],
        )
        for g in cost_groups:
            proj_val = g.get('project_id')
            proj_id = proj_val[0] if isinstance(proj_val, (list, tuple)) else proj_val
            cost_by_project[proj_id] = abs(g.get('amount', 0) or 0)
    except Exception:
        pass

    summaries = []
    for proj in projects:
        hours = hours_by_project.get(proj['id'], {})
        budgeted = hours.get('budgeted', 0)
        actual = hours.get('actual', 0)
        total_cost = cost_by_project.get(proj['id'], 0)
        variance = budgeted - actual

        summaries.append({
            'project': proj,
            'budgeted_hours': budgeted,
            'budgeted_hours_fmt': format_duration(budgeted),
            'actual_hours': actual,
            'actual_hours_fmt': format_duration(actual),
            'variance_hours': variance,
            'variance_sign': 'under' if variance >= 0 else 'over',
            'total_cost': total_cost,
        })

    return summaries


# ---------------------------------------------------------------------------
# Custom Job Costing (analytic-account-centric)
# ---------------------------------------------------------------------------

def get_job_dashboard_data(odoo):
    """Fetch all analytic accounts with custom fields for the jobs dashboard.

    Uses dynamic field discovery - only 2 API calls total
    (1 cached fields_get + 1 search_read).
    """
    columns, field_names = resolve_dashboard_columns(odoo)

    # Discover the status field and its options
    status_field, status_options = resolve_status_field(odoo)
    if status_field and status_field not in field_names:
        field_names.append(status_field)

    jobs = odoo.search_read(
        'account.analytic.account', [],
        fields=field_names,
        order='code asc',
    )

    # Build the selection label map for the status field
    status_sel_map = dict(status_options) if status_options else {}

    # Pre-format values for the template
    formatted_jobs = []
    for job in jobs:
        # Get status value for filtering
        raw_status = job.get(status_field, '') if status_field else ''
        if isinstance(raw_status, (list, tuple)):
            status_val = raw_status[1] if len(raw_status) >= 2 else ''
        else:
            status_val = status_sel_map.get(raw_status, str(raw_status)) if raw_status else ''

        row = {'id': job['id'], 'status': status_val, 'cells': []}
        for display_label, tech_name, sort_type, field_info in columns:
            raw_value = job.get(tech_name, '')
            formatted = format_odoo_value(raw_value, field_info)
            # Keep raw value for sorting
            if isinstance(raw_value, (list, tuple)):
                sort_val = raw_value[1] if len(raw_value) >= 2 else ''
            else:
                sort_val = raw_value if raw_value is not None and raw_value is not False else ''
            row['cells'].append({
                'label': display_label,
                'display': formatted,
                'raw': sort_val,
                'sort_type': sort_type,
            })
        formatted_jobs.append(row)

    from collections import Counter
    status_counts = Counter(j['status'] for j in formatted_jobs if j['status'])
    status_values = sorted(status_counts.keys())

    return {
        'columns': [(c[0], c[2]) for c in columns],
        'jobs': formatted_jobs,
        'status_options': status_values,
        'status_counts': dict(status_counts),
        'default_status': 'In Progress',
    }


def _fetch_orders_by_ids(odoo, model, order_ids):
    """Fetch sale.order or purchase.order records by IDs."""
    if not order_ids:
        return []
    orders = odoo.safe_search_read(
        model,
        [('id', 'in', list(order_ids))],
        fields=['id', 'name', 'partner_id', 'date_order', 'amount_total',
                'amount_untaxed', 'state', 'invoice_status'],
        order='date_order asc',
    )
    for o in orders:
        o['partner_name'] = format_many2one(o.get('partner_id'))
        o['display_date'] = o.get('date_order', '')
    return orders


def _find_orders_via_analytic_distribution(odoo, line_model, account_id):
    """Find order IDs via analytic_distribution on order lines (no state filter)."""
    try:
        lines = _search_lines_by_analytic(
            odoo, line_model, account_id,
            fields=['order_id', 'analytic_distribution'],
        )
    except Exception as exc:
        logger.warning(
            '%s lookup via analytic_distribution failed for account_id=%s: %s',
            line_model, account_id, exc,
        )
        return set()

    order_ids = set()
    for line in lines:
        if _distribution_pct(account_id, line.get('analytic_distribution')) <= 0:
            continue
        oid = line.get('order_id')
        if isinstance(oid, (list, tuple)):
            order_ids.add(oid[0])
        elif oid:
            order_ids.add(oid)
    return order_ids


def _find_orders_via_invoices(odoo, moves, order_model):
    """Trace back from invoices/bills to their source orders via invoice_origin."""
    order_names = set()
    for move in moves:
        origin = move.get('invoice_origin') or move.get('ref') or ''
        if origin:
            # invoice_origin can contain comma-separated SO/PO names
            for name in origin.split(','):
                name = name.strip()
                if name:
                    order_names.add(name)

    if not order_names:
        return set()

    try:
        # Search orders by name
        domain = ['|'] * (len(order_names) - 1) + [
            ('name', '=', name) for name in order_names
        ]
        orders = odoo.search(order_model, domain, limit=100)
        return set(orders)
    except Exception:
        return set()


def get_sales_orders(odoo, account_id, invoices=None):
    """Get Sales Orders linked to an analytic account.

    Tries multiple strategies:
    1. analytic_distribution on sale.order.line
    2. Trace back from customer invoices via invoice_origin
    3. analytic_account_id on sale.order.line (older Odoo)
    """
    order_ids = set()

    # Strategy 1: analytic_distribution on SO lines
    order_ids = _find_orders_via_analytic_distribution(
        odoo, 'sale.order.line', account_id
    )

    # Strategy 2: trace from invoices
    if not order_ids and invoices:
        order_ids = _find_orders_via_invoices(odoo, invoices, 'sale.order')

    return _fetch_orders_by_ids(odoo, 'sale.order', order_ids)


def _search_lines_by_analytic(odoo, model, account_id, fields):
    """Fetch `model` lines tagged to an analytic account.

    Primary: `distribution_analytic_account_ids` Many2many — the canonical
    searchable field added by Odoo 17's analytic_mixin. Every line model
    (purchase.order.line, account.move.line, sale.order.line) inherits it.

    Fallback: `analytic_distribution` ilike — kept for installs that don't
    expose the Many2many (older 17 backports, custom strippings).
    """
    try:
        return odoo.search_read(
            model,
            [('distribution_analytic_account_ids', 'in', [account_id])],
            fields=fields,
            limit=2000,
        )
    except Exception as exc:
        logger.warning(
            '%s search via distribution_analytic_account_ids failed for '
            'account_id=%s, falling back to analytic_distribution ilike: %s',
            model, account_id, exc,
        )
        return odoo.search_read(
            model,
            [('analytic_distribution', 'ilike', str(account_id))],
            fields=fields,
            limit=2000,
        )


def _po_lines_for_analytic(odoo, account_id):
    """Open PO lines tagged to this analytic account, with attribution.

    Two-phase lookup to stay resilient against API-user permission gaps:
      1. Scan `purchase.order.line` matched by `analytic_distribution ilike`.
      2. Batch-fetch parent PO states and drop lines whose order isn't in
         PO_OPEN_STATES (('purchase','done')).

    Each returned dict adds:
      - distribution_pct  (0-100)
      - attributed_amount (price_subtotal * pct/100)
      - committed_amount  ((product_qty - qty_invoiced) * price_unit * pct/100)

    `qty_invoiced` is financial exposure (what we still owe the vendor).
    See docs/decisions/odoo-cost-data-layers.md.
    """
    raw_lines = _search_lines_by_analytic(
        odoo, 'purchase.order.line', account_id,
        fields=['id', 'order_id', 'product_id', 'name',
                'product_qty', 'qty_invoiced', 'price_unit',
                'price_subtotal', 'analytic_distribution'],
    )

    matched = []
    order_ids = set()
    for line in raw_lines:
        dist = line.get('analytic_distribution')
        pct_value = _distribution_pct(account_id, dist)
        if pct_value <= 0:
            continue
        order_raw = line.get('order_id')
        order_pk = order_raw[0] if isinstance(order_raw, (list, tuple)) else order_raw
        if not order_pk:
            continue
        pct_share = pct_value / 100.0
        qty_open = max(
            0.0,
            (line.get('product_qty') or 0.0) - (line.get('qty_invoiced') or 0.0),
        )
        line['order_pk'] = order_pk
        line['distribution_pct'] = pct_value
        line['attributed_amount'] = (line.get('price_subtotal') or 0.0) * pct_share
        line['committed_amount'] = qty_open * (line.get('price_unit') or 0.0) * pct_share
        order_ids.add(order_pk)
        matched.append(line)

    if not matched:
        if raw_lines:
            logger.warning(
                'PO line search for account_id=%s returned %d rows but none '
                'matched after distribution verification; sample keys=%s',
                account_id, len(raw_lines),
                [list((rl.get('analytic_distribution') or {}).keys())
                 for rl in raw_lines[:3]],
            )
        else:
            logger.info(
                'PO line search for account_id=%s returned 0 rows. The account '
                'may not appear in any purchase.order.line.analytic_distribution. '
                'Hit /jobcosting/debug/analytic/%s to inspect.',
                account_id, account_id,
            )
        return []

    state_rows = odoo.search_read(
        'purchase.order',
        [('id', 'in', list(order_ids))],
        fields=['id', 'state'],
    )
    open_ids = {r['id'] for r in state_rows if r.get('state') in PO_OPEN_STATES}
    return [line for line in matched if line['order_pk'] in open_ids]


def _bill_lines_for_analytic(odoo, account_id):
    """Posted vendor-bill (and refund) lines tagged to this analytic, with attribution.

    Two-phase lookup: line scan by analytic_distribution first, then batch
    fetch of parent `account.move` records to filter to posted vendor moves
    and mark refund lines.

    Each returned dict adds:
      - distribution_pct  (0-100)
      - attributed_amount (price_subtotal * pct/100)
      - is_refund         (True for in_refund moves)
      - move_pk           (the parent move id)
    """
    raw_lines = _search_lines_by_analytic(
        odoo, 'account.move.line', account_id,
        fields=['id', 'move_id', 'name', 'price_subtotal', 'analytic_distribution'],
    )

    candidates = []
    move_ids = set()
    for line in raw_lines:
        dist = line.get('analytic_distribution')
        pct_value = _distribution_pct(account_id, dist)
        if pct_value <= 0:
            continue
        mv = line.get('move_id')
        move_pk = mv[0] if isinstance(mv, (list, tuple)) else mv
        if not move_pk:
            continue
        pct_share = pct_value / 100.0
        line['move_pk'] = move_pk
        line['distribution_pct'] = pct_value
        line['attributed_amount'] = (line.get('price_subtotal') or 0.0) * pct_share
        move_ids.add(move_pk)
        candidates.append(line)

    if not candidates:
        if raw_lines:
            logger.warning(
                'Move line search for account_id=%s returned %d rows but none '
                'matched after distribution verification; sample keys=%s',
                account_id, len(raw_lines),
                [list((rl.get('analytic_distribution') or {}).keys())
                 for rl in raw_lines[:3]],
            )
        else:
            logger.info(
                'Move line search for account_id=%s returned 0 rows.',
                account_id,
            )
        return []

    moves = odoo.search_read(
        'account.move',
        [('id', 'in', list(move_ids))],
        fields=['id', 'move_type', 'state'],
    )
    info_by_move = {m['id']: m for m in moves}

    matched = []
    for line in candidates:
        info = info_by_move.get(line.get('move_pk')) or {}
        if info.get('state') != 'posted':
            continue
        if info.get('move_type') not in ('in_invoice', 'in_refund'):
            continue
        line['is_refund'] = info.get('move_type') == 'in_refund'
        matched.append(line)
    return matched


def get_purchase_orders(odoo, account_id, bills=None):
    """Open Purchase Orders linked to an analytic account, with attribution.

    Primary strategy: analytic_distribution on purchase.order.line, restricted
    to PO state in ('purchase','done'). Each returned PO is enriched with
    `attributed_amount` and `committed_amount` summed across its matching lines.

    Fallbacks (no attribution available): trace via invoice_origin on bills,
    legacy analytic_account_id field on PO lines.
    """
    primary_lines = []
    try:
        primary_lines = _po_lines_for_analytic(odoo, account_id)
    except Exception as exc:
        logger.warning(
            'PO line lookup via analytic_distribution failed for account_id=%s: %s',
            account_id, exc,
        )

    if primary_lines:
        sums = {}
        for line in primary_lines:
            oid_raw = line.get('order_id')
            oid = oid_raw[0] if isinstance(oid_raw, (list, tuple)) else oid_raw
            if not oid:
                continue
            slot = sums.setdefault(oid, {'attributed': 0.0, 'committed': 0.0, 'lines': 0})
            slot['attributed'] += line.get('attributed_amount', 0.0)
            slot['committed'] += line.get('committed_amount', 0.0)
            slot['lines'] += 1

        orders = _fetch_orders_by_ids(odoo, 'purchase.order', set(sums.keys()))
        for order in orders:
            slot = sums.get(order['id'], {})
            order['attributed_amount'] = slot.get('attributed', 0.0)
            order['committed_amount'] = slot.get('committed', 0.0)
            order['matched_line_count'] = slot.get('lines', 0)
        return orders

    order_ids = set()
    if bills:
        order_ids = _find_orders_via_invoices(odoo, bills, 'purchase.order')

    return _fetch_orders_by_ids(odoo, 'purchase.order', order_ids)


def get_timesheets(odoo, account_id, limit=100):
    """Get timesheet entries only (not purchase/invoice lines)."""
    records = odoo.safe_search_read(
        'account.analytic.line',
        [
            ('account_id', '=', account_id),
            ('project_id', '!=', False),
        ],
        fields=['id', 'name', 'date', 'amount', 'unit_amount',
                'employee_id', 'project_id', 'task_id'],
        order='date desc',
        limit=limit,
    )

    for rec in records:
        rec['unit_amount_fmt'] = format_duration(rec.get('unit_amount'))

    return records


def get_job_financials(odoo, account_id):
    """Compute accurate financial data from source records.

    Pulls from Sales Orders, Invoices, Bills, and Timesheets
    to compute a proper P&L instead of relying on custom fields.
    """
    # Invoices & Bills first (needed for SO/PO trace-back)
    invoices, bills = get_account_invoices(odoo, account_id)

    # Sales Orders → Contract Value (pass invoices for trace-back strategy)
    sales_orders = get_sales_orders(odoo, account_id, invoices=invoices)
    confirmed_states = ('sale', 'done')
    original_contract = 0
    change_orders = 0

    for i, so in enumerate(sales_orders):
        if so.get('state') in confirmed_states:
            amt = so.get('amount_untaxed', 0) or so.get('amount_total', 0) or 0
            if i == 0:
                original_contract = amt
            else:
                change_orders += amt

    total_contract = original_contract + change_orders

    invoice_total = sum(
        m.get('amount_total', 0) or 0
        for m in invoices if m.get('move_type') == 'out_invoice' and m.get('state') == 'posted'
    )
    credit_note_total = sum(
        m.get('amount_total', 0) or 0
        for m in invoices if m.get('move_type') == 'out_refund' and m.get('state') == 'posted'
    )
    net_invoiced = invoice_total - credit_note_total

    posted_bills = [
        m for m in bills if m.get('state') == 'posted'
    ]
    bill_total = sum(
        m.get('attributed_amount', m.get('amount_total', 0) or 0)
        for m in posted_bills if m.get('move_type') == 'in_invoice'
    )
    vendor_refund_total = sum(
        m.get('attributed_amount', m.get('amount_total', 0) or 0)
        for m in posted_bills if m.get('move_type') == 'in_refund'
    )
    net_bills = bill_total - vendor_refund_total

    # Labor cost from timesheets
    timesheets = get_timesheets(odoo, account_id, limit=None)
    labor_hours = sum(t.get('unit_amount', 0) or 0 for t in timesheets)
    labor_cost = sum(abs(t.get('amount', 0) or 0) for t in timesheets)

    purchase_orders = get_purchase_orders(odoo, account_id, bills=bills)
    committed_cost = sum(po.get('committed_amount', 0.0) or 0.0 for po in purchase_orders)

    # If a job has posted bills but produced no PO matches, that's almost
    # always a configuration regression worth surfacing in the logs.
    if posted_bills and not purchase_orders:
        logger.warning(
            'No purchase orders found for account_id=%s despite %d posted bill(s); '
            'check that purchase.order.line.analytic_distribution is readable.',
            account_id, len(posted_bills),
        )

    # Gross profit & margin track BILLED costs only — what's actually on the
    # books. Committed PO costs are surfaced separately so the team can see
    # exposure without distorting realised profitability.
    total_costs = net_bills + labor_cost
    gross_profit = total_contract - total_costs
    margin_pct = (gross_profit / total_contract * 100) if total_contract > 0 else 0
    billed_vs_costs = net_invoiced - total_costs

    # Get Square Footage for per-sqft calculations
    field_map = get_custom_field_map(odoo)
    sqft_tech, _ = resolve_field(field_map, 'Square Footage')
    sq_ft = 0
    if sqft_tech:
        acct = odoo.search_read(
            'account.analytic.account',
            [('id', '=', account_id)],
            fields=[sqft_tech],
        )
        if acct:
            sq_ft = float(acct[0].get(sqft_tech, 0) or 0)

    cost_per_sqft = (total_costs / sq_ft) if sq_ft > 0 else 0
    revenue_per_sqft = (total_contract / sq_ft) if sq_ft > 0 else 0

    return {
        'original_contract': original_contract,
        'change_orders': change_orders,
        'total_contract': total_contract,
        'invoice_total': invoice_total,
        'credit_note_total': credit_note_total,
        'net_invoiced': net_invoiced,
        'bill_total': bill_total,
        'vendor_refund_total': vendor_refund_total,
        'net_bills': net_bills,
        'labor_hours': labor_hours,
        'labor_cost': labor_cost,
        'total_costs': total_costs,
        'committed_cost': committed_cost,
        'gross_profit': gross_profit,
        'margin_pct': margin_pct,
        'billed_vs_costs': billed_vs_costs,
        'sq_ft': sq_ft,
        'cost_per_sqft': cost_per_sqft,
        'revenue_per_sqft': revenue_per_sqft,
        'sales_orders': sales_orders,
        'purchase_orders': purchase_orders,
        'invoices': invoices,
        'bills': bills,
        'timesheets': timesheets[:100],
        'labor_hours_fmt': format_duration(labor_hours),
    }


def get_billing_summary(odoo, account_id, financials=None):
    """Compute progress-billing context for a job.

    Reuses get_job_financials so the numbers match the Job Detail page.
    Pass ``financials`` if the caller already has it to avoid a double
    fetch.

    Returns:
        contract         Total contract value (sales orders in sale/done state).
        billed           Net invoiced (posted invoices minus posted credit notes).
        paid             Sum of (amount_total - amount_residual) across posted
                         customer invoices — the portion already cleared.
        outstanding      billed - paid — the AR balance on this job.
        remaining        contract - billed — the amount still left to invoice.
        progress_bill_count  Count of posted customer invoices for this job.
        customer_id / customer_name  Taken from the first sales order and
                         falling back to the first invoice. Used to pre-fill
                         the Create Progress Bill form.
    """
    if financials is None:
        financials = get_job_financials(odoo, account_id)

    contract = financials.get('total_contract', 0) or 0
    billed = financials.get('net_invoiced', 0) or 0

    posted_out_invoices = [
        m for m in financials.get('invoices', [])
        if m.get('move_type') == 'out_invoice' and m.get('state') == 'posted'
    ]
    paid = sum(
        (m.get('amount_total', 0) or 0) - (m.get('amount_residual', 0) or 0)
        for m in posted_out_invoices
    )

    # Credit notes reduce both billed and paid (Odoo applies refund payments
    # symmetrically), but for simplicity we track only customer invoices here
    # — refunds are rare on progress billing and any overcount will show up
    # clearly on the summary.

    customer_id = None
    customer_name = ''
    for so in financials.get('sales_orders', []):
        pid = so.get('partner_id')
        if pid:
            customer_id = pid[0] if isinstance(pid, (list, tuple)) else pid
            customer_name = pid[1] if isinstance(pid, (list, tuple)) else ''
            break
    if not customer_id:
        for inv in posted_out_invoices:
            pid = inv.get('partner_id')
            if pid:
                customer_id = pid[0] if isinstance(pid, (list, tuple)) else pid
                customer_name = pid[1] if isinstance(pid, (list, tuple)) else ''
                break

    return {
        'contract': contract,
        'billed': billed,
        'paid': paid,
        'outstanding': billed - paid,
        'remaining': contract - billed,
        'progress_bill_count': len(posted_out_invoices),
        'customer_id': customer_id,
        'customer_name': customer_name,
    }


def get_job_detail(odoo, account_id):
    """Fetch full detail for a single analytic account (job).

    Returns structured sections with all custom fields, plus
    analytic lines, invoices, and bills.
    """
    sections, field_names = resolve_detail_sections(odoo)

    accounts = odoo.search_read(
        'account.analytic.account',
        [('id', '=', account_id)],
        fields=field_names,
    )
    if not accounts:
        return None

    account = accounts[0]

    # Build sections with formatted values
    rendered_sections = []
    for section_name, field_defs in sections:
        fields = []
        for display_label, tech_name, field_info, display_format in field_defs:
            raw_value = account.get(tech_name, '')
            formatted = format_odoo_value(raw_value, field_info)
            fields.append({
                'label': display_label,
                'value': formatted,
                'raw_value': raw_value,
                'type': field_info.get('type', 'char') if field_info else 'char',
                'display_format': display_format,
                'technical_name': tech_name,
            })
        if fields:
            rendered_sections.append({
                'name': section_name,
                'fields': fields,
            })

    # Computed financials from source data
    financials = get_job_financials(odoo, account_id)
    billing = get_billing_summary(odoo, account_id, financials=financials)

    return {
        'account': account,
        'sections': rendered_sections,
        'financials': financials,
        'billing': billing,
        'timesheets': financials['timesheets'],
        'sales_orders': financials['sales_orders'],
        'purchase_orders': financials['purchase_orders'],
        'invoices': financials['invoices'],
        'bills': financials['bills'],
    }


def _fetch_moves_by_ids(odoo, move_ids):
    """Fetch account.move records and split into invoices and bills."""
    invoices = []
    bills = []

    if not move_ids:
        return invoices, bills

    moves = odoo.safe_search_read(
        'account.move',
        [('id', 'in', list(move_ids))],
        fields=[
            'id', 'name', 'ref', 'partner_id', 'invoice_date', 'date',
            'amount_total', 'amount_residual', 'state', 'move_type',
            'payment_state', 'invoice_origin',
        ],
        order='invoice_date desc',
    )

    for move in moves:
        move['partner_name'] = format_many2one(move.get('partner_id'))
        move['display_date'] = move.get('invoice_date') or move.get('date') or ''
        move_type = move.get('move_type', '')
        if move_type in ('out_invoice', 'out_refund'):
            invoices.append(move)
        elif move_type in ('in_invoice', 'in_refund'):
            bills.append(move)

    return invoices, bills


def _fetch_bills_for_analytic(odoo, account_id):
    """Posted vendor bills/refunds for this analytic account.

    Primary path: line-level attribution via _bill_lines_for_analytic so each
    returned bill dict carries an `attributed_amount` summed from the matching
    lines' shares. Fallback: legacy analytic_account_id on move lines.
    """
    attr_by_move = {}
    move_ids = set()

    try:
        bill_lines = _bill_lines_for_analytic(odoo, account_id)
    except Exception as exc:
        logger.warning(
            'Bill line lookup via analytic_distribution failed for account_id=%s: %s',
            account_id, exc,
        )
        bill_lines = []

    for line in bill_lines:
        mv = line.get('move_pk')
        if not mv:
            continue
        move_ids.add(mv)
        attr_by_move[mv] = attr_by_move.get(mv, 0.0) + line.get('attributed_amount', 0.0)

    if not move_ids:
        return []

    _, bills = _fetch_moves_by_ids(odoo, move_ids)
    for bill in bills:
        bill['attributed_amount'] = attr_by_move.get(bill['id'], bill.get('amount_total', 0.0))
    return bills


def _fetch_invoices_for_analytic(odoo, account_id):
    """Customer invoices/refunds linked to this analytic account."""
    move_ids = set()

    candidate_moves = set()
    try:
        move_lines = _search_lines_by_analytic(
            odoo, 'account.move.line', account_id,
            fields=['move_id', 'analytic_distribution'],
        )
        for ml in move_lines:
            if _distribution_pct(account_id, ml.get('analytic_distribution')) > 0:
                mv = ml.get('move_id')
                mv = mv[0] if isinstance(mv, (list, tuple)) else mv
                if mv:
                    candidate_moves.add(mv)
    except Exception as exc:
        logger.warning(
            'Invoice lookup via analytic_distribution failed for account_id=%s: %s',
            account_id, exc,
        )

    if candidate_moves:
        filtered = odoo.search_read(
            'account.move',
            [('id', 'in', list(candidate_moves)),
             ('move_type', 'in', ['out_invoice', 'out_refund'])],
            fields=['id'],
        )
        move_ids.update(m['id'] for m in filtered)

    if not move_ids:
        try:
            a_lines = odoo.safe_search_read(
                'account.analytic.line',
                [('account_id', '=', account_id)],
                fields=['move_id', 'move_line_id'],
                limit=500,
            )
            line_ids = []
            for line in a_lines:
                mv = line.get('move_id')
                mv = mv[0] if isinstance(mv, (list, tuple)) else mv
                if mv and mv is not True:
                    move_ids.add(mv)
                ml = line.get('move_line_id')
                ml = ml[0] if isinstance(ml, (list, tuple)) else ml
                if ml and ml is not True:
                    line_ids.append(ml)
            if line_ids and not move_ids:
                rows = odoo.search_read(
                    'account.move.line',
                    [('id', 'in', line_ids)],
                    fields=['move_id'],
                )
                for r in rows:
                    mv = r.get('move_id')
                    mv = mv[0] if isinstance(mv, (list, tuple)) else mv
                    if mv:
                        move_ids.add(mv)
        except Exception as exc:
            logger.warning(
                'Invoice fallback via analytic lines failed for account_id=%s: %s',
                account_id, exc,
            )

    if not move_ids:
        return []

    invoices, _ = _fetch_moves_by_ids(odoo, move_ids)
    return invoices


def get_account_invoices(odoo, account_id):
    """Fetch customer invoices and vendor bills linked to an analytic account.

    Bills are fetched via percentage-aware line attribution and each bill dict
    carries an `attributed_amount` key. Invoices keep the broader fallbacks.

    Returns (invoices, bills).
    """
    invoices = _fetch_invoices_for_analytic(odoo, account_id)
    bills = _fetch_bills_for_analytic(odoo, account_id)
    return invoices, bills
