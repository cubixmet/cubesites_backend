# CubeSites Backend — Architecture & Frontend Analysis

**Date:** 2026-10-28  
**Sources of truth:** `cubesites/` (contractor app) primary; `cubesites_admin_dashboard/` for platform ops.  
**Backend:** `cubesites_backend/` (was empty Django 4.2 scaffold).

---

## 1. Frontend findings

### 1.1 Contractor app (`cubesites/`)

- TanStack Start + localStorage demo (`src/mock/store.ts`, `src/services/*`).
- **Tenant** = one `Account` workspace; users belong to that workspace.
- **Roles:** `owner` | `site_manager` | `staff` with permission flags (`viewSite`, `viewFinancials`, `createEntries`, `editEntries`, `manageItems`, `uploadMedia`, `reports`, `manageStaffSites`).
- **Sites:** `active` | `completed` | `inactive` + status history; only active sites accept new entries/photos.
- **Ledger:** items catalog + entries (materials/labour/equipment/other/payment); money in **integer paise**; payments not linked to expenses; `net = payments − expenses`.
- **Media:** bill attachments on entries; progress photos per site.
- **Billing:** hardcoded rules in `src/lib/billing.ts` (₹109/site after 3 free, ₹29/staff after 1 free, storage blocks ₹5/250 MB after 250 MB free); invoices + manual payment `pending_approval`.
- **Drive/backups:** UI placeholders only.

### 1.2 Super Admin app (`cubesites_admin_dashboard/`)

- Separate mock store; multi-tenant oversight.
- Features: contractors, cross-tenant sites/staff (read-only), versioned pricing, tax rules, payment review, storage corrections, Drive/backups ops, support cases, retention queue, platform audit, settings.
- Demo auth: `admin@cubesites.in` / `Admin@123` (must become real platform-admin users).

### 1.3 Conflicts (resolved for backend)

| Topic | Contractor | Admin | **Backend decision** |
|-------|------------|-------|----------------------|
| Money | paise ints | ₹ floats | **Paise integers everywhere** |
| Site status | active/completed/inactive | active/inactive/archived | **active/completed/inactive**; admin “archived” maps to `completed` |
| Staff roles | typed + permissions | free-text | **typed roles + permission JSON** |
| Tax | workspace display settings | platform `TaxRule` | **Platform TaxRule for invoices**; workspace settings for UI labels/breakup |
| Pricing | `PRICING` const | `PricingVersion` | **Versioned pricing** (seeded with contractor defaults) |
| Invoice status | due/pending_approval/paid | pending/overdue/paid | **due / pending_approval / paid / overdue** |
| IDs | `s_1`, `u_owner` | `c-101` | **UUIDs** in API; seed demo with readable emails |

### 1.4 Gaps / not fully implemented

- Real Google Drive OAuth, backup runners, restore verification → **API stubs + models only**.
- Payment gateway / webhooks → **manual approval path only**.
- Retention purge workflow → **models + reminder endpoint stub**.
- Email/SMS delivery → **not implemented**.
- Impersonation → **not in v1**.

---

## 2. Backend architecture

### 2.1 Apps

| App | Responsibility |
|-----|----------------|
| `accounts` | Custom `User`, `Workspace` (contractor account), auth (JWT), permissions helpers |
| `jobsites` | Sites, status history, staff↔site assignments |
| `ledger` | Catalog items, entries/transactions, attachments (bills/photos) |
| `billing` | Pricing versions, tax rules, subscriptions, invoices, payments, storage snapshots |
| `ops` | Activity logs, notifications, Drive/backup records, support cases, retention notices, admin settings |

### 2.2 Auth & isolation

- **Contractor users:** JWT; every query scoped by `user.workspace_id` (+ site visibility for non-owners).
- **Platform admins:** `User.is_platform_admin=True` (no workspace required); access `/api/admin/*` only.
- Hiding UI is not security — reads and mutations check permission keys server-side.
- Without `viewFinancials`, money fields are redacted (`null`) and site totals / bills are denied.
- Saving staff permissions runs `sanitize_permissions` so related parents (e.g. `editEntries` → `createEntries` + `viewSite`) are forced on.

### 2.3 API surface (summary)

- `/api/auth/*` — login, logout, me  
- `/api/v1/*` — contractor workspace APIs (sites, entries, media, staff, billing, reports, activity, notifications, settings)  
- `/api/admin/*` — super-admin APIs (contractors, payments review, pricing, tax, storage corrections, backups, support, …)

### 2.4 Money & billing

- All amounts: `BigIntegerField` paise.
- Billing math mirrors `cubesites/src/lib/billing.ts` in `billing/services.py`.
- Effective pricing from active `PricingVersion`; tax from effective `TaxRule` (fallback workspace `tax_rate_pct`).

### 2.5 Media

- Local `MEDIA_ROOT` for development; store path + `size_bytes`.
- Production: swap storage backend via Django storages (documented, not required for v1).

---

## 3. Implementation stages

1. Settings, env, deps, CORS, apps scaffold  
2. Models + migrations + admin  
3. Auth + contractor CRUD APIs  
4. Billing + admin APIs  
5. Tests + seed command + docs  
6. Frontend API client hooks (env-gated) without UI rewrite  

---

## 4. Running (preview)

```bash
cd cubesites_backend
source ../venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 8000
```

Frontends: set `VITE_API_URL=http://127.0.0.1:8000` when wiring HTTP clients.
