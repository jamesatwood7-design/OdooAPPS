import os
import tempfile

import pytest
from unittest.mock import MagicMock

from migration.id_map import IdMap
from migration.logging_setup import setup_logging
from migration.phases import (
    accounts, taxes, contacts, projects, analytic_accounts,
    moves, payments, analytic_lines,
)


@pytest.fixture
def id_map(tmp_path):
    db = tmp_path / 'idmap.sqlite'
    m = IdMap(str(db))
    yield m
    m.close()


@pytest.fixture
def logger(tmp_path):
    return setup_logging(str(tmp_path / 'logs'), verbose=False)


@pytest.fixture
def mock_odoo():
    o = MagicMock()
    o.safe_search_read.return_value = []
    return o


@pytest.fixture
def mock_zoho():
    z = MagicMock()
    return z


def test_accounts_phase_creates_and_skips(mock_odoo, mock_zoho, id_map, logger):
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 1, 'name': 'Sales', 'code': '4000', 'account_type': 'income'},
         {'id': 2, 'name': 'Cash', 'code': '1000', 'account_type': 'asset_cash'}],
        [],
    ]
    mock_zoho.create_account.side_effect = [
        {'chart_of_account': {'account_id': 'A1'}},
        {'chart_of_account': {'account_id': 'A2'}},
    ]
    counts = accounts.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts == {'created': 2, 'skipped': 0, 'failed': 0}
    assert id_map.get_zoho_id('account.account', 1) == 'A1'

    # Re-run -> all skipped
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 1, 'name': 'Sales', 'code': '4000', 'account_type': 'income'},
         {'id': 2, 'name': 'Cash', 'code': '1000', 'account_type': 'asset_cash'}],
        [],
    ]
    counts2 = accounts.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts2 == {'created': 0, 'skipped': 2, 'failed': 0}


def test_accounts_phase_records_failure(mock_odoo, mock_zoho, id_map, logger):
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 5, 'name': 'X', 'code': '', 'account_type': 'income'}],
        [],
    ]
    mock_zoho.create_account.side_effect = RuntimeError('boom')
    counts = accounts.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts['failed'] == 1
    failed = id_map.iter_failed('account.account')
    assert len(failed) == 1


def test_taxes_phase_creates_leaves_before_groups(mock_odoo, mock_zoho, id_map, logger):
    mock_odoo.safe_search_read.side_effect = [
        [
            {'id': 1, 'name': 'GST 5', 'amount': 5.0, 'amount_type': 'percent'},
            {'id': 2, 'name': 'PST 7', 'amount': 7.0, 'amount_type': 'percent'},
            {'id': 3, 'name': 'Combined', 'amount': 0.0, 'amount_type': 'group',
             'children_tax_ids': [1, 2]},
        ],
        [],
    ]
    create_calls = []

    def create(body):
        create_calls.append(body)
        return {'tax': {'tax_id': f"t{len(create_calls)}"}}

    mock_zoho.create_tax.side_effect = create
    counts = taxes.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts == {'created': 3, 'skipped': 0, 'failed': 0}
    # Leaves come before group
    assert create_calls[0]['tax_name'] == 'GST 5'
    assert create_calls[2].get('tax_specific_type') == 'compound_tax'


def test_contacts_phase_handles_dual_role(mock_odoo, mock_zoho, id_map, logger):
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 10, 'name': 'Both Inc', 'is_company': True,
          'customer_rank': 1, 'supplier_rank': 1, 'parent_id': False,
          'email': 'b@x.com', 'phone': '1', 'street': 's',
          'city': 'c', 'zip': 'z', 'state_id': False, 'country_id': False,
          'currency_id': False, 'vat': False}],
        [],
    ]
    mock_zoho.create_contact.side_effect = [
        {'contact': {'contact_id': 'CUST-1'}},
        {'contact': {'contact_id': 'VEND-1'}},
    ]
    counts = contacts.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts['created'] == 2
    assert id_map.get_zoho_id('res.partner', 10, 'customer') == 'CUST-1'
    assert id_map.get_zoho_id('res.partner', 10, 'vendor') == 'VEND-1'


def test_projects_phase_links_analytic_account(mock_odoo, mock_zoho, id_map, logger):
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 7, 'name': 'P1', 'partner_id': [3, 'Acme'],
          'analytic_account_id': [88, 'P1 Analytic']}],
        [],
    ]
    id_map.put('res.partner', 3, 'contact', 'CUST-9',
               status='created', variant='customer')
    mock_zoho.create_project.return_value = {'project': {'project_id': 'PRJ-7'}}
    counts = projects.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts['created'] == 1
    assert id_map.get_zoho_id('project.project', 7) == 'PRJ-7'
    # Linked analytic account is mapped to same Zoho project.
    assert id_map.get_zoho_id('account.analytic.account', 88) == 'PRJ-7'


def test_analytic_accounts_skips_already_linked(mock_odoo, mock_zoho, id_map, logger):
    # Already mapped via projects phase.
    id_map.put('account.analytic.account', 88, 'project', 'PRJ-7',
               status='created')
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 88, 'name': 'P1 Analytic', 'partner_id': False, 'active': True}],
        [],
    ]
    counts = analytic_accounts.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts == {'created': 0, 'skipped': 1, 'failed': 0}
    mock_zoho.create_project.assert_not_called()


def test_moves_phase_routes_by_move_type(mock_odoo, mock_zoho, id_map, logger):
    id_map.put('res.partner', 11, 'contact', 'CUST-1',
               status='created', variant='customer')
    id_map.put('res.partner', 12, 'contact', 'VEND-1',
               status='created', variant='vendor')
    id_map.put('account.account', 50, 'chart_of_account', 'A1',
               status='created')

    # Two moves: an out_invoice and an in_invoice
    move_recs = [
        {'id': 100, 'name': 'INV/100', 'move_type': 'out_invoice',
         'state': 'posted', 'partner_id': [11, 'C'],
         'invoice_date': '2024-01-01', 'invoice_date_due': '2024-02-01',
         'currency_id': [1, 'USD'], 'line_ids': [1]},
        {'id': 200, 'name': 'BILL/200', 'move_type': 'in_invoice',
         'state': 'posted', 'partner_id': [12, 'V'],
         'invoice_date': '2024-01-05', 'invoice_date_due': '2024-02-05',
         'currency_id': [1, 'USD'], 'line_ids': [2], 'ref': 'V-1'},
    ]
    line_recs_by_id = {
        1: [{'id': 1, 'name': 'Widget', 'account_id': [50, 'Sales'],
             'price_unit': 50.0, 'quantity': 1, 'tax_ids': [],
             'display_type': False}],
        2: [{'id': 2, 'name': 'Supplies', 'account_id': [50, 'COGS'],
             'price_unit': 30.0, 'quantity': 1, 'tax_ids': [],
             'display_type': False}],
    }

    def search_read_side_effect(model, domain, fields=None, **kwargs):
        if model == 'account.move':
            offset = kwargs.get('offset', 0)
            return move_recs if offset == 0 else []
        if model == 'account.move.line':
            ids = domain[0][2]
            out = []
            for i in ids:
                out.extend(line_recs_by_id.get(i, []))
            return out
        return []

    mock_odoo.safe_search_read.side_effect = search_read_side_effect
    mock_zoho.create_invoice.return_value = {'invoice': {'invoice_id': 'I-100'}}
    mock_zoho.create_bill.return_value = {'bill': {'bill_id': 'B-200'}}

    counts = moves.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts['created'] == 2
    assert mock_zoho.create_invoice.called
    assert mock_zoho.create_bill.called


def test_analytic_lines_requires_user_id(mock_odoo, mock_zoho, id_map, logger):
    with pytest.raises(ValueError):
        analytic_lines.migrate(mock_odoo, mock_zoho, id_map, False, logger,
                               zoho_user_id=None)


def test_analytic_lines_attaches_to_project(mock_odoo, mock_zoho, id_map, logger):
    id_map.put('project.project', 5, 'project', 'PRJ-5', status='created')
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 99, 'name': 'work', 'date': '2024-05-01', 'unit_amount': 1.5,
          'project_id': [5, 'P5'], 'account_id': False, 'employee_id': False,
          'user_id': [1, 'admin']}],
        [],
    ]
    mock_zoho.log_time_entry.return_value = {
        'time_entry': {'time_entry_id': 'TE-1'},
    }
    counts = analytic_lines.migrate(
        mock_odoo, mock_zoho, id_map, False, logger,
        zoho_user_id='zuser-1',
    )
    assert counts['created'] == 1
    body = mock_zoho.log_time_entry.call_args[0][0]
    assert body['project_id'] == 'PRJ-5'
    assert body['user_id'] == 'zuser-1'
    assert body['log_time'] == 1.5


def test_payments_phase_inbound_attaches_invoice(mock_odoo, mock_zoho, id_map, logger):
    id_map.put('res.partner', 11, 'contact', 'CUST-1',
               status='created', variant='customer')
    id_map.put('account.move', 100, 'invoice', 'I-100',
               status='created', variant='out_invoice')
    mock_odoo.safe_search_read.side_effect = [
        [{'id': 500, 'name': 'PMT/1', 'partner_id': [11, 'C'],
          'partner_type': 'customer', 'payment_type': 'inbound',
          'amount': 100.0, 'date': '2024-05-10',
          'currency_id': [1, 'USD'], 'state': 'posted',
          'reconciled_invoice_ids': [100], 'reconciled_bill_ids': []}],
        [],
    ]
    mock_zoho.create_customer_payment.return_value = {
        'payment': {'payment_id': 'P-500'},
    }
    counts = payments.migrate(mock_odoo, mock_zoho, id_map, False, logger)
    assert counts['created'] == 1
    body = mock_zoho.create_customer_payment.call_args[0][0]
    assert body['customer_id'] == 'CUST-1'
    assert body['invoices'] == [{'invoice_id': 'I-100', 'amount_applied': 0}]
