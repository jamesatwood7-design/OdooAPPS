from datetime import date, timedelta
from flask import (
    render_template, redirect, url_for, flash, request,
    jsonify, current_app, make_response,
)
from jobcosting import bp
from jobcosting import services
from common.exceptions import OdooAPIError, OdooConnectionError
from auth.routes import odoo_user_required
from jobcosting import reports


@bp.route('/')
@odoo_user_required
def dashboard():
    """Redirect to the Jobs dashboard."""
    return redirect(url_for('jobcosting.jobs_dashboard'))


# ---------------------------------------------------------------------------
# Analytic Entries (still useful for viewing/creating line items)
# ---------------------------------------------------------------------------

from common.list_query import (
    parse_list_query, search_facet, m2o_facet, date_range_facet,
)
from common.list_totals import compute_list_totals


ENTRIES_SORT_MAP = {
    'date': 'date',
    'amount': 'amount',
    'hours': 'unit_amount',
    'name': 'name',
    'project': 'project_id',
    'employee': 'employee_id',
}


@bp.route('/entries')
@odoo_user_required
def entries():
    """Paginated analytic-items list with multi-facet filtering + totals."""
    odoo = current_app.odoo

    account_list = []
    try:
        account_list = services.get_analytic_accounts(odoo)
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    account_options = [(a['id'], a['name']) for a in account_list]

    facets = [
        search_facet('q', ['name'], placeholder='Search description…'),
        m2o_facet('account_id', 'account_id', options=account_options, label='Account'),
        date_range_facet('date_from', 'date_to', 'date'),
    ]

    query = parse_list_query(
        request.args, facets, ENTRIES_SORT_MAP,
        default_sort='date_desc',
    )

    lines = []
    totals = {'count': 0, 'sums': {'amount': 0.0, 'unit_amount': 0.0}}
    try:
        lines, full_domain = services.get_analytic_lines_paginated(
            odoo,
            domain=query['domain'],
            order=query['order'],
            offset=query['offset'],
            limit=query['limit'],
        )
        totals = compute_list_totals(
            odoo, 'account.analytic.line', full_domain,
            sum_fields=['amount', 'unit_amount'],
        )
    except OdooConnectionError as e:
        flash(f'Cannot connect to Odoo: {e}', 'danger')
    except OdooAPIError as e:
        flash(f'Odoo error: {e}', 'danger')

    return render_template(
        'jobcosting/entries.html',
        lines=lines,
        facets=facets,
        query=query,
        totals=totals,
        accounts=account_list,
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
        status_counts=data.get('status_counts', {}),
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


@bp.route('/job/<int:account_id>/progress-bill', methods=['GET', 'POST'])
@odoo_user_required
def progress_bill(account_id):
    """Create a progress-billing invoice for this job.

    GET shows the form (pre-filled with customer + billing context).
    POST validates amount & milestone, calls create_progress_bill(),
    then jumps to the resulting draft invoice so the user can review,
    attach files, and post.
    """
    from accounting import transactions

    odoo = current_app.odoo

    detail = None
    try:
        detail = services.get_job_detail(odoo, account_id)
    except Exception as e:
        flash(f'Error loading job: {e}', 'danger')
        return redirect(url_for('jobcosting.jobs_dashboard'))

    if not detail:
        flash('Job not found.', 'warning')
        return redirect(url_for('jobcosting.jobs_dashboard'))

    billing = detail['billing']

    if request.method == 'POST':
        try:
            milestone = (request.form.get('milestone') or '').strip()
            amount = request.form.get('amount', type=float) or 0.0
            invoice_date = request.form.get('invoice_date') or date.today().isoformat()
            extra_notes = request.form.get('extra_notes', '')

            if not milestone:
                flash('Milestone label is required.', 'warning')
                return redirect(request.path)
            if amount <= 0:
                flash('Amount must be greater than zero.', 'warning')
                return redirect(request.path)
            if not billing.get('customer_id'):
                flash('This job has no linked customer — set one on a sales '
                      'order first, or create the invoice manually.',
                      'danger')
                return redirect(request.path)

            move_id = transactions.create_progress_bill(
                odoo,
                partner_id=billing['customer_id'],
                analytic_id=account_id,
                milestone=milestone,
                amount=amount,
                invoice_date=invoice_date,
                contract=billing['contract'],
                previously_billed=billing['billed'],
                previously_paid=billing['paid'],
                extra_notes=extra_notes,
            )
            flash('Progress bill created as draft. Review and post when ready.',
                  'success')
            return redirect(url_for('accounting.view_move', move_id=move_id))
        except Exception as e:
            current_app.logger.exception('Error creating progress bill')
            flash(f'Error creating progress bill: {e}', 'danger')

    return render_template(
        'jobcosting/progress_bill.html',
        detail=detail,
        billing=billing,
        today=date.today().isoformat(),
        next_number=billing.get('progress_bill_count', 0) + 1,
    )


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


# ---------------------------------------------------------------------------
# Financial Reports
# ---------------------------------------------------------------------------

@bp.route('/profitability')
@odoo_user_required
def profitability():
    """Profitability dashboard with charts."""
    odoo = current_app.odoo

    data = {'jobs': [], 'totals': {}, 'top_by_revenue': [], 'problem_jobs': []}
    try:
        data = reports.get_profitability_data(odoo)
    except Exception as e:
        flash(f'Error loading profitability data: {e}', 'danger')
        current_app.logger.exception('Error in profitability')

    return render_template('jobcosting/profitability.html', data=data)


@bp.route('/employee-costs')
@odoo_user_required
def employee_costs():
    """Employee cost report with date range."""
    odoo = current_app.odoo

    date_from_str = request.args.get('date_from', '')
    date_to_str = request.args.get('date_to', '')

    date_from = None
    date_to = None

    if date_from_str:
        try:
            date_from = date_from_str
        except ValueError:
            pass
    if date_to_str:
        try:
            date_to = date_to_str
        except ValueError:
            pass

    if not date_from and not date_to:
        today = date.today()
        date_from = (today - timedelta(days=30)).isoformat()
        date_to = today.isoformat()

    data = {'employees': [], 'total_hours': 0, 'total_cost': 0}
    try:
        data = reports.get_employee_cost_data(odoo, date_from, date_to)
    except Exception as e:
        flash(f'Error loading employee cost data: {e}', 'danger')
        current_app.logger.exception('Error in employee_costs')

    return render_template(
        'jobcosting/employee_costs.html',
        data=data,
        date_from=date_from,
        date_to=date_to,
    )


@bp.route('/wip')
@odoo_user_required
def wip_report():
    """Work in Progress report."""
    odoo = current_app.odoo

    data = {'jobs': [], 'totals': {}}
    try:
        data = reports.get_wip_data(odoo)
    except Exception as e:
        flash(f'Error loading WIP data: {e}', 'danger')
        current_app.logger.exception('Error in wip_report')

    return render_template('jobcosting/wip.html', data=data)


@bp.route('/compare')
@odoo_user_required
def compare_jobs():
    """Compare 2-3 jobs side by side."""
    odoo = current_app.odoo

    job_ids_str = request.args.get('jobs', '')
    job_ids = [int(x) for x in job_ids_str.split(',') if x.strip().isdigit()]

    all_accounts = []
    data = None

    try:
        all_accounts = odoo.search_read(
            'account.analytic.account', [],
            fields=['id', 'name', 'code'],
            order='code asc',
        )
        if job_ids:
            data = reports.get_job_comparison_data(odoo, job_ids)
    except Exception as e:
        flash(f'Error: {e}', 'danger')

    return render_template(
        'jobcosting/compare.html',
        accounts=all_accounts,
        data=data,
        selected_ids=job_ids,
    )


@bp.route('/export/<report_type>')
@odoo_user_required
def export_data(report_type):
    """Export jobs data as CSV."""
    odoo = current_app.odoo

    try:
        data = services.get_job_dashboard_data(odoo)
        jobs = data.get('jobs', [])
        columns = data.get('columns', [])

        if report_type == 'csv':
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            writer.writerow([c[0] for c in columns])

            # Rows
            for job in jobs:
                row = []
                for cell in job['cells']:
                    val = cell['display']
                    if cell['sort_type'] == 'currency' and val:
                        val = f'${val}'
                    elif cell['sort_type'] == 'percent' and val:
                        val = f'{val}%'
                    row.append(val)
                writer.writerow(row)

            resp = make_response(output.getvalue())
            resp.headers['Content-Type'] = 'text/csv'
            resp.headers['Content-Disposition'] = 'attachment; filename=jobs_export.csv'
            return resp

        else:
            flash('Unsupported export format.', 'warning')
            return redirect(url_for('jobcosting.jobs_dashboard'))

    except Exception as e:
        flash(f'Export error: {e}', 'danger')
        return redirect(url_for('jobcosting.jobs_dashboard'))


@bp.route('/debug/analytic/<int:account_id>')
@odoo_user_required
def debug_analytic(account_id):
    """Diagnostic: dump the analytic account + raw PO/bill line samples
    so we can see exactly how Odoo serialises analytic_distribution for
    this install. Used to debug empty PO/Bills tabs.
    """
    odoo = current_app.odoo
    out = {'account_id': account_id}

    try:
        acct = odoo.search_read(
            'account.analytic.account',
            [('id', '=', account_id)],
            fields=['id', 'name', 'code', 'plan_id', 'partner_id'],
        )
        out['account'] = acct[0] if acct else None
    except Exception as e:
        out['account_error'] = str(e)

    # Find the project linked to this analytic (or any analytic that
    # shares a name with this one). This helps identify multi-plan setups.
    try:
        out['projects_linked_here'] = odoo.search_read(
            'project.project',
            [('analytic_account_id', '=', account_id)],
            fields=['id', 'name', 'analytic_account_id'],
        )
    except Exception as e:
        out['projects_error'] = str(e)

    # List every analytic account with the same name (catches the case
    # where an id mismatch is the cause).
    try:
        if out.get('account'):
            out['same_name_accounts'] = odoo.search_read(
                'account.analytic.account',
                [('name', '=', out['account']['name'])],
                fields=['id', 'name', 'code', 'plan_id'],
            )
    except Exception as e:
        out['same_name_error'] = str(e)

    # Sample raw PO lines that substring-match this id.
    try:
        out['po_line_sample'] = odoo.search_read(
            'purchase.order.line',
            [('analytic_distribution', 'ilike', str(account_id))],
            fields=['id', 'order_id', 'analytic_distribution'],
            limit=5,
        )
    except Exception as e:
        out['po_line_error'] = str(e)

    # Sample raw move lines that substring-match this id.
    try:
        out['move_line_sample'] = odoo.search_read(
            'account.move.line',
            [('analytic_distribution', 'ilike', str(account_id))],
            fields=['id', 'move_id', 'analytic_distribution'],
            limit=5,
        )
    except Exception as e:
        out['move_line_error'] = str(e)

    # Show the first few PO lines in the system that HAVE any
    # analytic_distribution — so we can see the real key format.
    try:
        out['any_po_line_with_distribution'] = odoo.search_read(
            'purchase.order.line',
            [('analytic_distribution', '!=', False)],
            fields=['id', 'order_id', 'analytic_distribution'],
            limit=5,
        )
    except Exception as e:
        out['any_po_line_error'] = str(e)

    # SO lines tagged to this analytic — used to trace POs through sale_line_id.
    so_line_ids = []
    try:
        raw_so = odoo.search_read(
            'sale.order.line',
            [('analytic_distribution', 'ilike', str(account_id))],
            fields=['id', 'order_id', 'name', 'analytic_distribution'],
            limit=100,
        )
        verified = [
            l for l in raw_so
            if services._distribution_pct(account_id, l.get('analytic_distribution')) > 0
        ]
        so_line_ids = [l['id'] for l in verified]
        out['so_lines_for_this_analytic_count'] = len(verified)
        out['so_lines_sample'] = verified[:3]
    except Exception as e:
        out['so_lines_error'] = str(e)

    # PO lines linked to those SO lines via sale_line_id.
    if so_line_ids:
        try:
            po_via_so = odoo.search_read(
                'purchase.order.line',
                [('sale_line_id', 'in', so_line_ids)],
                fields=['id', 'order_id', 'sale_line_id',
                        'analytic_distribution', 'price_subtotal',
                        'product_qty', 'qty_invoiced', 'price_unit'],
                limit=100,
            )
            out['po_lines_via_sale_line_count'] = len(po_via_so)
            out['po_lines_via_sale_line_sample'] = po_via_so[:5]
        except Exception as e:
            out['po_via_sale_line_error'] = str(e)

    # Which PO line fields exist on this install (helps spot direct linkage
    # fields like project_id, task_id added by enterprise modules).
    try:
        fields_def = odoo.fields_get('purchase.order.line')
        interesting = sorted(
            name for name in fields_def
            if any(k in name.lower()
                   for k in ['project', 'task', 'analytic', 'sale_line', 'account_'])
        )
        out['po_line_interesting_fields'] = interesting
    except Exception as e:
        out['po_fields_error'] = str(e)

    return jsonify(out)
