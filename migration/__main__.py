"""CLI entrypoint: python -m migration ..."""
import argparse
import os
import sys

from config import Config
from common.odoo_api import OdooClient
from migration.id_map import IdMap
from migration.logging_setup import setup_logging
from migration.zoho_client import ZohoBooksClient
from migration import orchestrator


def _build_clients(dry_run):
    odoo = OdooClient(Config.ODOO_URL, Config.ODOO_DB,
                      Config.ODOO_USERNAME, Config.ODOO_PASSWORD)
    odoo.authenticate()
    zoho = None
    if not _missing_zoho_creds():
        zoho = ZohoBooksClient(
            client_id=Config.ZOHO_CLIENT_ID,
            client_secret=Config.ZOHO_CLIENT_SECRET,
            refresh_token=Config.ZOHO_REFRESH_TOKEN,
            org_id=Config.ZOHO_ORG_ID,
            region=Config.ZOHO_REGION,
            dry_run=dry_run,
        )
    elif not dry_run:
        raise SystemExit(
            'Missing Zoho credentials. Set ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, '
            'ZOHO_REFRESH_TOKEN, ZOHO_ORG_ID in .env, or pass --dry-run.'
        )
    return odoo, zoho


def _missing_zoho_creds():
    return not all([
        Config.ZOHO_CLIENT_ID, Config.ZOHO_CLIENT_SECRET,
        Config.ZOHO_REFRESH_TOKEN, Config.ZOHO_ORG_ID,
    ])


def _id_map_path():
    return os.path.join(Config.MIGRATION_STATE_DIR, 'id_map.sqlite')


def _log_dir():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(repo_root, 'logs')


def cmd_run(args):
    logger = setup_logging(_log_dir(), verbose=args.verbose)
    odoo, zoho = _build_clients(dry_run=args.dry_run)
    id_map = IdMap(_id_map_path())

    phases = [p.strip() for p in args.phase.split(',')] if args.phase else ['all']
    zoho_user_id = (args.zoho_user_id
                    or os.environ.get('MIGRATION_ZOHO_USER_ID', ''))
    if 'analytic_lines' in phases or 'all' in phases:
        if not zoho_user_id and not args.dry_run:
            logger.warning(
                'analytic_lines phase requires --zoho-user-id or '
                'MIGRATION_ZOHO_USER_ID; phase will be skipped.'
            )
            phases = [p for p in phases if p != 'analytic_lines']
            if 'all' in phases:
                phases = [n for n in orchestrator.PHASE_NAMES if n != 'analytic_lines']

    summary = orchestrator.run(
        odoo, zoho, id_map, logger,
        phases=phases, dry_run=args.dry_run,
        zoho_user_id=zoho_user_id or 'DRYRUN-USER',
    )
    logger.info('=== summary ===')
    for name, counts in summary.items():
        logger.info('  %s: %s', name, counts)
    id_map.close()
    return 0


def cmd_status(args):
    id_map = IdMap(_id_map_path())
    rows = id_map.counts()
    if not rows:
        print('id_map is empty')
    else:
        print(f"{'zoho_type':<20} {'status':<10} {'count':>8}")
        for r in rows:
            print(f"{r['zoho_type']:<20} {r['status']:<10} {r['c']:>8}")
    id_map.close()
    return 0


def cmd_failed(args):
    id_map = IdMap(_id_map_path())
    rows = id_map.iter_failed(args.model)
    for r in rows:
        print(f"{r['odoo_model']}#{r['odoo_id']} ({r['variant']}): {r['error']}")
    print(f'\n{len(rows)} failed record(s)')
    id_map.close()
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m migration',
        description='One-time Odoo -> Zoho Books data migration.',
    )
    sub = parser.add_subparsers(dest='cmd', required=True)

    run_p = sub.add_parser('run', help='Run migration phases')
    run_p.add_argument('--phase', default='all',
                       help=f"Comma-separated phases or 'all'. "
                            f"Available: {','.join(orchestrator.PHASE_NAMES)}")
    run_p.add_argument('--dry-run', action='store_true',
                       help='Pull from Odoo and log payloads without calling Zoho')
    run_p.add_argument('-v', '--verbose', action='store_true')
    run_p.add_argument('--zoho-user-id', default='',
                       help='Zoho user id to attribute time entries to')
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser('status', help='Show id_map counts')
    status_p.set_defaults(func=cmd_status)

    failed_p = sub.add_parser('failed', help='List failed records')
    failed_p.add_argument('--model', default=None)
    failed_p.set_defaults(func=cmd_failed)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
