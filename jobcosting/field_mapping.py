"""Dynamic discovery and mapping of custom fields on account.analytic.account.

Odoo custom fields are prefixed with x_ or x_studio_. This module uses
fields_get to discover them at runtime and maps human-readable labels
to technical field names, so the app works regardless of exact naming.
"""

import re


# Dashboard columns: (display_label, odoo_label_to_match, sort_type)
# sort_type is used by the JS for client-side sorting
DASHBOARD_COLUMNS = [
    ('Code', 'code', 'text'),
    ('Job Name', 'name', 'text'),
    ('Customer', 'Customer', 'text'),
    ('Building Type', 'Building Type', 'text'),
    ('Sq Ft', 'Square Footage', 'number'),
    ('Started', 'Date Started', 'date'),
    ('Completed', 'Date Completed', 'date'),
    ('Sales Price', 'Current Sales Price', 'currency'),
    ('Expenses', 'Total Expenses', 'currency'),
    ('Margin', 'Current Margin', 'currency'),
    ('Margin %', 'Actual Margin', 'percent'),
    ('Profit', 'Actual Profit', 'currency'),
    ('Projected Profit', 'Projected Profit', 'currency'),
    ('Salesman', 'Salesman', 'text'),
]

# Detail page sections: (section_name, [(display_label, odoo_label_to_match)])
DETAIL_SECTIONS = [
    ('Job Information', [
        ('Customer', 'Customer'),
        ('Square Footage', 'Square Footage'),
        ('Building Type', 'Building Type'),
        ('Date Started', 'Date Started'),
        ('Date Completed', 'Date Completed'),
        ('Salesman', 'Salesman'),
    ]),
    ('Revenue & Pricing', [
        ('Revenue per Sq Ft', 'Revenue per Sq'),
        ('Current Sales Price', 'Current Sales Price'),
        ('Last Project Sales Price', 'Last Project Sales'),
        ('Last Offered Sales Price', 'Last Offered Sales'),
        ('Overhead Sales Price', 'Overhead Sales Price'),
        ('Primer P1', 'Primer P1'),
    ]),
    ('Change Orders', [
        ('Change Order #1', 'Change Order #1'),
        ('CO #1 Description', 'CO P1 Description'),
        ('Change Order #2', 'Change Order #2'),
        ('CO #2 Description', 'CO P2 Description'),
    ]),
    ('Expenses & Margins', [
        ('Subcontracting to Invoice', 'Subcontracting to Invoice'),
        ('Total Expenses', 'Total Expenses'),
        ('Guard Rail Expenses', 'Guard'),
        ('Current Margin', 'Current Margin'),
        ('Actual Margin %', 'Actual Margin'),
        ('Actual Profit', 'Actual Profit'),
        ('Projected Profit', 'Projected Profit'),
    ]),
    ('Commissions', [
        ('Commission Check', 'Commission Check'),
        ('Commission Paid', 'Commission Paid'),
    ]),
]


def _normalize(label):
    """Normalize a label for fuzzy matching: lowercase, strip non-alphanumeric."""
    return re.sub(r'[^a-z0-9]', '', label.lower())


def get_custom_field_map(odoo):
    """Discover all custom fields on account.analytic.account.

    Returns a dict mapping normalized labels to field info:
    {
        'squarefootage': {
            'technical_name': 'x_studio_square_footage',
            'label': 'Square Footage',
            'type': 'float',
            'selection': [(value, label), ...] or None,
        },
        ...
    }

    Results are cached via OdooClient's _model_fields_cache.
    """
    all_fields = odoo.fields_get('account.analytic.account',
                                 attributes=['string', 'type', 'selection'])

    custom_map = {}
    for tech_name, info in all_fields.items():
        label = info.get('string', '')
        normalized = _normalize(label)
        if not normalized:
            continue

        custom_map[normalized] = {
            'technical_name': tech_name,
            'label': label,
            'type': info.get('type', 'char'),
            'selection': info.get('selection') or None,
        }

    return custom_map


def resolve_field(field_map, desired_label):
    """Find the technical field name matching a desired label.

    Uses fuzzy matching: tries exact normalized match first, then
    checks if the desired label is contained within any field label.

    Returns (technical_name, field_info) or (None, None) if not found.
    """
    normalized = _normalize(desired_label)

    # Exact match
    if normalized in field_map:
        info = field_map[normalized]
        return info['technical_name'], info

    # Substring match: find the first field whose normalized label contains our query
    for norm_label, info in field_map.items():
        if normalized in norm_label or norm_label in normalized:
            return info['technical_name'], info

    return None, None


def resolve_dashboard_columns(odoo):
    """Resolve dashboard column definitions to actual Odoo field names.

    Returns:
        columns: [(display_label, technical_name, sort_type, field_info), ...]
        technical_names: [list of technical field names to request from Odoo]
    """
    field_map = get_custom_field_map(odoo)
    columns = []
    technical_names = set()

    # Always include standard fields
    standard_fields = {'id', 'name', 'code'}
    technical_names.update(standard_fields)

    for display_label, odoo_label, sort_type in DASHBOARD_COLUMNS:
        # Standard fields
        if odoo_label in ('code', 'name'):
            columns.append((display_label, odoo_label, sort_type, None))
            continue

        tech_name, field_info = resolve_field(field_map, odoo_label)
        if tech_name:
            columns.append((display_label, tech_name, sort_type, field_info))
            technical_names.add(tech_name)

    return columns, list(technical_names)


def resolve_detail_sections(odoo):
    """Resolve detail page section definitions to actual Odoo field names.

    Returns:
        sections: [(section_name, [(display_label, technical_name, field_info), ...]), ...]
        technical_names: [list of all technical field names to request]
    """
    field_map = get_custom_field_map(odoo)
    sections = []
    technical_names = set(['id', 'name', 'code'])

    for section_name, field_defs in DETAIL_SECTIONS:
        resolved_fields = []
        for display_label, odoo_label in field_defs:
            tech_name, field_info = resolve_field(field_map, odoo_label)
            if tech_name:
                resolved_fields.append((display_label, tech_name, field_info))
                technical_names.add(tech_name)

        if resolved_fields:
            sections.append((section_name, resolved_fields))

    return sections, list(technical_names)


def format_odoo_value(value, field_info):
    """Format an Odoo field value for display based on its type.

    Handles Many2one tuples, selection fields, booleans, etc.
    """
    if value is None or value is False:
        return ''

    if field_info is None:
        # Standard field, just return string
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return str(value[1])
        return str(value)

    field_type = field_info.get('type', 'char')

    # Many2one: [id, display_name]
    if isinstance(value, (list, tuple)) and len(value) == 2:
        return str(value[1])

    # Selection: look up the label
    if field_type == 'selection' and field_info.get('selection'):
        sel_map = dict(field_info['selection'])
        return sel_map.get(value, str(value))

    # Boolean
    if field_type == 'boolean':
        return 'Yes' if value else 'No'

    # Float/monetary
    if field_type in ('float', 'monetary'):
        try:
            return f'{float(value):,.2f}'
        except (ValueError, TypeError):
            return str(value)

    # Integer
    if field_type == 'integer':
        try:
            return f'{int(value):,}'
        except (ValueError, TypeError):
            return str(value)

    return str(value)
