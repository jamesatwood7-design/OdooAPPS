from unittest.mock import MagicMock

from migration import mappers


def test_map_account_basic():
    rec = {'id': 5, 'name': 'Sales', 'code': '4000',
           'account_type': 'income', 'currency_id': False}
    body = mappers.map_account(rec)
    assert body['account_name'] == 'Sales'
    assert body['account_code'] == '4000'
    assert body['account_type'] == 'income'


def test_map_account_unknown_type_falls_back():
    rec = {'id': 1, 'name': 'X', 'code': '', 'account_type': 'mystery'}
    body = mappers.map_account(rec)
    assert body['account_type'] == 'other_current_asset'


def test_map_tax_leaf():
    rec = {'id': 1, 'name': 'GST 5%', 'amount': 5.0, 'amount_type': 'percent'}
    body = mappers.map_tax(rec)
    assert body['tax_percentage'] == 5.0
    assert 'tax_specific_type' not in body


def test_map_tax_group_with_children():
    rec = {'id': 9, 'name': 'Combined', 'amount': 0.0, 'amount_type': 'group'}
    body = mappers.map_tax(rec, child_zoho_ids=['101', '102'])
    assert body['tax_specific_type'] == 'compound_tax'


def test_map_contact_customer_with_address():
    rec = {
        'id': 7, 'name': 'Acme Co', 'company_name': 'Acme Co',
        'is_company': True, 'email': 'ops@acme.com', 'phone': '555-1',
        'street': '1 Main', 'street2': '', 'city': 'Townsville',
        'zip': '12345', 'state_id': [10, 'QLD'], 'country_id': [1, 'Australia'],
        'currency_id': [2, 'AUD'], 'vat': 'AU123', 'customer_rank': 1,
        'supplier_rank': 0,
    }
    body = mappers.map_contact(rec, 'customer')
    assert body['contact_type'] == 'customer'
    assert body['email'] == 'ops@acme.com'
    assert body['billing_address']['city'] == 'Townsville'
    assert body['billing_address']['state'] == 'QLD'
    assert body['currency_code'] == 'AUD'
    assert body['tax_reg_no'] == 'AU123'
    assert any(cf['label'] == 'odoo_id' and cf['value'] == '7'
               for cf in body['custom_fields'])


def test_map_contact_invalid_role():
    import pytest
    with pytest.raises(ValueError):
        mappers.map_contact({'id': 1, 'name': 'x'}, 'partner')


def test_map_project_with_customer():
    rec = {'id': 3, 'name': 'Big Build', 'partner_id': [11, 'Acme'],
           'date_start': '2024-01-01', 'date': '2024-12-31'}
    body = mappers.map_project(rec, customer_zoho_id='cust-99')
    assert body['project_name'] == 'Big Build'
    assert body['customer_id'] == 'cust-99'
    assert body['start_date'] == '2024-01-01'


def test_map_invoice_uses_id_map_for_customer_account_tax():
    id_map = MagicMock()
    id_map.get_zoho_id.side_effect = lambda model, oid, variant='': {
        ('res.partner', 11, 'customer'): 'cust-1',
        ('account.account', 50, ''): 'acc-1',
        ('account.tax', 7, ''): 'tax-1',
    }.get((model, oid, variant))

    move = {'id': 100, 'name': 'INV/100', 'partner_id': [11, 'Acme'],
            'invoice_date': '2024-05-01', 'invoice_date_due': '2024-05-31',
            'currency_id': [2, 'USD']}
    lines = [
        {'id': 1, 'name': 'Widget', 'account_id': [50, 'Sales'],
         'price_unit': 100.0, 'quantity': 2.0, 'tax_ids': [7],
         'display_type': False},
        {'id': 2, 'name': 'Section', 'display_type': 'line_section',
         'tax_ids': []},
    ]
    body = mappers.map_invoice(move, lines, id_map)
    assert body['customer_id'] == 'cust-1'
    assert body['invoice_number'] == 'INV/100'
    assert len(body['line_items']) == 1
    item = body['line_items'][0]
    assert item['account_id'] == 'acc-1'
    assert item['tax_id'] == 'tax-1'
    assert item['rate'] == 100.0
    assert item['quantity'] == 2.0


def test_map_invoice_raises_when_customer_unmapped():
    import pytest
    id_map = MagicMock()
    id_map.get_zoho_id.return_value = None
    with pytest.raises(KeyError):
        mappers.map_invoice(
            {'id': 1, 'partner_id': [9, 'X']}, [], id_map,
        )


def test_resolve_partner_direct_hit():
    id_map = MagicMock()
    id_map.get_zoho_id.side_effect = lambda model, oid, variant='': (
        'CUST-9' if (model, oid, variant) == ('res.partner', 9, 'customer') else None
    )
    assert mappers.resolve_partner_zoho_id(id_map, 9, 'customer') == 'CUST-9'


def test_resolve_partner_falls_back_to_parent_when_odoo_available():
    id_map = MagicMock()
    id_map.get_zoho_id.side_effect = lambda model, oid, variant='': (
        'CUST-99' if (model, oid, variant) == ('res.partner', 99, 'customer') else None
    )
    odoo = MagicMock()
    odoo.read.return_value = [{'parent_id': [99, 'ParentCo']}]
    # partner 50 has no entry; parent 99 does
    assert (
        mappers.resolve_partner_zoho_id(id_map, 50, 'customer', odoo=odoo)
        == 'CUST-99'
    )


def test_resolve_partner_falls_back_to_opposite_variant():
    id_map = MagicMock()
    # Only vendor variant exists for partner 7
    id_map.get_zoho_id.side_effect = lambda model, oid, variant='': (
        'VEND-7' if (model, oid, variant) == ('res.partner', 7, 'vendor') else None
    )
    # Looking up as customer should fall back to the vendor side
    assert (
        mappers.resolve_partner_zoho_id(id_map, 7, 'customer')
        == 'VEND-7'
    )


def test_resolve_partner_raises_with_no_fallbacks():
    import pytest
    id_map = MagicMock()
    id_map.get_zoho_id.return_value = None
    with pytest.raises(KeyError):
        mappers.resolve_partner_zoho_id(id_map, 123, 'customer')


def test_resolve_partner_parent_lookup_skipped_when_no_odoo():
    import pytest
    id_map = MagicMock()
    id_map.get_zoho_id.return_value = None
    # odoo=None: skip parent lookup, no opposite variant either -> KeyError
    with pytest.raises(KeyError):
        mappers.resolve_partner_zoho_id(id_map, 50, 'customer')


def test_map_bill_uses_parent_fallback():
    id_map = MagicMock()
    id_map.get_zoho_id.side_effect = lambda model, oid, variant='': (
        'VEND-PARENT' if (model, oid, variant) == ('res.partner', 200, 'vendor')
        else None
    )
    odoo = MagicMock()
    odoo.read.return_value = [{'parent_id': [200, 'ParentVendor']}]
    bill = {'id': 5, 'name': 'BILL/5', 'partner_id': [50, 'Child'],
            'invoice_date': '2024-01-01'}
    body = mappers.map_bill(bill, [], id_map, odoo=odoo)
    assert body['vendor_id'] == 'VEND-PARENT'


def test_map_journal_filters_zero_lines():
    id_map = MagicMock()
    id_map.get_zoho_id.return_value = 'acc-1'
    move = {'id': 5, 'name': 'JE/5', 'date': '2024-04-01'}
    lines = [
        {'name': 'D', 'account_id': [1, 'A'], 'debit': 100, 'credit': 0},
        {'name': 'C', 'account_id': [1, 'A'], 'debit': 0, 'credit': 100},
        {'name': 'Z', 'account_id': [1, 'A'], 'debit': 0, 'credit': 0},
    ]
    body = mappers.map_journal(move, lines, id_map)
    assert len(body['line_items']) == 2
    assert {li['debit_or_credit'] for li in body['line_items']} == {'debit', 'credit'}


def test_map_time_entry_minimal():
    rec = {'id': 1, 'date': '2024-05-01', 'unit_amount': 2.5, 'name': 'Work'}
    body = mappers.map_time_entry(rec, 'proj-1', 'user-1')
    assert body['project_id'] == 'proj-1'
    assert body['user_id'] == 'user-1'
    assert body['log_time'] == 2.5
