# Zoho Books Migration Setup

How to wire the `python -m migration` tool to a Zoho Books organization.

## 1. Find your data center

Open Zoho Books in a browser and check the URL bar:

| URL host           | Region | `ZOHO_REGION` value |
|--------------------|--------|---------------------|
| books.zoho.com     | US     | `US`                |
| books.zoho.eu      | EU     | `EU`                |
| books.zoho.in      | IN     | `IN`                |
| books.zoho.com.au  | AU     | `AU`                |
| books.zoho.jp      | JP     | `JP`                |

Use the matching `accounts.zoho.<tld>` and `api-console.zoho.<tld>` hosts in the next steps.

## 2. Find your organization id

In Zoho Books, **Settings → Organizations**. Each org has a numeric ID
shown on the org list page; copy it into `ZOHO_ORG_ID`.

## 3. Register a Self-Client and get a refresh token

The migration is a server-to-server one-shot, so use Zoho's "Self Client"
flow (no redirect URI, no user prompts).

1. Open `https://api-console.zoho.<tld>/` (US: `.com`, EU: `.eu`, etc.)
   and sign in as the Zoho Books admin.
2. **Add Client → Self Client → Create**.
3. Copy the **Client ID** and **Client Secret** into
   `ZOHO_CLIENT_ID` / `ZOHO_CLIENT_SECRET`.
4. Switch to the **Generate Code** tab on that same Self Client and enter:
   - **Scope**: `ZohoBooks.fullaccess.all`
   - **Time Duration**: `10 minutes` (the code expires fast, the refresh
     token does not)
   - **Scope Description**: anything, e.g. `Odoo migration`
   - Click **Create**, pick your org, copy the generated **code**.
5. Exchange that code for a refresh token. From a shell:

   ```bash
   curl -s -X POST "https://accounts.zoho.<tld>/oauth/v2/token" \
     -d "code=<THE_CODE_FROM_STEP_4>" \
     -d "client_id=<YOUR_CLIENT_ID>" \
     -d "client_secret=<YOUR_CLIENT_SECRET>" \
     -d "grant_type=authorization_code"
   ```

   The response includes a `refresh_token`. Copy it into
   `ZOHO_REFRESH_TOKEN`. Refresh tokens do not expire unless revoked, so
   you only do this once.

## 4. (Required for `analytic_lines` phase) find a Zoho user id

Time entries must be attributed to a Zoho user. The script doesn't try
to map Odoo employees 1:1 onto Zoho users — instead, pass one fallback
user id with `--zoho-user-id`.

```bash
ACCESS_TOKEN=$(curl -s -X POST "https://accounts.zoho.<tld>/oauth/v2/token" \
  -d "refresh_token=$ZOHO_REFRESH_TOKEN" \
  -d "client_id=$ZOHO_CLIENT_ID" \
  -d "client_secret=$ZOHO_CLIENT_SECRET" \
  -d "grant_type=refresh_token" | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s "https://www.zohoapis.<tld>/books/v3/users?organization_id=$ZOHO_ORG_ID" \
  -H "Authorization: Zoho-oauthtoken $ACCESS_TOKEN" | python -m json.tool
```

Pick a `user_id` from the JSON; pass it with `--zoho-user-id <id>` or set
`MIGRATION_ZOHO_USER_ID=<id>` in `.env`.

## 5. Fill in `.env`

```dotenv
ZOHO_CLIENT_ID=1000.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ZOHO_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
ZOHO_REFRESH_TOKEN=1000.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx.yyyy
ZOHO_ORG_ID=1234567890
ZOHO_REGION=US
MIGRATION_ZOHO_USER_ID=999000111
```

## 6. Smoke test

```bash
pip install -r requirements.txt
python -m migration run --dry-run --phase=accounts
```

If you see `phase accounts done: created=N skipped=0 failed=0` and a
fresh `logs/migration-<date>.jsonl` with N entries, credentials and
network are good.

## 7. Recommended cutover order

1. **Sandbox first.** Create a separate Zoho Books org and run a small
   subset (`--phase=accounts,taxes,contacts`) against it. Spot-check the
   UI for shape and field placement.
2. **Production dry run.** Against the real production Zoho org id, run
   `python -m migration run --dry-run --phase=all`. Review
   `logs/migration-*.jsonl` for the actual payloads we'd send. The dry
   run touches Odoo (read-only) and never calls Zoho.
3. **Real run, in phases.** Real cutover is cheapest run in stages so
   you can stop early if anything is off:
   ```bash
   python -m migration run --phase=accounts
   python -m migration run --phase=taxes
   python -m migration run --phase=contacts
   python -m migration run --phase=projects,analytic_accounts
   python -m migration run --phase=moves        # historical
   python -m migration run --phase=payments
   python -m migration run --phase=analytic_lines --zoho-user-id=<id>
   ```
4. **Check progress / failures.**
   ```bash
   python -m migration status         # counts per zoho_type and status
   python -m migration failed         # any rows with status=failed
   python -m migration failed --model account.move
   ```
5. **Re-run is safe.** The id_map (`migration/state/id_map.sqlite`)
   makes every phase idempotent — re-running skips records already
   created.

## 8. Rate limits

Zoho Books enforces ~100 API calls/minute per organization. The client
already token-buckets at this limit and respects `Retry-After` headers
on 429s. For a *Free Plan* org there is also a hard 1000-calls/day cap
(Standard / Premium plans raise this substantially); if you're on Free,
plan to spread historical transactions across multiple days or upgrade
the plan before the cutover.

## 9. What gets migrated

| Odoo                                        | Zoho Books                |
|---------------------------------------------|---------------------------|
| `account.account` (non-deprecated)          | Chart of accounts         |
| `account.tax` (active; children before groups) | Taxes / tax groups     |
| `res.partner` (customer_rank or supplier_rank) | Contacts (one per role) |
| `project.project`                           | Projects                  |
| `account.analytic.account` (active, standalone) | Projects (cost centers) |
| `account.move` (state=posted), all move_types except `entry`-only and tasks | Invoices / Bills / Credit Notes / Vendor Credits / Manual Journals |
| `account.payment` (posted / paid / reconciled) | Customer & Vendor payments, attached to invoices/bills via the id_map |
| `account.analytic.line` (unit_amount > 0)   | Time entries on Zoho projects |

`project.task`, attachments, inventory, manufacturing, HR/payroll, and
CRM data are intentionally **out of scope**.
