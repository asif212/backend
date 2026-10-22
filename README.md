# my_time API

Independent FastAPI repository. Python 3.11+, SQLAlchemy, Alembic; SQLite for development and PostgreSQL through psycopg. No templates or React build dependencies. See [current features and operating rules](FEATURES.md).

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
cp .env.example .env
alembic upgrade head
python -m my_time.cli admin
uvicorn my_time.main:app --reload
```

Interactive API contract: http://localhost:8000/docs. Versioned endpoints: `/api/v1`. Bootstrap an administrator using the CLI, sign in, create a team, then create its lead using `POST /api/v1/teams/{id}/leads` with `role: "lead"`. Leads sign in, change their temporary password, sign in again, create locations and employees. Employee creation supports department, title, joining date, and assigned office. No public registration or default passwords.

Authentication uses revocable opaque bearer sessions, stored hashed in the database. The React client keeps tokens in memory. Password changes revoke all sessions. Browser writes require an explicit Authorization header. Configure exact CORS origins in `.env`; serve over HTTPS in production. API docs deliberately differ from the legacy spec, to support a separate frontend and an inspectable contract.

## Checks

```sh
pytest
alembic check
```

Migrations run explicitly; importing the application never creates tables. Set `RUN_SCHEDULER=true` only on a single process. Keep it disabled on other processes; a dedicated worker and transactional job claiming remain necessary for horizontal scaling. Stored legacy timestamps use naive UTC; attendance work dates use team timezones.

## Existing data and PostgreSQL

Do not point this application at the original database during development. New default SQLite data lives here, separately from the original root database.

1. Stop legacy writes and its scheduler. Make a consistent SQLite backup using SQLite's backup API or `.backup`; copying the `.db` alone can omit WAL data. Verify the backup.
2. Create a new empty destination, set `DATABASE_URL`, and run `alembic upgrade head`.
3. Import the backup into that empty destination:

```sh
python -m my_time.import_legacy --source sqlite:////absolute/path/to/backup.db
```

The importer preserves IDs, copies tables in dependency order, refuses nonempty destinations, skips legacy sessions/rate-limit counters, checks SQLite references, and resets PostgreSQL ID sequences. It wraps inserts in one transaction. Keep the destination URL in the environment; do not place production credentials in shell history. Use a backup as the source, stop writes for cutover, and compare row counts and sample workflows before switching traffic. Large datasets will need streamed import batches. Source schemas with extra custom columns require manual mapping; the importer does not reconcile schema differences.

For PostgreSQL, install project dependencies (includes `psycopg[binary]`), provision an empty database and set `DATABASE_URL=postgresql+psycopg://...`. Changing the URL alone does not migrate data. Actual PostgreSQL runtime and import verification are still required before cutover; local verification used SQLite.

The two new HR tables do not alter legacy tables. Existing users need employee profiles and office assignment before location holidays apply. Legacy team holidays still apply in `/calendar`. The current holiday list endpoint lists location holidays.

## Current limits

This release includes projects/sprints/issues, collaboration and attachments, employee profile editing, leave policies and ledgers, correction approvals, and basic reports. Full Jira/HR parity remains incomplete; [FEATURES.md](FEATURES.md) lists implemented workflows and remaining work. Lists are generally bounded at 200 records; comprehensive pagination remains pending. Login throttling needs atomic enforcement and wider endpoint limits before production. Existing nullable schema constraints and legacy UTC representation require a reviewed follow-up migration. Private profile fields are accessed through dedicated self/lead profile endpoints.
