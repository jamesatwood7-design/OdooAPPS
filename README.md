# Odoo Time Clock & Job Costing Applications

Two web applications that connect to your Odoo ERP instance via XML-RPC API:

1. **Time Clock** - Employee clock in/out, attendance tracking, daily and weekly hour summaries
2. **Job Costing** - Analytic items management, project cost tracking, budget vs. actual reports

## Requirements

- Python 3.9+
- Access to an Odoo instance (v14+) with HR Attendance and Project/Accounting modules enabled

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the example environment file and update it with your Odoo connection details:

```bash
cp .env.example .env
```

Edit `.env` with your settings:

```
ODOO_URL=https://your-odoo-instance.com
ODOO_DB=your_database_name
ODOO_USERNAME=your_api_user
ODOO_PASSWORD=your_api_password
FLASK_SECRET_KEY=generate-a-random-secret-key
FLASK_DEBUG=0
```

### 3. Run the Application

```bash
python app.py
```

The application will start at `http://localhost:5000`.

## Odoo Module Requirements

Ensure these modules are installed on your Odoo instance:

- **Attendances** (`hr_attendance`) - Required for the Time Clock app
- **Project** (`project`) - Required for the Job Costing app
- **Accounting / Analytic Accounting** (`analytic`) - Required for analytic items and job costing

The API user configured in `.env` needs read/write access to these models:
- `hr.employee`
- `hr.attendance`
- `project.project`
- `project.task`
- `account.analytic.account`
- `account.analytic.line`

## Application Features

### Time Clock (`/timeclock/`)

- **Dashboard** - Select an employee, view current status (clocked in/out), clock in or out with a single click
- **Live Timer** - When clocked in, a live elapsed timer updates every second
- **Attendance History** - Browse attendance records with date range filters
- **Hour Summaries** - View daily breakdown and weekly totals with visual progress bars

### Job Costing (`/jobcosting/`)

- **Dashboard** - Overview of all projects showing budgeted hours, actual hours, costs, and budget utilization
- **Project Detail** - View tasks with planned vs. actual hours, recent analytic entries, and budget progress
- **Analytic Accounts** - Browse analytic accounts with debit/credit balances
- **Create Entries** - Add time entries (with hourly rate calculation) or expense entries against projects and tasks
- **Budget vs. Actual Reports** - Per-task breakdown with Chart.js bar charts, variance analysis, and cost summaries
- **Cascading Dropdowns** - Selecting a project auto-loads its tasks and analytic account

## Project Structure

```
OdooAPPS/
├── app.py                  # Flask application factory
├── config.py               # Configuration from environment variables
├── common/
│   ├── odoo_api.py         # XML-RPC client (OdooClient class)
│   ├── exceptions.py       # Custom exception classes
│   └── utils.py            # Date/time formatting helpers
├── timeclock/
│   ├── routes.py           # Time clock HTTP endpoints
│   └── services.py         # Time clock business logic
├── jobcosting/
│   ├── routes.py           # Job costing HTTP endpoints
│   └── services.py         # Job costing business logic
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS and JavaScript
└── tests/                  # Pytest test suite
```

## Running Tests

```bash
python -m pytest tests/ -v
```

Tests use mocked Odoo client - no live Odoo connection needed.

## Tech Stack

- **Backend**: Python, Flask, xmlrpc.client (standard library)
- **Frontend**: Bootstrap 5 (CDN), vanilla JavaScript, Chart.js (CDN)
- **API**: Odoo XML-RPC (`/xmlrpc/2/common`, `/xmlrpc/2/object`)
