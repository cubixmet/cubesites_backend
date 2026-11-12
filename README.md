# CubeSites Django Backend

DRF API shared by the contractor app (`cubesites/`) and Super Admin (`cubesites_admin_dashboard/`).

See [ARCHITECTURE.md](./ARCHITECTURE.md) for frontend analysis, conflict resolutions, and app layout.  
See [API.md](./API.md) for endpoint reference.

## Quick start

```bash
cd cubesites_backend
source ../venv/bin/activate          # or: python -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # edit secrets / DATABASE_URL as needed
python manage.py migrate
python manage.py seed_demo
python manage.py runserver 8000
```

### Demo credentials

| Audience | Email | Password |
|----------|-------|----------|
| Platform admin | `admin@cubesites.in` | `Admin@123` |
| Contractor owner | `owner@cubesites.demo` | `demo1234` |
| Site manager | `manager@cubesites.demo` | `demo1234` |
| Staff | `staff@cubesites.demo` | `demo1234` |

## PostgreSQL

Set in `.env`:

```
DATABASE_URL=postgres://USER:PASSWORD@127.0.0.1:5432/cubesites
```

Then `migrate` again against Postgres.

## Frontends

```bash
# contractor (default Vite port 8080)
cd ../cubesites && npm run dev

# admin (use another port if needed)
cd ../cubesites_admin_dashboard && npm run dev -- --port 8081
```

Set `VITE_API_URL=http://127.0.0.1:8000` in each frontend `.env` when switching services to HTTP (see frontend `src/lib/api.ts`).

CORS origins are configured via `CORS_ALLOWED_ORIGINS`.

## Tests

```bash
python manage.py test accounts.tests
python manage.py check
```

## Money & billing

All money fields are **integer paise**. Billing math mirrors `cubesites/src/lib/billing.ts` in `billing/services.py`, with rates stored as `PricingVersion` / `TaxRule` rows (seeded by `seed_demo`).

## Not yet fully implemented

- Live Google Drive OAuth / backup runners (models + stub retry only)
- Payment gateway / webhooks (manual approval path works)
- Retention purge automation
- Email/SMS delivery
- Full frontend service swap (API client stub present; mock store still default in UI)
# cubesites_backend
