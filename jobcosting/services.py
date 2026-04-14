from common.utils import date_to_odoo, odoo_to_date, format_duration, format_many2one
from jobcosting.field_mapping import (
    resolve_dashboard_columns, resolve_detail_sections, format_odoo_value,
    resolve_status_field,
)


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
    """Get analytic items with filters."""
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

    # Get unique status values for the filter bar
    status_values = sorted(set(j['status'] for j in formatted_jobs if j['status']))

    return {
        'columns': [(c[0], c[2]) for c in columns],  # (label, sort_type)
        'jobs': formatted_jobs,
        'status_options': status_values,
        'default_status': 'In Progress',
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

    # Analytic lines for this account
    lines = get_analytic_lines(odoo, account_id=account_id, limit=50)

    # Invoices and bills
    invoices, bills = get_account_invoices(odoo, account_id)

    return {
        'account': account,
        'sections': rendered_sections,
        'lines': lines,
        'invoices': invoices,
        'bills': bills,
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
            'payment_state',
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


def get_account_invoices(odoo, account_id):
    """Fetch invoices and bills linked to an analytic account.

    Tries multiple strategies since Odoo versions handle the link differently:
    1. analytic_distribution JSON field on account.move.line (Odoo 17+)
    2. analytic_account_id on account.move.line (older Odoo / some configs)
    3. Via analytic lines that have move_line_id

    Returns (invoices, bills) as two separate lists.
    """
    # Strategy 1: analytic_distribution ilike search (Odoo 17)
    try:
        move_lines = odoo.search_read(
            'account.move.line',
            [('analytic_distribution', 'ilike', str(account_id))],
            fields=['move_id', 'analytic_distribution'],
            limit=500,
        )

        move_ids = set()
        for ml in move_lines:
            dist = ml.get('analytic_distribution')
            if isinstance(dist, dict) and str(account_id) in dist:
                move_val = ml.get('move_id')
                if isinstance(move_val, (list, tuple)):
                    move_ids.add(move_val[0])
                elif move_val:
                    move_ids.add(move_val)

        if move_ids:
            return _fetch_moves_by_ids(odoo, move_ids)
    except Exception:
        pass

    # Strategy 2: analytic_account_id direct field on move lines
    try:
        move_lines = odoo.search_read(
            'account.move.line',
            [('analytic_account_id', '=', account_id)],
            fields=['move_id'],
            limit=500,
        )

        move_ids = set()
        for ml in move_lines:
            move_val = ml.get('move_id')
            if isinstance(move_val, (list, tuple)):
                move_ids.add(move_val[0])
            elif move_val:
                move_ids.add(move_val)

        if move_ids:
            return _fetch_moves_by_ids(odoo, move_ids)
    except Exception:
        pass

    # Strategy 3: via analytic lines → move_line_id → move_id
    try:
        # Try move_id first (some Odoo versions have it directly)
        a_lines = odoo.safe_search_read(
            'account.analytic.line',
            [('account_id', '=', account_id)],
            fields=['move_id', 'move_line_id'],
            limit=500,
        )

        move_ids = set()
        move_line_ids = []

        for l in a_lines:
            # Direct move_id on analytic line
            mv = l.get('move_id')
            if isinstance(mv, (list, tuple)) and mv[0]:
                move_ids.add(mv[0])
            elif mv and mv is not True:
                move_ids.add(mv)

            # Or via move_line_id
            ml = l.get('move_line_id')
            if isinstance(ml, (list, tuple)) and ml[0]:
                move_line_ids.append(ml[0])
            elif ml and ml is not True:
                move_line_ids.append(ml)

        # Get moves from move_line_ids
        if move_line_ids and not move_ids:
            aml_records = odoo.search_read(
                'account.move.line',
                [('id', 'in', move_line_ids)],
                fields=['move_id'],
            )
            for r in aml_records:
                mv = r.get('move_id')
                if isinstance(mv, (list, tuple)):
                    move_ids.add(mv[0])
                elif mv:
                    move_ids.add(mv)

        if move_ids:
            return _fetch_moves_by_ids(odoo, move_ids)
    except Exception:
        pass

    return [], []
