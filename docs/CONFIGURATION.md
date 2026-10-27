# Configuration

All real values belong in ignored local environment files or the hosting platform's environment settings. Templates are intentionally blank. Restart the backend after runtime changes; rebuild the frontend after changing public frontend configuration.

## Backend

- `APP_ENV`: `development` locally, `production` on the public service.
- `APP_ORIGIN`: the exact frontend origin, such as `http://localhost:5173` locally. Production requires HTTPS.
- `APP_ALLOWED_HOSTS`: comma-separated production hostnames, without schemes, paths or wildcard entries. Must include the hostname of `APP_ORIGIN`.
- `DATABASE_URL`: SQLAlchemy PostgreSQL URL using `postgresql+psycopg://`. Percent-encode password characters in the URL. Production requires `sslmode=require`, `verify-ca` or `verify-full`.
- `MIGRATION_DATABASE_URL`: optional migration-only connection. Alembic falls back to `DATABASE_URL` if absent. Do not expose this value to the browser.
- `SUPABASE_URL`: your HTTPS Supabase project origin.
- `SUPABASE_PUBLISHABLE_KEY`: the project's public publishable key (or supported legacy anon key). Never use a secret/service-role key here.
- `GROQ_API_KEY`: server-only content analysis, question generation and transcription credential.
- `GROQ_MODEL`: content model; defaults to `openai/gpt-oss-120b`. Model availability must match your provider account.
- `GROQ_STT_MODEL`: transcription model; defaults to `whisper-large-v3-turbo`.
- `GROQ_INTERVIEW_TOKEN_BUDGET`: complete-request token estimate budget, including output reserve; default 7000.
- `GROQ_COMMUNICATION_API_KEY`: optional separate communication credential; falls back to the main key.
- `GROQ_COMMUNICATION_MODEL`: optional communication model; falls back to the content model.
- `GROQ_COMMUNICATION_TOKEN_BUDGET`: communication request budget; default 7000.

Separate keys in the same provider organization may share quotas. Never put database credentials or Groq keys in variables beginning with `VITE_`.

## Frontend

`VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` use the same public project values as the backend. The production build rejects missing public configuration and private provider/service-role keys. These values are embedded in browser assets by design; they are not database or model-provider secrets. No real project values are supplied in this release.

## Runtime behavior

`PORT` selects the production listener port (default 8000). `RUN_MIGRATIONS_ON_START=true` runs Alembic before the server starts; default is false. Use that option only for an intentional migration against the configured database. Changing an environment template does not reset a database or copy another account's history.
