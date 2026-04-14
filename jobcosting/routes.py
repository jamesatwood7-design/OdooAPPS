from datetime import date
from flask import (
    render_template, redirect, url_for, flash, request,
    jsonify, current_app,
)
from jobcosting import bp
from jobcosting import services
from common.exceptions import OdooAPIError, OdooConnectionError


@bp.route('/')
def dashboard():
    """Job costing dashboard showing projects with cost summaries."""
    odoo = current_app.odoo

    summaries = []
    try:
        summaries = services.get_cost_summary_by_project(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')
    except Exception as e:
        flash(f'Unexpected error loading projects: {e}', 'danger')
        current_app.logger.exception('Error in jobcosting dashboard')

    return render_template('jobcosting/dashboard.html', summaries=summaries)


@bp.route('/project/<int:project_id>')
def project_detail(project_id):
    """Project detail: tasks, analytic lines, budget vs actual."""
    odoo = current_app.odoo

    detail = None
    try:
        detail = services.get_project_detail(odoo, project_id)
        if not detail:
            flash('Project not found.', 'warning')
            return redirect(url_for('jobcosting.dashboard'))
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
        return redirect(url_for('jobcosting.dashboard'))
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')
        return redirect(url_for('jobcosting.dashboard'))

    return render_template('jobcosting/project_detail.html', detail=detail)


@bp.route('/accounts')
def accounts():
    """List analytic accounts with balances."""
    odoo = current_app.odoo

    account_list = []
    try:
        account_list = services.get_analytic_accounts(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template('jobcosting/accounts.html', accounts=account_list)


@bp.route('/entries')
def entries():
    """Browse analytic items with filters."""
    odoo = current_app.odoo

    project_id = request.args.get('project_id', type=int)
    account_id = request.args.get('account_id', type=int)
    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    date_from = None
    date_to = None
    if date_from_str:
        try:
            date_from = date.fromisoformat(date_from_str)
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = date.fromisoformat(date_to_str)
        except ValueError:
            pass

    lines = []
    projects = []
    account_list = []

    try:
        projects = services.get_projects(odoo)
        account_list = services.get_analytic_accounts(odoo)
        lines = services.get_analytic_lines(
            odoo,
            account_id=account_id,
            project_id=project_id,
            date_from=date_from,
            date_to=date_to,
        )
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'jobcosting/entries.html',
        lines=lines,
        projects=projects,
        accounts=account_list,
        selected_project_id=project_id,
        selected_account_id=account_id,
        date_from=date_from,
        date_to=date_to,
    )


@bp.route('/entries/create', methods=['GET', 'POST'])
def create_entry():
    """Form to create a new analytic item (time or expense entry)."""
    odoo = current_app.odoo

    if request.method == 'POST':
        entry_type = request.form.get('entry_type', 'time')
        account_id = request.form.get('account_id', type=int)
        project_id = request.form.get('project_id', type=int)
        description = request.form.get('description', '').strip()
        entry_date_str = request.form.get('entry_date', '')

        if not account_id:
            flash('Please select an analytic account.', 'warning')
            return redirect(url_for('jobcosting.create_entry'))

        if not description:
            flash('Please enter a description.', 'warning')
            return redirect(url_for('jobcosting.create_entry'))

        try:
            entry_date = date.fromisoformat(entry_date_str)
        except (ValueError, TypeError):
            entry_date = date.today()

        try:
            if entry_type == 'time':
                task_id = request.form.get('task_id', type=int)
                employee_id = request.form.get('employee_id', type=int)
                hours = request.form.get('hours', 0, type=float)
                hourly_rate = request.form.get('hourly_rate', 0, type=float)

                if hours <= 0:
                    flash('Hours must be greater than zero.', 'warning')
                    return redirect(url_for('jobcosting.create_entry'))

                services.create_time_entry(
                    odoo, account_id, project_id, task_id,
                    employee_id, entry_date, hours, description, hourly_rate,
                )
                flash('Time entry created successfully.', 'success')
            else:
                amount = request.form.get('amount', 0, type=float)
                if amount <= 0:
                    flash('Amount must be greater than zero.', 'warning')
                    return redirect(url_for('jobcosting.create_entry'))

                services.create_expense_entry(
                    odoo, account_id, entry_date, amount, description,
                    project_id=project_id,
                )
                flash('Expense entry created successfully.', 'success')

            if project_id:
                return redirect(url_for('jobcosting.project_detail', project_id=project_id))
            return redirect(url_for('jobcosting.entries'))

        except OdooConnectionError as e:
            flash(f'Cannot connect to Odoo: {e}', 'danger')
        except OdooAPIError as e:
            flash(f'Error creating entry: {e}', 'danger')

    # GET request - load dropdown data
    projects = []
    account_list = []
    employees = []

    try:
        projects = services.get_projects(odoo)
        account_list = services.get_analytic_accounts(odoo)
        employees = services.get_employees(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'jobcosting/create_entry.html',
        projects=projects,
        accounts=account_list,
        employees=employees,
        today=date.today(),
    )


@bp.route('/report')
def report_list():
    """Select a project to view its job cost report."""
    odoo = current_app.odoo

    projects = []
    try:
        projects = services.get_projects(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template('jobcosting/report_list.html', projects=projects)


@bp.route('/report/<int:project_id>')
def report(project_id):
    """Budget vs actual report for a specific project."""
    odoo = current_app.odoo

    report_data = None
    try:
        report_data = services.get_job_cost_report(odoo, project_id)
        if not report_data:
            flash('Project not found.', 'warning')
            return redirect(url_for('jobcosting.report_list'))
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
        return redirect(url_for('jobcosting.report_list'))
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')
        return redirect(url_for('jobcosting.report_list'))

    return render_template('jobcosting/report.html', report=report_data)


@bp.route('/api/tasks/<int:project_id>')
def api_tasks(project_id):
    """JSON endpoint for cascading task dropdown."""
    odoo = current_app.odoo
    try:
        tasks = services.get_tasks_for_project(odoo, project_id)
        return jsonify([
            {'id': t['id'], 'name': t['name']}
            for t in tasks
        ])
    except (OdooConnectionError, OdooAPIError) as e:
        return jsonify({'error': str(e)}), 503


@bp.route('/api/project-account/<int:project_id>')
def api_project_account(project_id):
    """JSON endpoint to get the analytic account for a project."""
    odoo = current_app.odoo
    try:
        project = services.get_project(odoo, project_id)
        if project and project.get('analytic_account_id'):
            acct = project['analytic_account_id']
            return jsonify({
                'account_id': acct[0] if isinstance(acct, (list, tuple)) else acct,
                'account_name': acct[1] if isinstance(acct, (list, tuple)) else str(acct),
            })
        return jsonify({'account_id': None, 'account_name': None})
    except (OdooConnectionError, OdooAPIError) as e:
        return jsonify({'error': str(e)}), 503
