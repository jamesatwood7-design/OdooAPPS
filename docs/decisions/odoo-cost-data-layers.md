# Odoo cost data lives in three layers — query all of them

## Context

The Job Detail page aggregates costs against an `account.analytic.account`. Odoo 17 splits the data this app needs across three separate models. Querying only one (analytic items) understates costs and produces empty PO/Bills tabs even when purchasing activity exists.

## The three layers

1. **`account.analytic.line`** — auto-generated from *posted* vendor bills and timesheets. Reliable for billed cost and labor. **Does not include open POs**, because POs are commitments, not accounting entries — no analytic line exists until the bill is posted.

2. **`purchase.order` / `purchase.order.line`** — where PO commitments live. Each line carries an `analytic_distribution` JSON field, e.g. `{"24": 100.0}` (the key is the analytic account id as a string; the value is a percentage). A line can split across multiple analytics.

3. **`account.move`** with `move_type='in_invoice'` — vendor bills. Each `account.move.line` also carries `analytic_distribution`.

## Querying `analytic_distribution`

`analytic_distribution` is a JSON dict field on every model that inherits `analytic.mixin` (`purchase.order.line`, `account.move.line`, `sale.order.line`, ...). **Don't filter it directly with `ilike`** — Odoo's JSON column isn't reliably text-searchable on all installs (we hit this: an Odoo 17 Enterprise instance returned zero rows for `[('analytic_distribution', 'ilike', '1084')]` even though many lines referenced account 1084).

The searchable companion is the computed Many2many `distribution_analytic_account_ids`, which stores the account ids extracted from the JSON. Use that as the domain filter:

```python
[('distribution_analytic_account_ids', 'in', [account_id])]
```

Then read the raw `analytic_distribution` dict to compute attribution. Keep an `ilike` fallback for the rare install without the Many2many.

**Dict-key verification** still matters for attribution. Odoo 17 keys look like `"24"` or (with Analytic Plans enabled) `"24,42"` — a comma-separated compound key when one line is tagged across plans. Split each key on comma and match any part. This rejects `"242"`/`"124"` false positives while accepting compound keys.

The percentage matters for cost attribution. A line split 60/40 across two jobs contributes 60% of its value to the first job:

- Billed contribution: `line.price_subtotal * pct / 100`.
- Uninvoiced PO commitment: `(product_qty - qty_invoiced) * price_unit * pct / 100`.

Use `qty_invoiced` (financial exposure — what we still owe vendors), not `qty_received` (a receiving-based view we don't want here).

## Why we don't call `project.project._get_profitability_items()`

Odoo exposes a method that returns pre-aggregated revenue/cost data per project. We considered calling it via RPC instead of building our own aggregation. We chose not to, because:

- It's underscore-prefixed (semi-private). Odoo has reorganized this code between major versions and is likely to again.
- It expects a `project.project` record. Our entity is `account.analytic.account`. The mapping `project.project.analytic_account_id` is 1:N and not present for non-project analytics.
- It returns a heavy nested payload we'd then have to reshape.
- It does not expose attribution detail in a way we can verify against the percentage in `analytic_distribution`.

The direct queries are ~30 lines each, debuggable, and keep us in control of attribution. If we ever want to swap, do it for the Financials tab only and mirror the keys the method already returns.

## KPI presentation

- **Billed Costs** = `net_bills + labor_cost`, attributed by percentage. Drives Gross Profit and Margin — those numbers must reflect what's actually on the books.
- **Purchase Orders** = sum of uninvoiced PO commitments, attributed by percentage. Shown alongside Billed Costs so the team sees realized vs. exposure at a glance. Does **not** flow into Gross Profit or Margin.

## Operational notes

- Never wrap an Odoo `search_read` in `except Exception: pass`. Log at WARNING with the analytic account id, the strategy that failed, and the exception. The silent-swallow pattern is exactly what hid this bug.
- After the PO query returns, if it's empty but the job has posted bills, log a warning. Activity in one layer with nothing in the other is almost always a configuration regression worth surfacing.
