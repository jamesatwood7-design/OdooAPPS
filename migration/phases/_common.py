"""Shared helpers for phase modules."""
import logging
from migration.logging_setup import log_record


def paginate(odoo, model, domain, fields, page_size=200, order='id'):
    """Yield batches of records using safe_search_read with pagination."""
    offset = 0
    while True:
        batch = odoo.safe_search_read(
            model, domain, fields=fields,
            offset=offset, limit=page_size, order=order,
        )
        if not batch:
            return
        for rec in batch:
            yield rec
        if len(batch) < page_size:
            return
        offset += len(batch)


def extract_zoho_id(response, key):
    """Pull the new record's id from a Zoho create response.

    Zoho responses look like: {"code": 0, "message": "...", "<key>": {...}}
    where the inner dict has a `*_id` field.
    """
    if not isinstance(response, dict):
        return None
    if response.get('_dry_run'):
        path = response.get('path', '')
        return f"DRYRUN-{path.replace('/', '-')}"
    payload = response.get(key)
    if not isinstance(payload, dict):
        # Some Zoho endpoints return the object at the top level.
        payload = response
    for k, v in payload.items():
        if k.endswith('_id') and v:
            return str(v)
    return None


def record_success(logger, id_map, odoo_model, odoo_id, zoho_type, zoho_id,
                   variant=''):
    id_map.put(odoo_model, odoo_id, zoho_type, zoho_id,
               status='created', variant=variant)
    log_record(
        logger, logging.INFO,
        f"created {zoho_type} for {odoo_model}#{odoo_id} -> {zoho_id}",
        action='created', odoo_model=odoo_model, odoo_id=odoo_id,
        zoho_type=zoho_type, zoho_id=zoho_id, variant=variant,
    )


def record_skip(logger, odoo_model, odoo_id, zoho_id, variant=''):
    log_record(
        logger, logging.DEBUG,
        f"skip {odoo_model}#{odoo_id} (already migrated as {zoho_id})",
        action='skipped', odoo_model=odoo_model, odoo_id=odoo_id,
        zoho_id=zoho_id, variant=variant,
    )


def record_failure(logger, id_map, odoo_model, odoo_id, error, zoho_type='',
                   variant=''):
    id_map.mark_failed(odoo_model, odoo_id, error,
                       variant=variant, zoho_type=zoho_type)
    log_record(
        logger, logging.ERROR,
        f"FAILED {odoo_model}#{odoo_id}: {error}",
        action='failed', odoo_model=odoo_model, odoo_id=odoo_id,
        zoho_type=zoho_type, variant=variant, error=str(error),
    )
