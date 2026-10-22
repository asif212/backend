# Implemented capabilities and limits

This inventory supersedes the initial split inventory in the parent migration workspace. It describes the API and matching React client as of this implementation. It is not a claim of full Jira or enterprise HR parity.

| Area | API and React workflows |
|---|---|
| Administration | Team creation, lead creation, suspension/reactivation with session revocation, administrator CLI bootstrap |
| Identity | Sign-in, first password change, hashed opaque sessions, idle/absolute expiration, revocation, logout |
| People | Employee creation, department/title/join-date/office profile editing, employee self-profile view, deactivation revoking access |
| Projects | Team-scoped projects, stable project key, owner, cost/currency, time estimate, planned/release dates, editable planning details, member allocation percentages and dates, atomic per-project issue numbering |
| Issues | Epic/feature/story/task/bug/subtask types, parent relationships, priority, points, labels, editable time estimate, planned cost/currency, planned/release/due dates, reassignment to allocated project members, fixed validated transitions, issue details and status history |
| Planning | Project filtering, searchable issue list, backlog view, sprint create/start/complete, one active sprint per project, completed sprint snapshot, incomplete issues returned to backlog |
| Collaboration | Comments, follow/unfollow, in-app comment notifications to watchers, bounded work logging, issue links, dependency cycle prevention, blocking dependencies and children must finish before parent/target completion |
| Attachments | Authenticated upload/download, 5 MB maximum file size, downloads forced as attachments, filenames sanitized; bytes are stored in the database in this release |
| Attendance | Live geofence check-in/out, timezone-based work dates, automatic checkout, correction requests, lead decisions, immutable original times with effective correction overlay |
| Leave | Policy selection, full/half-day requests, overlap checks, working-day/holiday charges, reserved balances, approval/rejection, cancellation/refund, one to three distinct lead approvals |
| Leave policies | Office eligibility, annual/monthly accrual, eligibility waiting period, optional joining-year proration, carry-forward cap, annual account rollover, per-employee/year enrollment, immutable ledger view |
| Calendars | Office holidays affecting all assigned employees, team holidays in calculations, employee attendance calendar, shift start/end and working weekdays/timezone settings |
| Operations | Read/unread notifications, scoped audit history, current task status/overdue summary, date-filtered attendance reports using approved corrections |
| Migration | Independent packages, versioned OpenAPI, explicit Alembic chain, SQLite/PostgreSQL connection configuration, source-preserving legacy import |

## Operating rules

- Projects are collaborative for all members of the same team. Standalone legacy tasks remain visible only to their assignee and lead. Project-specific permission schemes and organization memberships are not implemented.
- Project membership controls assignment eligibility, while visibility remains team-wide. Leads add/update allocations from Projects → open a project. Allocations are inclusive date intervals; missing boundaries are unbounded. Overlapping allocations across projects cannot exceed 100%. The server checks the issue's planned date (or today's date in the team timezone if absent) against the assignee's active allocation. Finish or reassign open project issues before deactivating a membership. Inactive memberships can be reactivated without duplicating records.
- Projects and issues/features have manual planned cost, an uppercase three-letter currency code (default INR), estimates in minutes, and planned/release dates. Costs use fixed-precision decimal storage and serialize as decimal strings. Blank cost means unknown, distinct from zero. Release cannot precede planned date; due date remains a separate deadline. Currency values are never automatically converted and project cost is not calculated from issue costs.
- Upgrading existing projects creates memberships for existing issue assignees. An employee assigned across several projects receives equal allocation shares rounded down to two decimals. Review these inferred allocations after migration. Existing costs/dates remain unknown; estimates and assignments are preserved.
- Admins manage teams and leads, while leads manage team work and HR. There is no separate HR role or field-level HR permission scheme yet. Profile access is limited to self or team lead.
- Create work locations, assign employee profiles to offices, create leave policies, and enroll employees by policy/year before requesting policy-based leave. Without any active team policies, legacy unmetered leave remains supported. Once a policy exists, requests require a policy.
- Requests reserve available days immediately. Approval keeps the reservation as the consumed amount; rejection/cancellation adds exactly one refund. Balances therefore exclude both pending and approved requests. Approved leave can only be cancelled before it begins.
- Half-day requests cover one working date. A second request for another half of the same date is currently considered overlapping; morning/afternoon sessions are not modeled.
- Approval steps mean distinct active leads in the same team, rather than named sequential manager/HR chains. A lead cannot approve twice; any authorized lead can reject. Configure enough leads for the chosen policy.
- Year-crossing leave requests must be split. Future-year accounts have no new accrual until that year starts. Annual entitlement posts once; monthly entitlement posts at the beginning of each month, rounded down to two decimals with the residual in December. Missed due periods are caught up on the next run.
- Joining-year annual proration uses remaining calendar days, including the join date. Monthly proration credits whole joining and subsequent months. Proration is optional. Missing join dates are rejected for policies with a waiting period.
- Rollover creates current-year accounts from eligible, active employees' prior-year accounts. It transfers up to the policy cap from the previous balance using paired ledger entries, so transferred days cannot be spent twice. Carry-forward is fixed when first processed; late prior-year refunds do not automatically restate it. Remaining prior-year balances do not expire automatically in this version.
- `RUN_SCHEDULER=true` runs accrual/rollover and attendance jobs every minute. Keep exactly one scheduler process. The lead can also run due accruals from Leave balances. Unique ledger keys make repeat accrual safe. PostgreSQL row locking is used where available; SQLite is intended for single-process local development.
- Corrections require a completed attendance row, the original work date, a positive interval of at most 24 hours, and no future checkout. Original attendance is preserved; reports and effective attendance values use the latest approved correction. Timers use the same effective interval.
- Reports use the requested dates for attendance; task status counts are current, rather than historical snapshots. Overdue counts use the requested end date.
- Policy definitions are immutable through the API. Create new policies for changed rules; employee effective-dated transfers and policy reassignment history remain future work.
- Attachments are in database blobs for a self-contained local application. Production should use private object storage, request limits at the proxy, scanning/quarantine and retention controls. Content is never served inline by the API.

## Remaining product work

The following roadmap areas remain unimplemented: organization/multiple-team memberships; HR-specific and project-level roles; configurable issue workflows and custom fields; drag-and-drop/ranked backlog and WIP limits; releases/components/roadmaps; advanced agile charts and dashboards; saved filters; mentions and rich text; email/webhook/integration delivery; named/delegated approval chains and escalation; hourly leave/AM-PM sessions; leave expiry/encashment/negative balances and jurisdiction rules; roster templates, break/overtime calculations and biometric adapters; onboarding/offboarding checklists, documents/assets, recruitment, expenses, performance reviews and payroll; SSO/MFA; full pagination; exports; centralized rate limiting, durable job queue/outbox and production monitoring/backup automation.

These should be implemented as reviewed modules with acceptance tests rather than represented by empty navigation entries or placeholder buttons.

## Verification

All 28 tests pass. The suite exercises project/sprint lifecycle, cross-team access denial, issue hierarchy, transition validation, comments/work logs, dependency cycles, attachment isolation, session revocation, leave accrual/reservation/refunds, distinct approvals, carry-forward/proration, half-days/waiting periods, holidays, correction preservation, legacy import, complete migration upgrade/downgrade, preservation of existing policy rows/defaults during upgrade, project allocation capacity and date checks, exact cost metadata, Feature issue creation/editing, and migration backfill of existing project assignments. Frontend TypeScript and production builds pass. PostgreSQL DDL compilation passes for all 30 tables; 17 frontend Chrome interaction tests pass against mocked API responses; live backend/browser integration and real PostgreSQL verification remain outstanding. The Python suite still reports deprecation warnings for the inherited naive UTC timestamp approach and installed test client.
