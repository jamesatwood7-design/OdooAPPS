"""Totals across a filtered list, computed server-side via read_group.

Pairs with common/list_query.py: the caller passes the same Odoo domain
that was used for the paginated search_read, and receives the total
count and column sums across the *entire* filtered set — not just the
current page.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def compute_list_totals(odoo, model, domain, sum_fields=()):
    """Count + column sums for a filtered result set.

    ``sum_fields`` is a list of Odoo field names whose numeric values
    should be summed. The returned dict always includes ``count`` and a
    ``sums`` dict keyed by field.

    Any read_group failure is logged (so schema changes are visible) and
    yields zeros — the list still renders, just without footer totals.
    """
    result = {'count': 0, 'sums': {field: 0.0 for field in sum_fields}}
    try:
        if sum_fields:
            rows = odoo.read_group(
                model, domain,
                fields=[f'{f}:sum' for f in sum_fields],
                groupby=[],
            )
            if rows:
                row = rows[0]
                result['count'] = row.get('__count', 0) or 0
                for field in sum_fields:
                    result['sums'][field] = row.get(field, 0) or 0.0
        else:
            result['count'] = odoo.execute_kw(model, 'search_count', [domain])
    except Exception as exc:
        logger.warning(
            'compute_list_totals failed for model=%s domain=%s: %s',
            model, domain, exc,
        )
    return result
