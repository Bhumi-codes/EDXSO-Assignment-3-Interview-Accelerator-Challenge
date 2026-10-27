# Ace-it

AI-powered interview practice personalized to a resume and job description.

Ace-it combines role analysis, adaptive interviews, voice interaction and evidence-linked feedback in one application.

## Features

- Google sign-in with private, account-owned preparation sessions.
- Resume and job-description intake from pasted text, PDF, DOCX and TXT.
- Documented job-fit analysis with traceable source evidence.
- Screening, Competency and Deep Dive interviews with adaptive questions.
- Microphone transcription, transcript review and spoken question playback.
- Optional local camera preview and animated interviewer.
- Seven competency dimensions, question feedback, readiness and a preparation plan.
- Downloadable PDF reports and persistent interview history.

## Architecture

React, TypeScript and Vite provide the frontend. FastAPI serves the compiled frontend and `/api` from one origin. Supabase provides Google authentication and PostgreSQL storage. Groq provides language-model inference and transcription; browser speech synthesis reads questions. ONNX Runtime runs local audio pause detection.

Read [Architecture](docs/ARCHITECTURE.md), [Configuration](docs/CONFIGURATION.md) and [Deployment](docs/DEPLOYMENT.md) for operating details.

## Local development

Use Python 3.12 and Node.js 22. Create a virtual environment, then install the backend dependencies:

```sh
python -m venv .venv
# Activate .venv using your shell's activation command.
python -m pip install -r backend/requirements-dev.txt
```

Copy `backend/.env.example` to `backend/.env` and `frontend/.env.example` to `frontend/.env.local`. Fill these files with your own service configuration; no credentials are supplied. Run migrations against the intended Supabase database:

```sh
cd backend
python -m alembic upgrade head
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

In another terminal:

```sh
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`. The Vite development server proxies `/api` to FastAPI. On Windows PowerShell, use `npm.cmd` if required by your shell configuration.

## Production

The default deployment uses Render's native Python runtime. The build script installs pinned dependencies, builds the frontend and checks audio decoding plus the pause-detection model. The start script serves the frontend and API from one origin. Version files select Python 3.12 and Node.js 22. Public frontend values are needed at build time; database and Groq secrets stay server-side. Production requires HTTPS, explicit allowed hosts, SSL database connections and a built frontend. The Dockerfile is an optional alternative and is not used by the native Render configuration.

Deployment is a separate step. See [Deployment](docs/DEPLOYMENT.md) before configuring a public service. No GitHub repository or hosting resource is created by this source package.

## Data and privacy

This package contains no candidate documents, account history, database exports, recordings or local environment files. Histories live in PostgreSQL and are queried using the verified signed-in user's identity. Separate accounts receive separate session lists; knowing another session ID does not grant access.

Using an existing database keeps its existing records, including your own history when you sign in to the same account. To start with an empty environment, configure a separate Supabase project and apply the schema migrations. No database reset is performed automatically.

The camera is a local preview. The application does not record or analyze its video. Audio is processed for transcription/pause observations and is not retained by the application. Accepted text, assessments and source-linked memory are saved for reports. Third-party handling follows the configured provider account policies. See [Privacy and operation](docs/PRIVACY.md).

## Automated validation

```sh
cd backend
python -m pytest tests -q
```

```sh
cd frontend
npm ci
npm run build
```

Tests use synthetic data and isolated SQLite fixtures. They do not require real accounts, production credentials or candidate records. CI validates the backend and frontend on Linux.

## Limitations

AI-generated questions and feedback can be imperfect. Readiness is a preparation estimate, not a hiring decision. Model quotas, hosting resources and provider response times still apply. Scanned PDFs need pasted text or a text-based export. Speech synthesis and microphone support depend on the browser. Background assessments run in the application process; saved progress supports retry after interruptions. Run one application worker with the supplied configuration.

Third-party assets retain their licenses in `frontend/public/assets/interviewer/ASSET_CREDITS.md` and `backend/app/assets/SILERO_LICENSE`.
