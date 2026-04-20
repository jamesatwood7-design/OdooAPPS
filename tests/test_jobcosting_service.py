import pytest
from unittest.mock import MagicMock
from datetime import date

from jobcosting.services import (
    get_analytic_accounts, get_projects, get_project,
    get_tasks_for_project, get_analytic_lines,
    create_time_entry, create_expense_entry,
    get_project_detail, get_job_cost_report,
    _po_lines_for_analytic, _bill_lines_for_analytic,
    _distribution_pct, get_purchase_orders, PO_OPEN_STATES,
)


def _po_line_search_read(lines, orders=None):
    """Build a side_effect for odoo.search_read that emulates the two-phase
    PO lookup: first call returns lines, second call returns parent orders.
    """
    orders = orders or []
    def impl(model, domain, **kw):
        if model == 'purchase.order.line':
            return lines
        if model == 'purchase.order':
            return orders
        return []
    return impl


def _bill_line_search_read(lines, moves=None):
    moves = moves or []
    def impl(model, domain, **kw):
        if model == 'account.move.line':
            return lines
        if model == 'account.move':
            return moves
        return []
    return impl


@pytest.fixture
def odoo():
    mock = MagicMock()
    mock.uid = 1
    return mock


class TestAnalyticAccounts:
    def test_get_all(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Acct A', 'code': 'AA', 'balance': 100.0,
             'debit': 200.0, 'credit': 100.0},
        ]

        result = get_analytic_accounts(odoo)

        assert len(result) == 1
        assert result[0]['name'] == 'Acct A'

    def test_get_with_domain(self, odoo):
        odoo.safe_search_read.return_value = []

        get_analytic_accounts(odoo, domain=[('code', '=', 'X')])

        call_args = odoo.safe_search_read.call_args
        assert ('account.analytic.account', [('code', '=', 'X')]) == call_args[0]


class TestProjects:
    def test_get_projects(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Project Alpha',
             'analytic_account_id': [10, 'Alpha Acct'],
             'date_start': '2024-01-01', 'date': False, 'task_count': 5},
        ]

        result = get_projects(odoo)

        assert len(result) == 1
        assert result[0]['task_count'] == 5

    def test_get_project_found(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Project Alpha',
             'analytic_account_id': [10, 'Alpha Acct'],
             'date_start': '2024-01-01', 'date': False, 'task_count': 5},
        ]

        result = get_project(odoo, 1)

        assert result['name'] == 'Project Alpha'

    def test_get_project_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_project(odoo, 999)

        assert result is None


class TestTasks:
    def test_get_tasks(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Task 1', 'planned_hours': 10.0,
             'effective_hours': 6.0, 'remaining_hours': 4.0,
             'stage_id': [1, 'In Progress']},
        ]

        result = get_tasks_for_project(odoo, 1)

        assert len(result) == 1
        assert result[0]['planned_hours'] == 10.0


class TestAnalyticLines:
    def test_get_lines_formatted(self, odoo):
        odoo.safe_search_read.return_value = [
            {'id': 1, 'name': 'Dev work', 'date': '2024-01-15',
             'amount': -150.0, 'unit_amount': 2.0,
             'employee_id': [1, 'Alice'], 'project_id': [1, 'Alpha'],
             'task_id': [1, 'Task 1'], 'account_id': [10, 'Acct']},
        ]

        result = get_analytic_lines(odoo, project_id=1)

        assert len(result) == 1
        assert result[0]['unit_amount_fmt'] == '2h 00m'
        assert result[0]['date_obj'] == date(2024, 1, 15)


class TestCreateEntries:
    def test_create_time_entry_with_rate(self, odoo):
        odoo.create.return_value = 100

        result = create_time_entry(
            odoo, account_id=10, project_id=1, task_id=1,
            employee_id=1, entry_date=date(2024, 1, 15),
            hours=2.5, description='Development work', hourly_rate=75.0,
        )

        assert result == 100
        call_args = odoo.create.call_args[0]
        assert call_args[0] == 'account.analytic.line'
        values = call_args[1]
        assert values['unit_amount'] == 2.5
        assert values['amount'] == -(2.5 * 75.0)
        assert values['name'] == 'Development work'

    def test_create_time_entry_no_rate(self, odoo):
        odoo.create.return_value = 101

        create_time_entry(
            odoo, account_id=10, project_id=1, task_id=None,
            employee_id=None, entry_date=date(2024, 1, 15),
            hours=3.0, description='Research',
        )

        values = odoo.create.call_args[0][1]
        assert values['amount'] == 0
        assert 'task_id' not in values
        assert 'employee_id' not in values

    def test_create_expense_entry(self, odoo):
        odoo.create.return_value = 102

        create_expense_entry(
            odoo, account_id=10, entry_date=date(2024, 1, 15),
            amount=250.0, description='Materials', project_id=1,
        )

        values = odoo.create.call_args[0][1]
        assert values['amount'] == -250.0
        assert values['name'] == 'Materials'
        assert values['project_id'] == 1


class TestProjectDetail:
    def test_returns_aggregated_data(self, odoo):
        def mock_search_read(model, domain, **kwargs):
            if model == 'project.project':
                return [{'id': 1, 'name': 'Alpha',
                         'analytic_account_id': [10, 'Acct'],
                         'date_start': False, 'date': False, 'task_count': 2}]
            elif model == 'project.task':
                return [
                    {'id': 1, 'name': 'Task 1', 'planned_hours': 10.0,
                     'effective_hours': 6.0, 'remaining_hours': 4.0,
                     'stage_id': [1, 'Done']},
                    {'id': 2, 'name': 'Task 2', 'planned_hours': 20.0,
                     'effective_hours': 15.0, 'remaining_hours': 5.0,
                     'stage_id': [2, 'In Progress']},
                ]
            elif model == 'account.analytic.line':
                return [
                    {'id': 1, 'name': 'Work', 'date': '2024-01-15',
                     'amount': -450.0, 'unit_amount': 6.0,
                     'employee_id': False, 'project_id': [1, 'Alpha'],
                     'task_id': [1, 'Task 1'], 'account_id': [10, 'Acct']},
                    {'id': 2, 'name': 'More work', 'date': '2024-01-16',
                     'amount': -1125.0, 'unit_amount': 15.0,
                     'employee_id': False, 'project_id': [1, 'Alpha'],
                     'task_id': [2, 'Task 2'], 'account_id': [10, 'Acct']},
                ]
            return []

        odoo.safe_search_read.side_effect = mock_search_read

        result = get_project_detail(odoo, 1)

        assert result is not None
        assert result['totals']['budgeted_hours'] == 30.0
        assert result['totals']['actual_hours'] == 21.0
        assert result['totals']['total_cost'] == 1575.0
        assert result['totals']['variance_sign'] == 'under'

    def test_project_not_found(self, odoo):
        odoo.safe_search_read.return_value = []

        result = get_project_detail(odoo, 999)

        assert result is None


class TestJobCostReport:
    def test_budget_vs_actual(self, odoo):
        call_count = [0]

        def mock_search_read(model, domain, **kwargs):
            if model == 'project.project':
                return [{'id': 1, 'name': 'Alpha',
                         'analytic_account_id': [10, 'Acct'],
                         'date_start': False, 'date': False, 'task_count': 1}]
            elif model == 'project.task':
                return [
                    {'id': 1, 'name': 'Task 1', 'planned_hours': 40.0,
                     'effective_hours': 45.0, 'remaining_hours': -5.0,
                     'stage_id': [1, 'In Progress']},
                ]
            return []

        odoo.safe_search_read.side_effect = mock_search_read
        odoo.read_group.return_value = [
            {'task_id': [1, 'Task 1'], 'unit_amount': 45.0,
             'amount': -3375.0, '__count': 10},
        ]

        result = get_job_cost_report(odoo, 1)

        assert result is not None
        assert len(result['task_rows']) == 1
        assert result['task_rows'][0]['budgeted_hours'] == 40.0
        assert result['task_rows'][0]['actual_hours'] == 45.0
        assert result['task_rows'][0]['variance_sign'] == 'over'
        assert result['totals']['variance_sign'] == 'over'

    def test_empty_project(self, odoo):
        odoo.safe_search_read.side_effect = lambda model, domain, **kw: (
            [{'id': 1, 'name': 'Empty', 'analytic_account_id': False,
              'date_start': False, 'date': False, 'task_count': 0}]
            if model == 'project.project' else []
        )
        odoo.read_group.return_value = []

        result = get_job_cost_report(odoo, 1)

        assert result is not None
        assert result['totals']['budgeted_hours'] == 0
        assert result['totals']['actual_hours'] == 0


class TestDistributionPct:
    def test_simple_key(self):
        assert _distribution_pct(24, {'24': 100.0}) == 100.0

    def test_rejects_substring_false_positive(self):
        assert _distribution_pct(24, {'242': 100.0}) == 0.0
        assert _distribution_pct(24, {'124': 100.0}) == 0.0

    def test_compound_key_odoo17_analytic_plans(self):
        # When Analytic Plans are enabled, a line tagged to job 24 AND
        # department 42 is stored with a single compound key "24,42".
        # Each analytic in the key still receives the full percentage.
        assert _distribution_pct(24, {'24,42': 100.0}) == 100.0
        assert _distribution_pct(42, {'24,42': 100.0}) == 100.0

    def test_compound_key_partial_share(self):
        assert _distribution_pct(24, {'24,42': 60.0, '25,42': 40.0}) == 60.0

    def test_non_dict_returns_zero(self):
        assert _distribution_pct(24, None) == 0.0
        assert _distribution_pct(24, False) == 0.0
        assert _distribution_pct(24, 'not-a-dict') == 0.0


class TestSearchDomain:
    """Verify the canonical Odoo 17 analytic-account search is used."""

    def test_po_line_search_uses_distribution_m2m(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(lines=[], orders=[])

        _po_lines_for_analytic(odoo, 1084)

        first_call = odoo.search_read.call_args_list[0]
        assert first_call[0][0] == 'purchase.order.line'
        domain = first_call[0][1]
        assert ('distribution_analytic_account_ids', 'in', [1084]) in domain

    def test_po_line_search_falls_back_to_ilike(self, odoo):
        calls = []
        def impl(model, domain, **kw):
            calls.append((model, domain))
            if len(calls) == 1 and model == 'purchase.order.line':
                raise Exception("distribution_analytic_account_ids missing")
            return []
        odoo.search_read.side_effect = impl

        _po_lines_for_analytic(odoo, 1084)

        assert ('distribution_analytic_account_ids', 'in', [1084]) in calls[0][1]
        assert ('analytic_distribution', 'ilike', '1084') in calls[1][1]

    def test_bill_line_search_uses_distribution_m2m(self, odoo):
        odoo.search_read.side_effect = _bill_line_search_read(lines=[], moves=[])

        _bill_lines_for_analytic(odoo, 1084)

        first_call = odoo.search_read.call_args_list[0]
        assert first_call[0][0] == 'account.move.line'
        domain = first_call[0][1]
        assert ('distribution_analytic_account_ids', 'in', [1084]) in domain


class TestPOLinesForAnalytic:
    def test_single_full_attribution(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 10.0, 'qty_invoiced': 2.0, 'price_unit': 50.0,
                'price_subtotal': 500.0, 'analytic_distribution': {'24': 100.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert len(result) == 1
        line = result[0]
        assert line['distribution_pct'] == 100.0
        assert line['attributed_amount'] == 500.0
        assert line['committed_amount'] == 400.0

    def test_partial_attribution_respects_pct(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 10.0, 'qty_invoiced': 0.0, 'price_unit': 100.0,
                'price_subtotal': 1000.0,
                'analytic_distribution': {'24': 60.0, '25': 40.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert len(result) == 1
        line = result[0]
        assert line['distribution_pct'] == 60.0
        assert line['attributed_amount'] == 600.0
        assert line['committed_amount'] == 600.0

    def test_compound_analytic_plan_key(self, odoo):
        # The bug that was silently dropping every PO: compound key "24,42"
        # failed the old `str(24) in dist` dict-key check.
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 10.0, 'qty_invoiced': 0.0, 'price_unit': 100.0,
                'price_subtotal': 1000.0,
                'analytic_distribution': {'24,42': 100.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert len(result) == 1
        assert result[0]['attributed_amount'] == 1000.0
        assert result[0]['committed_amount'] == 1000.0

    def test_rejects_ilike_false_positive(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 1.0, 'qty_invoiced': 0.0, 'price_unit': 10.0,
                'price_subtotal': 10.0,
                'analytic_distribution': {'242': 100.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert result == []

    def test_filters_to_open_states_post_fetch(self, odoo):
        # Two lines on two orders: one open (done), one cancelled.
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[
                {'id': 11, 'order_id': (100, 'PO100'),
                 'product_qty': 1.0, 'qty_invoiced': 0.0, 'price_unit': 10.0,
                 'price_subtotal': 10.0, 'analytic_distribution': {'24': 100.0}},
                {'id': 12, 'order_id': (200, 'PO200'),
                 'product_qty': 1.0, 'qty_invoiced': 0.0, 'price_unit': 10.0,
                 'price_subtotal': 10.0, 'analytic_distribution': {'24': 100.0}},
            ],
            orders=[
                {'id': 100, 'state': 'done'},
                {'id': 200, 'state': 'cancel'},
            ],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert len(result) == 1
        assert result[0]['order_pk'] == 100

    def test_fully_invoiced_line_has_zero_committed(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 5.0, 'qty_invoiced': 5.0, 'price_unit': 100.0,
                'price_subtotal': 500.0, 'analytic_distribution': {'24': 100.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert result[0]['committed_amount'] == 0.0

    def test_over_invoiced_clamped_to_zero(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 5.0, 'qty_invoiced': 7.0, 'price_unit': 100.0,
                'price_subtotal': 500.0, 'analytic_distribution': {'24': 100.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert result[0]['committed_amount'] == 0.0

    def test_zero_pct_is_dropped(self, odoo):
        odoo.search_read.side_effect = _po_line_search_read(
            lines=[{
                'id': 11, 'order_id': (100, 'PO100'),
                'product_qty': 10.0, 'qty_invoiced': 0.0, 'price_unit': 50.0,
                'price_subtotal': 500.0, 'analytic_distribution': {'24': 0.0},
            }],
            orders=[{'id': 100, 'state': 'purchase'}],
        )

        result = _po_lines_for_analytic(odoo, 24)

        assert result == []


class TestBillLinesForAnalytic:
    def test_attribution_and_refund_flag(self, odoo):
        odoo.search_read.side_effect = _bill_line_search_read(
            lines=[
                {'id': 1, 'move_id': (500, 'BILL/001'), 'name': 'a',
                 'price_subtotal': 1000.0,
                 'analytic_distribution': {'24': 60.0}},
                {'id': 2, 'move_id': (501, 'CN/001'), 'name': 'b',
                 'price_subtotal': 200.0,
                 'analytic_distribution': {'24': 100.0}},
            ],
            moves=[
                {'id': 500, 'move_type': 'in_invoice', 'state': 'posted'},
                {'id': 501, 'move_type': 'in_refund', 'state': 'posted'},
            ],
        )

        result = _bill_lines_for_analytic(odoo, 24)

        by_move = {line['move_pk']: line for line in result}
        assert by_move[500]['attributed_amount'] == 600.0
        assert by_move[500]['is_refund'] is False
        assert by_move[501]['attributed_amount'] == 200.0
        assert by_move[501]['is_refund'] is True

    def test_compound_analytic_plan_key(self, odoo):
        odoo.search_read.side_effect = _bill_line_search_read(
            lines=[{
                'id': 1, 'move_id': (500, 'BILL/001'), 'name': 'a',
                'price_subtotal': 1000.0,
                'analytic_distribution': {'24,42': 100.0},
            }],
            moves=[{'id': 500, 'move_type': 'in_invoice', 'state': 'posted'}],
        )

        result = _bill_lines_for_analytic(odoo, 24)

        assert len(result) == 1
        assert result[0]['attributed_amount'] == 1000.0

    def test_rejects_ilike_false_positive(self, odoo):
        odoo.search_read.side_effect = _bill_line_search_read(
            lines=[{
                'id': 1, 'move_id': (500, 'BILL/001'), 'name': 'a',
                'price_subtotal': 1000.0,
                'analytic_distribution': {'124': 100.0},
            }],
            moves=[{'id': 500, 'move_type': 'in_invoice', 'state': 'posted'}],
        )

        result = _bill_lines_for_analytic(odoo, 24)

        assert result == []

    def test_filters_to_posted_vendor_moves_post_fetch(self, odoo):
        odoo.search_read.side_effect = _bill_line_search_read(
            lines=[
                {'id': 1, 'move_id': (500, 'BILL/001'), 'name': 'a',
                 'price_subtotal': 100.0,
                 'analytic_distribution': {'24': 100.0}},
                {'id': 2, 'move_id': (600, 'INV/001'), 'name': 'b',
                 'price_subtotal': 200.0,
                 'analytic_distribution': {'24': 100.0}},
                {'id': 3, 'move_id': (700, 'DRAFT'), 'name': 'c',
                 'price_subtotal': 300.0,
                 'analytic_distribution': {'24': 100.0}},
            ],
            moves=[
                {'id': 500, 'move_type': 'in_invoice', 'state': 'posted'},
                {'id': 600, 'move_type': 'out_invoice', 'state': 'posted'},
                {'id': 700, 'move_type': 'in_invoice', 'state': 'draft'},
            ],
        )

        result = _bill_lines_for_analytic(odoo, 24)

        move_pks = {line['move_pk'] for line in result}
        assert move_pks == {500}


class TestGetPurchaseOrdersAttribution:
    def test_primary_path_aggregates_lines_to_orders(self, odoo):
        def fake_search_read(model, domain, **kw):
            if model == 'purchase.order.line':
                return [
                    {'id': 11, 'order_id': (100, 'PO100'),
                     'product_qty': 10.0, 'qty_invoiced': 2.0,
                     'price_unit': 50.0, 'price_subtotal': 500.0,
                     'analytic_distribution': {'24': 100.0}},
                    {'id': 12, 'order_id': (100, 'PO100'),
                     'product_qty': 4.0, 'qty_invoiced': 0.0,
                     'price_unit': 25.0, 'price_subtotal': 100.0,
                     'analytic_distribution': {'24': 50.0}},
                    {'id': 21, 'order_id': (200, 'PO200'),
                     'product_qty': 1.0, 'qty_invoiced': 0.0,
                     'price_unit': 10.0, 'price_subtotal': 10.0,
                     'analytic_distribution': {'24': 100.0}},
                ]
            if model == 'purchase.order':
                return [
                    {'id': 100, 'state': 'purchase'},
                    {'id': 200, 'state': 'done'},
                ]
            return []
        odoo.search_read.side_effect = fake_search_read
        odoo.safe_search_read.return_value = [
            {'id': 100, 'name': 'PO100', 'partner_id': (9, 'Vendor A'),
             'date_order': '2025-01-01', 'amount_total': 600.0,
             'amount_untaxed': 600.0, 'state': 'purchase',
             'invoice_status': 'to invoice'},
            {'id': 200, 'name': 'PO200', 'partner_id': (9, 'Vendor A'),
             'date_order': '2025-01-02', 'amount_total': 10.0,
             'amount_untaxed': 10.0, 'state': 'done',
             'invoice_status': 'invoiced'},
        ]

        result = get_purchase_orders(odoo, 24)

        by_id = {po['id']: po for po in result}
        # PO100: line 11 attributed 500, line 12 attributed 50 (100 * 0.5); committed = (10-2)*50*1 + 4*25*0.5 = 400 + 50 = 450
        assert by_id[100]['attributed_amount'] == 550.0
        assert by_id[100]['committed_amount'] == 450.0
        assert by_id[100]['matched_line_count'] == 2
        # PO200: single line, fully invoiced in practice? committed = 1*10*1 = 10
        assert by_id[200]['attributed_amount'] == 10.0
        assert by_id[200]['committed_amount'] == 10.0
