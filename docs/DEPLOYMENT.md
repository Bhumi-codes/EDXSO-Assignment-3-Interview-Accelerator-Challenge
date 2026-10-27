# Native Render deployment

Deploy one Python Web Service. FastAPI serves both the frontend and API. Supabase remains the database. Docker is not used by render.yaml; the Dockerfile is an optional alternative.

## 1. Prepare GitHub

Use only the contents of F:\AI_Interview_project\release\Ace-it as the repository root. Do not upload the surrounding working project or the older Ace-it-production validation folder. Create a repository yourself and upload/push using Git or GitHub Desktop. Private repositories are supported when Render has access. Include hidden files. The root should contain backend, frontend, deploy, render.yaml, .python-version and .node-version. Never upload working .env files, .venv, node_modules or database exports. No repository is pushed automatically.

## 2. Create the service

At https://dashboard.render.com choose New > Web Service, connect GitHub and select your repository/branch.

- Language: Python 3
- Root Directory: leave blank
- Build Command: sh deploy/build.sh
- Start Command: sh deploy/start.sh
- Health Check Path: /api/health
- Region: near your Supabase region where available

Do not choose Docker or Static Site. Version files select Python 3.12 and Node 22; remove conflicting version overrides. Do not set PORT manually.

Use Free for an initial trial if available. Render does not recommend Free for production; it sleeps after 15 idle minutes and can take about a minute to wake. Check memory use during a full interview before deciding whether a paid instance is needed. Do not create Render Postgres: your app uses Supabase.

## 3. Add environment variables

Add these individually in Render Environment before deployment. Replace placeholders with real values, without angle brackets:

```text
APP_ENV=production
APP_ORIGIN=https://<actual-service-host>.onrender.com
APP_ALLOWED_HOSTS=<actual-service-host>.onrender.com
DATABASE_URL=<your working PostgreSQL SQLAlchemy SSL URL>
SUPABASE_URL=<your Supabase HTTPS project URL>
SUPABASE_PUBLISHABLE_KEY=<your public publishable key>
VITE_SUPABASE_URL=<same as SUPABASE_URL>
VITE_SUPABASE_PUBLISHABLE_KEY=<same as SUPABASE_PUBLISHABLE_KEY>
GROQ_API_KEY=<your main server-side key>
RUN_MIGRATIONS_ON_START=true
```

Use the actual assigned Render hostname. If it is assigned after creation, correct APP_ORIGIN/APP_ALLOWED_HOSTS and redeploy. A startup failure due to incorrect origin/host settings is resolved by correcting them.

Copy DATABASE_URL privately from your local backend environment. It must begin postgresql+psycopg://, contain the percent-encoded password and require SSL, for example ?sslmode=require. Supabase Shared Pooler Session mode on port 5432 provides an IPv4-compatible starting point. Use its exact project-specific host and username. If using migration-only credentials, add MIGRATION_DATABASE_URL.

Copy these optional settings when used by your working local app; omit unused settings instead of entering blank overrides:

```text
GROQ_COMMUNICATION_API_KEY=<separate communication key>
GROQ_MODEL=<your working content model>
GROQ_COMMUNICATION_MODEL=<your working communication model>
GROQ_STT_MODEL=<your working transcription model>
GROQ_INTERVIEW_TOKEN_BUDGET=7000
GROQ_COMMUNICATION_TOKEN_BUDGET=7000
```

Never put database passwords, provider keys or Supabase secret/service-role keys in VITE variables. Both VITE values are public browser configuration and must exist during the build. Changing them requires a rebuild. Separate Groq keys may share organization quotas.

RUN_MIGRATIONS_ON_START=true applies versioned schema migrations, without resetting tables or importing history. Against an existing database already at head, there is nothing new to apply. Use the intended database and normal backups. After the first successful deployment, set this to false and redeploy. For future schema changes, run an intentional migration step or enable this setting for that deployment.

## 4. Deploy

Click Deploy Web Service. The build installs dependencies, builds frontend/dist and checks native audio support. Look for:

```text
Audio decoding and CPU pause-detection model loaded successfully.
```

Startup should show Application startup complete and Uvicorn listening on 0.0.0.0 with Render's port. Open https://<actual-host>/api/health, then the main site. Health alone does not verify database, OAuth or provider access.

## 5. Configure Google login

In Supabase > Authentication > URL Configuration:

1. Set Site URL to your actual production HTTPS origin.
2. Add that exact URL to Redirect URLs, plus its trailing-slash form if used by the app. Keep localhost entries if still developing locally.
3. Save.

In Google Cloud > Google Auth Platform > Clients > your existing Web application client:

1. Add the Render HTTPS origin under Authorized JavaScript origins.
2. Keep the Supabase callback from its Google provider settings under Authorized redirect URIs, normally https://<project-ref>.supabase.co/auth/v1/callback.
3. Do not replace that callback with the Render home page. Save.

If the consent screen is in Testing, only configured test users can sign in. Add intended testers or complete Google's publishing requirements before public release.

## 6. Verify the deployment

Use synthetic data. Sign in, create a session, analyze resume/JD text, record/review/submit an answer and hear the next question. Test camera on/off, end or finish the attempt, view its report and download the PDF. Refresh the current page and confirm navigation is retained.

Use a second account/browser profile and confirm separate histories. Restart/redeploy and verify persistence. Existing histories remain in Supabase, not in the source package; your own account will still show its history on the same database.

Complete a real interview to check memory, latency, quotas and background assessment recovery. The build check does not establish real microphone behavior or concurrent-user capacity.

## Troubleshooting

- Host validation or 400: use the actual hostname without scheme/path in APP_ALLOWED_HOSTS, and HTTPS in APP_ORIGIN.
- Frontend configuration build failure: check both VITE values and rebuild.
- Database connection failure: verify session-pooler host/username/port, encoded password, SSL and Supabase health/network restrictions. Never share the URL in logs/screenshots.
- Login returns to localhost: correct Supabase Site URL/Redirect URLs and start a fresh sign-in.
- Audio check failure: inspect the av/onnxruntime shared-library or model error. Investigate before considering Docker; do not silently disable measurements.
- Process killed/out of memory: inspect Render logs/metrics during audio decoding and review capacity before a paid upgrade.
- Slow first load on Free: allow for idle spin-down. No artificial keep-alive traffic is configured.
- Groq quota error: hosting does not increase model quota. Saved progress supports retry after recovery.

Official references:
- https://render.com/docs/deploy-fastapi
- https://render.com/docs/native-runtimes
- https://render.com/docs/python-version
- https://render.com/docs/node-version
- https://render.com/docs/free
- https://supabase.com/docs/guides/auth/social-sign-in/auth-google
