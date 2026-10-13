# GeM Tender Intelligence: client portal (frontend)

React + Vite single-page app for clients. A client sees only the GeM tenders matched to their
own seller profile, plus the structured tender view, the match explanation and the tender
documents. Every rule is enforced by the backend; the UI only displays what the API returns.

## Configure

Create `frontend/.env.local` (never commit it):

```
VITE_SUPABASE_URL=https://<project>.supabase.co
VITE_SUPABASE_ANON_KEY=<public anon key>
```

The anon key is a public, browser-safe key. Never put a service-role key in the frontend.

Development without Supabase: put `VITE_DEV_LOGIN=true` in `frontend/.env.local` and
`DEV_LOGIN_ENABLED=true` in the backend `.env`. The login page then asks only for an email
(local test sign-in; see the main README). Never enable it for a shared or production build.

## Run

```
npm install
npm run dev        # http://localhost:5173, proxies /api to http://localhost:8000
npm run build      # type-check (tsc -b) + production bundle
npm test           # vitest
```

## Pages

| Route | Backend API |
|---|---|
| `/login` | Supabase Auth (email + password), then `POST /api/auth/provision`; or `POST /api/dev/login` with the local test sign-in |
| `/` My Tenders | `GET /api/portal/sellers/{id}/summary`, `GET /api/portal/sellers/{id}/tenders` |
| `/tenders/:id` | `GET /api/portal/sellers/{id}/tenders/{tender_id}`, document download |
| `/profile` | `GET /api/sellers/{id}`, `POST /api/sellers/{id}/attributes`, `POST /api/portal/sellers/{id}/matches/refresh` |
