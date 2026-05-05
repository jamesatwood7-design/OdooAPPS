"""Schema-driven list-query parsing.

Every list page declares a small list of facets describing how URL query
parameters map onto Odoo domain filters. parse_list_query() turns
request.args into a domain + order + offset + limit + resolved-filter
dict ready to pass through to search_read().

Keeping this centralised means new lists don't have to reimplement
pagination, sort parsing, or the "active filter" values needed by the
template.
"""
from __future__ import annotations

from urllib.parse import urlencode


VALID_PAGE_SIZES = (25, 50, 100)
DEFAULT_PAGE_SIZE = 50


def search_facet(param, fields, placeholder='Search…', label='Search'):
    return {
        'kind': 'search',
        'param': param,
        'fields': list(fields),
        'placeholder': placeholder,
        'label': label,
    }


def select_facet(param, field, options, label=None):
    return {
        'kind': 'select',
        'param': param,
        'field': field,
        'options': list(options),
        'label': label or field.replace('_', ' ').title(),
    }


def m2o_facet(param, field, options=None, label=None):
    """Many-to-one facet. When `options` is supplied (list of (id, label)),
    the filter form renders a dropdown; otherwise it hides the control and
    only reacts to direct URL params (e.g. drill-down links)."""
    return {
        'kind': 'm2o',
        'param': param,
        'field': field,
        'options': list(options) if options else None,
        'label': label or field.replace('_', ' ').title(),
    }


def date_range_facet(param_from, param_to, field,
                     label_from='From', label_to='To'):
    return {
        'kind': 'date_range',
        'param_from': param_from,
        'param_to': param_to,
        'field': field,
        'label_from': label_from,
        'label_to': label_to,
    }


def _coerce_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_list_query(args, facets, sort_map=None,
                     default_sort=None, default_page_size=DEFAULT_PAGE_SIZE):
    """Parse request.args into a filter/sort/pagination bundle.

    `facets` is a list of dicts produced by the factory helpers above.
    `sort_map` is a dict mapping short sort keys to Odoo field names,
    e.g. {'date': 'invoice_date', 'amount': 'amount_total'}.
    `default_sort` is a key like 'date_desc' or just 'date' (desc is
    the implicit default).

    Returns a dict with:
      domain, order, limit, offset, page, page_size, filters, sort, q
    """
    sort_map = sort_map or {}
    domain = []
    filters = {}
    q = ''

    for facet in facets:
        kind = facet['kind']
        if kind == 'search':
            value = (args.get(facet['param']) or '').strip()
            if value:
                q = value
                filters[facet['param']] = value
                # OR across all searchable fields: ['|', '|', (f1), (f2), (f3)]
                fields = facet['fields']
                if len(fields) == 1:
                    domain.append((fields[0], 'ilike', value))
                else:
                    clause = ['|'] * (len(fields) - 1)
                    for field in fields:
                        clause.append((field, 'ilike', value))
                    domain.extend(clause)
        elif kind == 'select':
            value = (args.get(facet['param']) or '').strip()
            if value:
                filters[facet['param']] = value
                domain.append((facet['field'], '=', value))
        elif kind == 'm2o':
            value = _coerce_int(args.get(facet['param']))
            if value:
                filters[facet['param']] = value
                domain.append((facet['field'], '=', value))
        elif kind == 'date_range':
            df = (args.get(facet['param_from']) or '').strip()
            dt = (args.get(facet['param_to']) or '').strip()
            if df:
                filters[facet['param_from']] = df
                domain.append((facet['field'], '>=', df))
            if dt:
                filters[facet['param_to']] = dt
                domain.append((facet['field'], '<=', dt))

    sort_raw = (args.get('sort') or '').strip() or default_sort or ''
    sort_key, sort_dir = _parse_sort(sort_raw)
    order = None
    if sort_key and sort_key in sort_map:
        order = f'{sort_map[sort_key]} {sort_dir}'
        filters['sort'] = f'{sort_key}_{sort_dir}'

    page = max(1, _coerce_int(args.get('page'), 1))
    page_size = _coerce_int(args.get('page_size'), default_page_size)
    if page_size not in VALID_PAGE_SIZES:
        page_size = default_page_size
    offset = (page - 1) * page_size

    return {
        'domain': domain,
        'order': order,
        'limit': page_size,
        'offset': offset,
        'page': page,
        'page_size': page_size,
        'filters': filters,
        'sort': f'{sort_key}_{sort_dir}' if sort_key else '',
        'q': q,
    }


def _parse_sort(raw):
    """Parse 'date_desc' / 'date_asc' / 'date' into (key, direction)."""
    if not raw:
        return None, 'desc'
    if raw.endswith('_desc'):
        return raw[:-5], 'desc'
    if raw.endswith('_asc'):
        return raw[:-4], 'asc'
    return raw, 'desc'


def page_url(args, **overrides):
    """Build a query string from the current request.args with overrides.

    Empty / None values are dropped so the URL stays clean. The helper is
    registered as a Jinja global so templates can write
    ``<a href="?{{ page_url(request.args, page=2) }}">`` without worrying
    about urlencoding.
    """
    merged = {}
    if hasattr(args, 'items'):
        for key, value in args.items():
            merged[key] = value
    for key, value in overrides.items():
        if value is None or value == '':
            merged.pop(key, None)
        else:
            merged[key] = value
    return urlencode(merged, doseq=True)
