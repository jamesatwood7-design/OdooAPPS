import pytest
from werkzeug.datastructures import MultiDict

from common.list_query import (
    parse_list_query, page_url,
    search_facet, select_facet, m2o_facet, date_range_facet,
)


class TestSearchFacet:
    def test_single_field_produces_ilike(self):
        facets = [search_facet('q', ['name'])]
        result = parse_list_query(MultiDict({'q': 'acme'}), facets)
        assert result['domain'] == [('name', 'ilike', 'acme')]
        assert result['q'] == 'acme'
        assert result['filters'] == {'q': 'acme'}

    def test_multi_field_produces_or_chain(self):
        facets = [search_facet('q', ['name', 'partner_id.name', 'ref'])]
        result = parse_list_query(MultiDict({'q': 'acme'}), facets)
        assert result['domain'] == [
            '|', '|',
            ('name', 'ilike', 'acme'),
            ('partner_id.name', 'ilike', 'acme'),
            ('ref', 'ilike', 'acme'),
        ]

    def test_empty_search_produces_empty_domain(self):
        facets = [search_facet('q', ['name'])]
        result = parse_list_query(MultiDict({}), facets)
        assert result['domain'] == []
        assert result['q'] == ''

    def test_whitespace_only_search_is_dropped(self):
        facets = [search_facet('q', ['name'])]
        result = parse_list_query(MultiDict({'q': '   '}), facets)
        assert result['domain'] == []


class TestSelectFacet:
    def test_value_appended_to_domain(self):
        facets = [select_facet('state', 'state',
                               [('draft', 'Draft'), ('posted', 'Posted')])]
        result = parse_list_query(MultiDict({'state': 'posted'}), facets)
        assert result['domain'] == [('state', '=', 'posted')]
        assert result['filters']['state'] == 'posted'

    def test_empty_value_does_not_filter(self):
        facets = [select_facet('state', 'state', [('posted', 'Posted')])]
        result = parse_list_query(MultiDict({'state': ''}), facets)
        assert result['domain'] == []


class TestM2OFacet:
    def test_int_coercion(self):
        facets = [m2o_facet('partner_id', 'partner_id')]
        result = parse_list_query(MultiDict({'partner_id': '42'}), facets)
        assert result['domain'] == [('partner_id', '=', 42)]

    def test_non_numeric_ignored(self):
        facets = [m2o_facet('partner_id', 'partner_id')]
        result = parse_list_query(MultiDict({'partner_id': 'abc'}), facets)
        assert result['domain'] == []


class TestDateRangeFacet:
    def test_both_ends(self):
        facets = [date_range_facet('date_from', 'date_to', 'invoice_date')]
        result = parse_list_query(
            MultiDict({'date_from': '2025-01-01', 'date_to': '2025-12-31'}),
            facets,
        )
        assert ('invoice_date', '>=', '2025-01-01') in result['domain']
        assert ('invoice_date', '<=', '2025-12-31') in result['domain']

    def test_only_from(self):
        facets = [date_range_facet('date_from', 'date_to', 'invoice_date')]
        result = parse_list_query(MultiDict({'date_from': '2025-01-01'}), facets)
        assert result['domain'] == [('invoice_date', '>=', '2025-01-01')]


class TestSort:
    def test_sort_desc(self):
        result = parse_list_query(
            MultiDict({'sort': 'amount_desc'}),
            [],
            {'amount': 'amount_total'},
        )
        assert result['order'] == 'amount_total desc'

    def test_sort_asc(self):
        result = parse_list_query(
            MultiDict({'sort': 'amount_asc'}),
            [],
            {'amount': 'amount_total'},
        )
        assert result['order'] == 'amount_total asc'

    def test_unknown_sort_key_ignored(self):
        result = parse_list_query(
            MultiDict({'sort': 'bogus_desc'}),
            [],
            {'amount': 'amount_total'},
        )
        assert result['order'] is None

    def test_default_sort_applied_when_no_param(self):
        result = parse_list_query(
            MultiDict({}),
            [],
            {'date': 'invoice_date'},
            default_sort='date_desc',
        )
        assert result['order'] == 'invoice_date desc'


class TestPagination:
    def test_default_page_and_size(self):
        result = parse_list_query(MultiDict({}), [])
        assert result['page'] == 1
        assert result['page_size'] == 50
        assert result['offset'] == 0
        assert result['limit'] == 50

    def test_page_to_offset(self):
        result = parse_list_query(MultiDict({'page': '3', 'page_size': '25'}), [])
        assert result['page'] == 3
        assert result['page_size'] == 25
        assert result['offset'] == 50

    def test_invalid_page_size_falls_back(self):
        result = parse_list_query(MultiDict({'page_size': '7'}), [])
        assert result['page_size'] == 50

    def test_negative_page_clamped(self):
        result = parse_list_query(MultiDict({'page': '-5'}), [])
        assert result['page'] == 1


class TestPageUrl:
    def test_overrides_replace_existing(self):
        args = MultiDict({'q': 'acme', 'page': '1'})
        result = page_url(args, page=3)
        assert 'page=3' in result
        assert 'q=acme' in result
        assert 'page=1' not in result

    def test_empty_override_drops_param(self):
        args = MultiDict({'q': 'acme', 'state': 'posted'})
        result = page_url(args, state='')
        assert 'state=' not in result
        assert 'q=acme' in result

    def test_none_override_drops_param(self):
        args = MultiDict({'q': 'acme'})
        result = page_url(args, q=None)
        assert 'q=' not in result

    def test_url_encodes_values(self):
        args = MultiDict({})
        result = page_url(args, q='hello world')
        assert 'q=hello+world' in result or 'q=hello%20world' in result
