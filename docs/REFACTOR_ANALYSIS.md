# Repository assessment and implementation plan

This document records the initial repository assessment. The implementation has since expanded; use [the current feature inventory](../FEATURES.md) for delivered capabilities, verification and remaining scope.

## Recommendation

Use two repositories: a React/TypeScript client and a modular FastAPI application, with one PostgreSQL database. Keep authorization, approvals, attendance calculations, workflow transitions and audit writes in the API. Use versioned OpenAPI as the integration contract; generate TypeScript types once the schemas stabilize. Avoid microservices initially: leave approval, balances, calendars and attendance require consistent transactions.

Keep modules for identity/organization, projects/workflows, time/attendance, HR/leave, notifications and audit/reporting. Separate routers, domain services and persistence as each module grows; the initial API is centralized and should be decomposed as the contract stabilizes. Use a dedicated scheduler worker before scaling API processes. Use object storage for documents/attachments and a durable outbox for eventual email/integration delivery.

The first organization boundary currently remains `team_id`, matching existing data. Before supporting multiple teams within one company, introduce organizations, memberships and project permissions with an explicit migration. Do not treat teams as companies indefinitely or grant HR access through project membership. HR permissions need field-level access for compensation, identity documents and private leave information.

## What exists in the legacy code

| Area | Current implementation | Gaps found |
|---|---|---|
| Architecture | FastAPI, synchronous SQLAlchemy, Jinja/HTMX pages | No frontend separation, packaging, migration revisions or API contract for normal users |
| Identity | Argon2, lead/member/super-admin, database sessions | Raw tokens in login routes; unrelated random hash in unused session helper; absolute lifetime absent; inconsistent revocation; no forced-change enforcement on domain routes |
| Authorization | Many team-filtered queries | Task creation/reassignment accepts foreign assignees; member status route accepts arbitrary strings; organization-level model absent |
| Tasks | Assignment, estimates, due dates, four statuses, events | No projects, issue keys, hierarchy, sprint/backlog, comments, attachments, worklogs, custom fields or workflow definitions |
| Attendance | Geofence check-in/out, one row per user/date, correction model | Uses UTC work date; auto-checkout is a placeholder; no shift roster, breaks, regularization UI or complete calendar/reporting |
| Leave | Requests and single lead decisions | No date validation/overlap protection; arbitrary decisions; no balances, types, accrual, carry-forward or approval chains |
| Locations/holidays | Team work locations and team holiday model | No employee office assignment or office holiday CRUD in current routes |
| Scheduler | Task/attendance interval overlap calculation | Missing overrun notifications, auto-close, cleanup, concurrency control and bounded queries |
| Database | SQLite, WAL, create_all at module import | SQLite connection options applied unconditionally; no production migration process; nullable fields and string statuses need tightening |
| Security/operations | Audit/notification/rate-limit tables | Tables do not mean complete enforcement; default reset password, GET logout, no demonstrated CSRF layer, incomplete audit, no visible CI/deployment config |
| Tests | Scheduler, super-admin API, web smoke tests | Sparse negative/security coverage; test DB filename shared with root data; import-time DB creation |

Evidence reviewed: `src/my_time/{main,db,config,cli}.py`, all models, routes, security modules, location service, scheduler, templates, existing tests and `SPEC (1).md`. No employee data or password hashes needed to be read from the existing database. Patch scripts and reset scripts remain legacy utilities; do not carry them into production delivery.

## Implemented in this split

- Independently packaged FastAPI backend and React/Vite frontend, with separate dependency files, examples and run instructions.
- Versioned JSON endpoints, OpenAPI docs, configured exact CORS origins, explicit migrations, SQLite/PostgreSQL driver selection, health endpoint.
- Opaque bearer authentication with hashed storage, idle/absolute expiry, logout, session revocation, mandatory first password change and team suspension checks. Basic persistent login throttling.
- Admin team and lead provisioning; lead employee creation with profile and office metadata.
- Task create/list/board/status transitions, same-team active assignee validation, event history writes, task assignment/block notifications.
- Geofenced JSON attendance, bounded input coordinates and accuracy, team-local work dates, duplicate/open-session checks, timezone/overnight auto-close with audit.
- Leave requests, date validation, overlap checks, immutable final decision, no self-approval, scoped notifications and audit entries.
- Office holiday creation/listing and employee office mapping; attendance calendar API resolves working days, team/office holidays, approved leave and actual attendance.
- New empty-database migrations and a legacy data importer preserving IDs and revoking legacy sessions.
- Backend integration tests for isolation, authentication, transitions, leave decisions, geofencing, holidays, auto-close and import safety.

The frontend includes sign-in/password-change, basic admin team creation, task board, attendance, leave/approval, employees, locations and holidays. Lead provisioning, calendar and notifications are API-only in this release. The initial split intentionally leaves the original application usable for comparison and rollback; no database was cut over.

## Complete product backlog

These are required follow-up capabilities, not claims of implemented functionality.

| Phase | Scope | Acceptance criteria |
|---|---|---|
| 1: migration foundation | Two repositories, contract, auth, domain workflow APIs, migration rehearsal | Both build independently; parity inventory; isolation tests; reviewed staging data import; rollback demonstrated |
| 2: organization and HR core | Companies, teams/departments, offices/timezones, reporting managers, employment records, employee lifecycle, HR/manager roles, restricted documents, profile editing/import | Multiple teams per company; no private HR field leakage; onboarding/offboarding revokes access; permission matrix tested |
| 3: Jira work management | Projects/keys, epic/story/task/bug/subtask hierarchy, components/releases, labels, priorities, comments/mentions, attachments, watchers, links/dependencies, custom fields/workflows, project permissions | Consistent issue keys under concurrency, transition permissions/history, search/filter API and accessible boards |
| 4: agile planning | Backlog ordering, Scrum sprints, Kanban WIP limits, estimates/story points, sprint start/close, release planning, roadmaps, velocity/burndown/cycle-time reports | Historical sprint snapshots; reliable metrics; carry-over on sprint close; cross-project permission checks |
| 5: attendance depth | Shift templates/rosters, overnight shifts, breaks, overtime, grace/late/early rules, remote work, attendance corrections/approvals, timesheets, reports, biometric import adapters | DST/timezone tests; approved corrections preserve originals; payroll-ready period export; configurable location consent/retention |
| 6: leave automation | Leave types, eligibility, policy assignment by country/location/employment class, monthly/yearly accrual, probation, opening balances, half-days/hours, proration, carry-forward/expiry, negative balances, cancellation and reversals | Immutable balance ledger with unique accrual period keys; atomic reservation/debit; repeat-safe jobs; working-day/holiday calculation; auditable policy versions |
| 7: calendars and approvals | Location holiday calendars by year, bulk holiday import, optional/restricted holidays, employee transfers with effective dates, multi-step approvals, delegates, escalation and reminders | No auto-assumed legal calendar; explicit HR publication; no retroactive changes to posted balances; approval idempotency and no self-approval |
| 8: broader HR | Onboarding/checklists, probation, documents/assets, offboarding, performance cycles, objectives/reviews, expense approvals, HR helpdesk, optional recruitment | Restricted access, complete change history, configurable workflows; define country-specific payroll as a separate integration project |
| 9: platform and production | SSO/OIDC/MFA, enterprise permissions, atomic rate limiting, outbox/queue, WebSocket events, notifications, imports/exports, audit UI, search, integrations/webhooks, accessibility, CI, backups/restore, monitoring | Browser/API end-to-end tests; PostgreSQL concurrency/load tests; backup restore and rollback; security review; dependency lock/audit and migration checks |

Implement projects and organization boundaries before custom Jira workflows; implement the leave ledger before automatic approval or accrual. Automations must have stable idempotency keys and versioned policies. Approval must atomically reserve/consume leave and emit notifications. Holiday calendars affect calculations, rather than inserting a separate holiday attendance record for every employee.

“All Jira features” spans multiple products and a marketplace; define target parity for Jira Software work management separately from Jira Service Management and enterprise add-ons. The roadmap above targets core issue tracking and agile planning first. Payroll and statutory policies require explicit jurisdiction and employer rules; do not infer them from an office location alone.

## Migration and rollout

1. Keep original source/data until new workflows and imported data are verified. Initial split directories can be moved into sibling checkouts without code changes.
2. Back up SQLite consistently, then rehearse import to an empty PostgreSQL database. Validate counts, orphan references, statuses, null fields, UTC conventions, indexes and sequences. Assign profiles/offices to existing users; never infer location from historical GPS alone.
3. Reconcile existing invalid statuses or cross-team task references explicitly. Tighten foreign keys, required fields and check constraints in reviewed revisions once data is clean.
4. Rebuild session state by requiring login after migration. Deploy React and API independently with compatible API versions and explicit origins. Keep one scheduler enabled until a dedicated worker is in place.
5. Freeze legacy writes during final cutover, import once, verify workflows, switch routing. Rollback must account for any new writes; do not blindly switch databases back after accepting new transactions.

No live PostgreSQL server was provisioned or verified here. PostgreSQL compatibility is prepared through SQLAlchemy, driver dependencies, migrations and sequence-reset import logic; a real staging rehearsal is still required. The new schema deliberately retains legacy nullable fields and UTC timestamp representation pending data cleanup.

## References

- [FastAPI CORS configuration](https://fastapi.tiangolo.com/tutorial/cors/): frontend/backend origins are distinct, configure exact permitted origins.
- [Alembic autogeneration](https://alembic.sqlalchemy.org/en/latest/autogenerate.html): generated revisions are candidates requiring review; keep fixed revisions in source control.
- [Atlassian Scrum and Kanban planning](https://support.atlassian.com/jira-software-cloud/docs/create-and-plan-work-with-scrum-and-kanban/): agile planning includes substantially more than a four-column task board.
