from datetime import date
from flask import (
    render_template, redirect, url_for, flash, request,
    jsonify, current_app,
)
from jobcosting import bp
from jobcosting import services
from common.exceptions import OdooAPIError, OdooConnectionError
from auth.routes import odoo_user_required


@bp.route('/')
@odoo_user_required
def dashboard():
    """Redirect to the Jobs dashboard."""
    return redirect(url_for('jobcosting.jobs_dashboard'))


# ---------------------------------------------------------------------------
# Analytic Entries (still useful for viewing/creating line items)
# ---------------------------------------------------------------------------

@bp.route('/entries')
@odoo_user_required
def entries():
    """Browse analytic items with filters."""
    odoo = current_app.odoo

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
    account_list = []

    try:
        account_list = services.get_analytic_accounts(odoo)
        lines = services.get_analytic_lines(
            odoo,
            account_id=account_id,
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
        projects=[],
        accounts=account_list,
        selected_project_id=None,
        selected_account_id=account_id,
        date_from=date_from,
        date_to=date_to,
    )


@bp.route('/entries/create', methods=['GET', 'POST'])
@odoo_user_required
def create_entry():
    """Form to create a new analytic item (time or expense entry)."""
    odoo = current_app.odoo

    if request.method == 'POST':
        entry_type = request.form.get('entry_type', 'time')
        account_id = request.form.get('account_id', type=int)
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
                    odoo, account_id, None, task_id,
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
                )
                flash('Expense entry created successfully.', 'success')

            return redirect(url_for('jobcosting.entries'))

        except OdooConnectionError as e:
            flash(f'Cannot connect to Odoo: {e}', 'danger')
        except OdooAPIError as e:
            flash(f'Error creating entry: {e}', 'danger')

    # GET request - load dropdown data
    account_list = []
    employees = []

    try:
        account_list = services.get_analytic_accounts(odoo)
        employees = services.get_employees(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'jobcosting/create_entry.html',
        projects=[],
        accounts=account_list,
        employees=employees,
        today=date.today(),
    )


# ---------------------------------------------------------------------------
# Jobs views (analytic-account-centric)
# ---------------------------------------------------------------------------

@bp.route('/jobs')
@odoo_user_required
def jobs_dashboard():
    """Spreadsheet-style dashboard of all jobs (analytic accounts) with custom fields."""
    odoo = current_app.odoo

    data = {'columns': [], 'jobs': []}
    try:
        data = services.get_job_dashboard_data(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')
    except Exception as e:
        flash(f'Error loading jobs: {e}', 'danger')
        current_app.logger.exception('Error in jobs_dashboard')

    return render_template(
        'jobcosting/jobs_dashboard.html',
        columns=data.get('columns', []),
        jobs=data.get('jobs', []),
        status_options=data.get('status_options', []),
        default_status=data.get('default_status', 'In Progress'),
    )


@bp.route('/job/<int:account_id>')
@odoo_user_required
def job_detail(account_id):
    """Full detail page for a single job (analytic account)."""
    odoo = current_app.odoo

    detail = None
    try:
        detail = services.get_job_detail(odoo, account_id)
        if not detail:
            flash('Job not found.', 'warning')
            return redirect(url_for('jobcosting.jobs_dashboard'))
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
        return redirect(url_for('jobcosting.jobs_dashboard'))
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')
        return redirect(url_for('jobcosting.jobs_dashboard'))
    except Exception as e:
        flash(f'Error loading job: {e}', 'danger')
        current_app.logger.exception('Error in job_detail')
        return redirect(url_for('jobcosting.jobs_dashboard'))

    return render_template('jobcosting/job_detail.html', detail=detail)


@bp.route('/job/<int:account_id>/save', methods=['POST'])
@odoo_user_required
def job_save(account_id):
    """Save edited fields on an analytic account."""
    odoo = current_app.odoo

    try:
        data = request.get_json()
        if not data or not isinstance(data, dict):
            return jsonify({'error': 'No data provided'}), 400

        safe_values = {}
        for field_name, value in data.items():
            if field_name.startswith('x_') or field_name in ('name', 'code'):
                safe_values[field_name] = value

        if not safe_values:
            return jsonify({'error': 'No valid fields to update'}), 400

        odoo.write('account.analytic.account', [account_id], safe_values)
        return jsonify({'success': True})

    except OdooAPIError as e:
        return jsonify({'error': str(e)}), 400
    except (OdooConnectionError, Exception) as e:
        return jsonify({'error': str(e)}), 500
