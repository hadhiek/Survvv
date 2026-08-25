# NITC Survey Exchange

A working MVP for a NITC-only survey respondent exchange. It implements demographic quotas, credit reservation and transfer, one response per student/survey, idempotent Google Forms webhooks, and a small participant feed.

## Run locally

1. `cd backend; python -m venv .venv; .\.venv\Scripts\activate; pip install -r requirements.txt`
2. `uvicorn app.main:app --reload` (API: `http://localhost:8000/docs`)
3. In another terminal: `cd frontend; npm install; Copy-Item .env.local.example .env.local; npm run dev` (web: `http://localhost:3000`)

The local app uses SQLite and `DEV_MODE=true`. The frontend headers simulate the logged-in account only for development; do not deploy this mode.

## Production setup

1. Create a Supabase project; enable email confirmation and restrict signups to NITC addresses in the Auth hook/trigger.
2. Run [`supabase/migrations/001_initial.sql`](supabase/migrations/001_initial.sql) in the SQL editor.
3. Set `DATABASE_URL` to the Supabase PostgreSQL connection string and `DEV_MODE=false`.
4. Set `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CORS_ORIGINS`, and `ADMIN_EMAILS`. The API verifies Supabase access tokens through the Auth user endpoint. The frontend should obtain a token via `@supabase/ssr` and send it as `Authorization: Bearer <token>`.
5. The email in `ADMIN_EMAILS` becomes the first administrator when it signs in. Admins can inspect `/admin/overview` and grant startup credits with `POST /admin/users/{user_id}/credits`.
5. Deploy the frontend to Vercel and API to Render/Railway using HTTPS. Install the generated script from [`google-apps-script/survey-integration.gs`](google-apps-script/survey-integration.gs) in each response spreadsheet, then create its installable trigger.

## Operational rules

- The `webhook_secret` is returned once when a survey is created; save it in the Apps Script project.
- Every credit-changing path uses a database transaction and every completion is keyed by a unique session. Repeated webhook delivery is safe.
- Google Forms must have a required **Participation Code** field and its entry key must be supplied when creating the survey.
- The supplied SQL uses RLS to make browser access read-only. Keep all mutations in FastAPI using a tightly protected service-role database connection.

## Test

From `backend`: `pytest -q`. It verifies reservation, quota completion, credit transfer, and webhook idempotency.
