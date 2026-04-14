from common.utils import date_to_odoo, odoo_to_date, format_duration


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
