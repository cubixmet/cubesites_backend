# CubeSites API reference

Base URL (local): `http://127.0.0.1:8000`  
Auth: `Authorization: Bearer <access>` from `/api/auth/login/`  
Errors: `{ "detail": "...", "code": "...", "errors"?: ... }`  
Money: integer **paise**.

---

## Auth — `/api/auth/`

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/config/` | public | `{ googleClientId, googleEnabled, otpExpiryMinutes }` |
| POST | `/google/` | public | GIS `{ credential }` (+ `businessName`/`phone` for new owners) |
| POST | `/signup/` | public | Start email signup → sends OTP email |
| POST | `/signup/verify/` | public | `{ email, otp }` → create owner workspace + tokens |
| POST | `/signup/resend/` | public | Resend signup OTP |
| POST | `/login/` | public | `{ identifier, password }` — email **or phone** + password (no OTP) |
| POST | `/refresh/` | public | JWT refresh (`{ refresh }`) |
| GET/PATCH | `/me/` | user | Current user (+ workspace on GET) |

---

## Contractor — `/api/v1/`

Requires workspace user (not platform admin).

| Method | Path | Perm | Description |
|--------|------|------|-------------|
| GET/PATCH | `/workspace/` | manageStaffSites (PATCH) | Account / settings fields |
| GET/POST | `/staff/` | manageStaffSites | Non-owner users |
| GET/PATCH | `/staff/:id/` | manageStaffSites | Update staff |
| POST | `/staff/:id/active/` | manageStaffSites | `{ active }` |
| GET/POST | `/sites/` | viewSite (GET); manageStaffSites (POST) | List/create sites |
| GET/PATCH | `/sites/:id/` | viewSite (GET); manageStaffSites (PATCH) | Site detail |
| GET | `/sites/:id/totals/` | viewFinancials | `{ expenses, payments, net, count }` |
| POST | `/sites/:id/status/` | manageStaffSites | `{ status }` (+ reactivation quote) |
| PUT | `/sites/:id/assignments/` | manageStaffSites | `{ userIds: [] }` |
| GET/POST | `/items/` | viewSite\|createEntries\|manageItems (GET); manageItems (POST) | Catalog |
| PATCH | `/items/:id/` | manageItems | Rename |
| GET/POST | `/entries/` | viewSite (GET; money redacted without viewFinancials); createEntries (POST) | Transactions |
| GET/PATCH/DELETE | `/entries/:id/` | viewSite (GET); editEntries (mutate) | Entry CRUD |
| GET/POST | `/media/` | viewSite (GET; bills need viewFinancials); uploadMedia (POST) | multipart upload |
| DELETE | `/media/:id/` | uploadMedia | Remove attachment |
| GET | `/billing/current/` | manageStaffSites or viewFinancials | Current estimate |
| GET | `/invoices/` | manageStaffSites | Invoice list |
| POST | `/invoices/current/` | manageStaffSites | Issue period invoice |
| POST | `/invoices/:id/payments/` | manageStaffSites | Manual payment |
| GET | `/activity/` | viewSite (money in before/after redacted without viewFinancials) | Audit log |
| GET | `/notifications/` | authenticated | Inbox |
| POST | `/notifications/read-all/` | authenticated | Mark all read |
| POST | `/notifications/:id/read/` | authenticated | Mark one read |

---

## Super Admin — `/api/admin/`

Requires `is_platform_admin`.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/overview/` | KPI counts |
| GET | `/contractors/` | List (+ `?q=`) |
| GET | `/contractors/:id/` | Detail + sites/staff/invoices |
| POST | `/contractors/:id/status/` | `{ status, reason }` |
| GET | `/sites/` | Cross-tenant sites |
| GET | `/staff/` | Cross-tenant staff |
| GET | `/payments/` | Billing payments |
| POST | `/payments/:id/review/` | `{ decision: approved\|rejected, reason }` |
| GET/POST | `/pricing-versions/` | Versioned pricing |
| GET/POST | `/tax-rules/` | Effective-dated tax |
| GET | `/subscriptions/` | Cross-tenant subscriptions |
| GET | `/invoices/` | Cross-tenant invoices |
| GET | `/storage/snapshots/` | Daily storage snapshots (+ `?contractorId=`) |
| POST | `/storage/snapshots/:id/corrections/` | `{ mb, reason }` |
| GET | `/backups/` | Backup jobs |
| POST | `/backups/:id/retry/` | Stub retry |
| GET | `/support/cases/` | Support list |
| GET/PATCH | `/support/cases/:id/` | Case detail |
| POST | `/support/cases/:id/notes/` | Internal note |
| GET | `/notifications/` | Platform / workspace alerts |
| GET | `/activity/` | Platform audit |
| GET/PUT | `/settings/` | Platform settings |

---

## Permissions (contractor)

`viewSite`, `viewFinancials`, `createEntries`, `editEntries`, `manageItems`, `uploadMedia`, `reports`, `manageStaffSites`  
Owner always allowed. Enforced server-side.
