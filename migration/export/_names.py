"""Display-name helpers for Zoho FK-by-name resolution.

Zoho's CSV/XLSX imports reference customers, vendors, accounts, projects,
items and taxes BY NAME (not by id). Two Odoo partners called "Acme" would
collide, so partner/project/account names always get a `[Odoo #N]` suffix.
This both guarantees uniqueness in Zoho and lets the user trace any Zoho
record back to its Odoo origin.
"""


def partner_display_name(rec):
    """Build a stable, unique display name for a res.partner."""
    name = (rec.get('name') or '').strip() or f"Partner {rec['id']}"
    return f"{name} [Odoo #{rec['id']}]"


def account_display_name(rec):
    """Build a stable, unique display name for an account.account."""
    name = (rec.get('name') or '').strip() or f"Account {rec['id']}"
    code = (rec.get('code') or '').strip()
    if code:
        return f"{code} {name} [Odoo #{rec['id']}]"
    return f"{name} [Odoo #{rec['id']}]"


def project_display_name(rec, prefix='Project'):
    """Build a stable, unique display name for project.project /
    account.analytic.account."""
    name = (rec.get('name') or '').strip() or f"{prefix} {rec['id']}"
    return f"{name} [Odoo #{rec['id']}]"


def tax_display_name(rec):
    """account.tax display name (used as Zoho Tax Name reference)."""
    name = (rec.get('name') or '').strip() or f"Tax {rec['id']}"
    return f"{name} [Odoo #{rec['id']}]"


def invoice_number(rec, prefix='INV'):
    """Use Odoo's name if present (already unique), else synthesize."""
    n = (rec.get('name') or '').strip()
    return n or f"{prefix}-ODOO-{rec['id']}"


def bill_number(rec):
    """Vendor bills prefer vendor reference, fall back to Odoo name."""
    return ((rec.get('ref') or '').strip()
            or (rec.get('name') or '').strip()
            or f"BILL-ODOO-{rec['id']}")
