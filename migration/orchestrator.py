import logging

from migration.phases import (
    accounts, taxes, contacts, projects, analytic_accounts,
    moves, payments, analytic_lines,
)


# Ordered list of (phase_name, module). Order matters for dependency resolution.
PHASE_ORDER = [
    ('accounts', accounts),
    ('taxes', taxes),
    ('contacts', contacts),
    ('projects', projects),
    ('analytic_accounts', analytic_accounts),
    ('moves', moves),
    ('payments', payments),
    ('analytic_lines', analytic_lines),
]

PHASE_NAMES = [name for name, _ in PHASE_ORDER]


def run(odoo, zoho, id_map, logger, phases=None, dry_run=False,
        zoho_user_id=None):
    """Run the requested phases in order. Returns dict of phase->counts."""
    if phases is None or 'all' in phases:
        selected = PHASE_ORDER
    else:
        selected = [(n, m) for n, m in PHASE_ORDER if n in phases]
        unknown = set(phases) - set(PHASE_NAMES) - {'all'}
        if unknown:
            raise ValueError(f'Unknown phase(s): {sorted(unknown)}')

    summary = {}
    for name, module in selected:
        logger.info('--- phase: %s ---', name)
        if name == 'analytic_lines':
            counts = module.migrate(odoo, zoho, id_map, dry_run, logger,
                                    zoho_user_id=zoho_user_id)
        else:
            counts = module.migrate(odoo, zoho, id_map, dry_run, logger)
        summary[name] = counts
        logger.log(
            logging.INFO,
            'phase %s done: created=%d skipped=%d failed=%d',
            name, counts['created'], counts['skipped'], counts['failed'],
        )
    return summary
