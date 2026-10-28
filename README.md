# Ace-it

Ace-it helps you prepare for a job interview using your own resume and the job description. It asks relevant questions, listens to your answers and uses the conversation to decide what to ask next. After the interview, you can review your performance, see where you need more practice and follow a personalized preparation plan.

## Live demo

**[Open Ace-it](https://ace-it.onrender.com)**

Sign in with Google to create your own preparation sessions. You do not need to install anything to use the live demo.

> The demo runs on Render's free tier and uses the project owner's configured free-tier Groq API allowance. The first visit after inactivity may take about a minute to load. AI features can become temporarily unavailable when the shared provider quota is exhausted.

## How the project works

1. **Sign in and create a session.** Give the session a name for the role you want to prepare for. Sessions and interview histories belong to the signed-in account.
2. **Add your resume and job description.** Paste text or upload a PDF, DOCX or UTF-8 TXT file. Review the extracted text before analysis. Scanned PDFs need pasted text or a text-based version.
3. **Review the role analysis and documented job fit.** The app identifies job requirements, resume evidence, matches and preparation gaps. Documented job fit is separate from interview performance.
4. **Begin the interview.** A short welcome introduces the interviewer. You can enable your camera preview and check your microphone before starting.
5. **Complete three interview levels.**
   - **Screening: 4 questions.** Covers your background, motivation, role fit, relevant experience, communication and basic understanding.
   - **Competency: 4 questions.** Explores job-related knowledge, practical decisions, projects, problem solving and teamwork.
   - **Deep Dive: 7 questions.** Probes explanations, trade-offs, reasoning and realistic scenarios through adaptive follow-up questions.
6. **Answer and continue.** Hear each question, record an answer, review or correct the transcript and submit it. Typed answers are also supported. The next question uses the resume, JD, previous answers, demonstrated strengths, gaps and discussed topics. You can skip a question or end the attempt early. A new attempt has its own answer history.
7. **Read the performance report.** Saved scores appear after the attempt ends, while a separate AI step prepares the personalized summary and guidance. The report includes an overall score, competency scores, evidence coverage, readiness, strengths and areas to improve. Question feedback shows the question, submitted answer, assessment, strengths, improvements and the direction a stronger answer could take.
8. **Follow your preparation plan.** Priorities are linked to demonstrated gaps and role requirements. Each personalized priority can include the supporting evidence, specific subtopics to review, a practical exercise and a success check. Download the report, summary and preparation guidance as a PDF.

### Assessment and communication

The seven report dimensions are:

- Role fit.
- Technical knowledge.
- Problem solving.
- Communication.
- Confidence — clarity and ownership.
- Depth of understanding.
- Behavioural fit.

Confidence describes demonstrated clarity, supported explanations and ownership of work. It does not infer personality or emotions from a face or voice. Honest uncertainty is not automatically treated as poor confidence.

Communication assessment considers grammar, sentence structure and disruptive repetition while ignoring spelling mistakes and likely transcription errors. Available audio observations support small, defined adjustments for qualifying internal pauses. Ordinary non-repetitive fillers are not penalized. Typed answers can receive language assessment, but cannot receive an audio-pause deduction.

Python aggregates saved rubric assessments into dimension and overall scores. Explicit skips adjust assessed dimension scores once; unasked questions after an early end do not create an additional penalty. Missing evidence is distinguished from demonstrated weakness. Readiness combines available interview evidence and documented JD alignment, with a conclusion when all seven dimensions are assessed. These are preparation estimates, not hiring predictions.

## Technology stack

- **Frontend:** React 19, TypeScript, Vite and CSS.
- **Interview interface:** Three.js for the animated 3D interviewer; browser media APIs for microphone input and optional camera preview; browser speech synthesis for question playback.
- **Backend:** Python 3.12, FastAPI, Pydantic and HTTPX.
- **Database and authentication:** Supabase PostgreSQL and Supabase Auth with Google OAuth.
- **Database access and migrations:** SQLAlchemy, Psycopg and Alembic.
- **AI services:** Groq for content analysis, adaptive question generation, answer assessment, communication assessment and speech-to-text. The default configured models are openai/gpt-oss-120b for text and whisper-large-v3-turbo for transcription; availability depends on the provider account.
- **Audio processing:** PyAV, NumPy and Silero VAD through CPU ONNX Runtime for post-recording pause observations.
- **Documents and reports:** pypdf, python-docx and ReportLab.
- **Validation and deployment:** pytest, TypeScript checks, GitHub Actions and Render's native Python runtime. FastAPI serves the built frontend and API from one public origin.

Content assessment also extracts compact, source-linked memory updates. Python merges updates, removes exact duplicates, tracks coverage and selects relevant context within a request budget. Optional memory consolidation runs in the background. Full answers remain stored separately for feedback and evidence review.

### Database schema

The application has eight main tables. Supabase manages authentication identities separately in auth.users, and Alembic tracks migration versions in alembic_version.

- **profiles:** Signed-in user ID, display name and timestamps. Connected to the Supabase authentication identity.
- **interview_sessions:** Owner, title, document text and snapshots, role/candidate analysis, job-fit information, attempt state and timestamps. A new attempt can reference its source session without replacing its history.
- **session_requirements:** Extracted requirements for a session, including category, importance, source evidence and fit-scoring weight.
- **requirement_matches:** The resume match, supporting evidence, explanation and preparation note for a requirement.
- **interview_levels:** Screening, Competency and Deep Dive level records, their question budgets, status and timestamps.
- **interview_turns:** Questions, follow-up relationships, submitted text, answer mode, processing status and available delivery observations.
- **turn_evaluations:** Per-answer rubric scores, assessment, evidence, strengths, improvements, ideal direction and processing metadata.
- **interview_reports:** One report per attempt, containing aggregated scores, coverage, readiness, strengths, weaknesses, summary and preparation plan.

```mermaid
flowchart TD
    A[Supabase auth.users] --> B[profiles]
    B --> C[interview_sessions]
    C --> D[session_requirements]
    D --> E[requirement_matches]
    C --> F[interview_levels]
    F --> G[interview_turns]
    G --> H[turn_evaluations]
    C --> I[interview_reports]
```

UUID keys connect the records, with JSONB used for structured analysis, evidence and processing metadata. The backend verifies the signed-in identity and applies ownership checks to session access. Migrations enable row-level security and revoke direct browser-role table access. Privileged server credentials can bypass RLS, so backend ownership checks remain essential. No candidate histories or database exports are included in this repository.

## Run your own copy locally

The live demo uses the deployed service owner's configuration. Running your own copy requires your own Supabase project, Google OAuth client and Groq API key.

### 1. Install prerequisites and download the code

Install Python 3.12, Node.js 22 with npm, and Git. Use a browser with microphone support; Chrome or Edge is a practical starting point.

```sh
git clone https://github.com/Bhumi-codes/EDXSO-Assignment-3-Interview-Accelerator-Challenge.git ace-it
cd ace-it
```

Alternatively, choose Code > Download ZIP on GitHub, extract it and open a terminal in the extracted project folder. Its root should contain backend, frontend and deploy.

### 2. Set up Supabase and Google sign-in

1. Create an account at [Supabase](https://supabase.com/) and create a project in an organization you own. Save the database password securely.
2. Copy the project's HTTPS URL and public publishable key from its connection/API settings. Do not use a secret or service-role key as the public key.
3. Open Connect and select the Shared Pooler in Session mode. Copy its exact project-specific host, username and port; Session mode normally uses port 5432.
4. Construct the SQLAlchemy database URL using postgresql+psycopg:// and require SSL. Replace the password placeholder with your database password, percent-encoding special characters in the password only. For example, an @ inside the password becomes %40. Do not encode the entire connection URL.
5. In Google Cloud, create/select a project and configure Google Auth Platform. Create a Web application OAuth client and add http://localhost:5173 under Authorized JavaScript origins.
6. In Supabase Authentication > Sign In / Providers > Google, copy the displayed OAuth callback URL into Google's Authorized redirect URIs. Enter the Google client ID and secret in Supabase and enable the provider.
7. In Supabase Authentication > URL Configuration, set Site URL to http://localhost:5173 and add http://localhost:5173 and http://localhost:5173/ to Redirect URLs. Save.

Use the [Supabase Google sign-in guide](https://supabase.com/docs/guides/auth/social-sign-in/auth-google) and [PostgreSQL connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres) for the current dashboard and provider settings.

### 3. Create your Groq key

Create a [Groq account and API key](https://console.groq.com/keys). Your account must have access to the configured text and transcription models. A separate communication key is optional; without it, communication assessment uses the main key. Separate keys can share the same organization quota. See the [Groq quickstart](https://console.groq.com/docs/quickstart).

### 4. Create the environment files

Copy backend/.env.example to backend/.env, and frontend/.env.example to frontend/.env.local.

On Windows PowerShell, from the repository root:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item frontend/.env.example frontend/.env.local
```

On macOS/Linux:

```sh
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

Fill backend/.env using your own values:

```dotenv
APP_ENV=development
APP_ORIGIN=http://localhost:5173
APP_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql+psycopg://postgres.PROJECT_REF:URL_ENCODED_PASSWORD@SESSION_POOLER_HOST:5432/postgres?sslmode=require
SUPABASE_URL=https://PROJECT_REF.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLIC_PUBLISHABLE_KEY
GROQ_API_KEY=YOUR_GROQ_API_KEY
GROQ_MODEL=openai/gpt-oss-120b
GROQ_STT_MODEL=whisper-large-v3-turbo
GROQ_INTERVIEW_TOKEN_BUDGET=7000
GROQ_COMMUNICATION_TOKEN_BUDGET=7000
```

Replace every placeholder. Use the exact host and username from your project's connection settings, not the literal example. If desired, add GROQ_COMMUNICATION_API_KEY and GROQ_COMMUNICATION_MODEL for a separate communication configuration. MIGRATION_DATABASE_URL is available for a separate migration connection; otherwise Alembic uses DATABASE_URL.

Fill frontend/.env.local:

```dotenv
VITE_SUPABASE_URL=https://PROJECT_REF.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=YOUR_PUBLIC_PUBLISHABLE_KEY
```

The frontend and backend use the same public Supabase project URL and publishable key. Only the backend receives database and Groq secrets. Never put them in VITE variables or commit real environment files. The environment templates contain placeholders only. Restart running servers after configuration changes; rebuild production frontend assets when public frontend values change.

### 5. Install dependencies and apply migrations

On Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
cd frontend
npm.cmd ci
cd ../backend
..\.venv\Scripts\python.exe -m alembic upgrade head
cd ..
```

On macOS/Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd frontend
npm ci
cd ../backend
../.venv/bin/python -m alembic upgrade head
cd ..
```

These commands create the application schema in the Supabase database you configured. You do not need to create the tables manually or import another user's history. Use a dedicated project for your copy.

### 6. Start the app

Open two terminals from the repository root.

**Terminal 1 - backend, Windows PowerShell:**

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

On macOS/Linux, use ../.venv/bin/python in place of the Windows Python executable.

**Terminal 2 - frontend, Windows PowerShell:**

```powershell
cd frontend
npm.cmd run dev
```

On macOS/Linux, use npm run dev.

Open **http://localhost:5173** and sign in with Google. The frontend development server forwards API requests to the backend on port 8000. Keep both terminals running. Allow microphone access to answer by voice; the camera is optional.

For native Render deployment of your own copy, follow [Deployment](docs/DEPLOYMENT.md). The Dockerfile is an optional alternative and is not used by the current live deployment.

## Results and feature coverage

The project delivers the complete preparation flow: document intake, JD/resume analysis, three interview levels, saved answer history, competency feedback, readiness, personalized preparation and PDF export.

Functional coverage includes:

- Google authentication and account-owned session histories.
- Resume/JD intake, extracted-text review and evidence-linked job-fit analysis.
- Screening, Competency and Deep Dive progression, with adaptive question generation and coverage tracking.
- Recorded answers, transcription review, typed answers and spoken question playback.
- Optional camera preview and an animated interviewer with speaking/listening states.
- Recovery from interrupted provider processing using saved answers and completed checkpoints.
- Seven report dimensions, explicit-skip handling, separate new attempts and preserved prior histories.
- Question-level feedback, prioritized preparation strategies and downloadable PDF reports.

The native Render deployment passed the frontend build, audio-decoding and CPU pause-model load check, application startup and health checks. Live Google sign-in, including a separate-account check, and product use were manually confirmed during deployment.

Automated backend tests cover ownership controls, input validation, interview progression, assessment/memory handling, reporting, communication/delivery rules and production configuration. The frontend build runs TypeScript checks. GitHub Actions provides backend-test and frontend-build checks for the repository.

To run the backend tests on Windows, from the repository root:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests -q
```

Feature coverage is not a measured code-coverage percentage or proof of scoring accuracy. No benchmark accuracy, hiring-prediction result or concurrent-user capacity is claimed.

## Limitations

- **Voice-first, with preview-only video.** The camera provides a local interview-style preview. Candidate video is not recorded, uploaded or used in assessment reports. Facial expressions and emotions are not evaluated.
- **Shared free-tier AI allowance.** The live demo uses the owner's configured provider account and free API quotas. Visitors share those limits. Analysis, transcription, assessment or report generation may pause when quotas are exhausted. Running your own copy requires your own provider configuration.
- **Free hosting constraints.** Render's free service can sleep after inactivity, introducing a cold-start delay. CPU and memory are limited; sustained or concurrent usage has not been load-tested. See [Render's current free-service limits](https://render.com/docs/free).
- **Document limitations.** OCR is not included. Scanned/image-only PDFs require pasted text. Uploads are limited to the supported formats and size; the app currently accepts up to 5 MB per file.
- **Provider and processing limits.** Large documents or unusually long answers require more processing and can still encounter model/rate limits despite bounded memory and chunking. Background jobs run inside the application process rather than a durable external queue; interrupted work may require retry from saved checkpoints. The supplied deployment uses one application worker.
Third-party interviewer assets and the bundled Silero model retain their original licenses. See frontend/public/assets/interviewer/ASSET_CREDITS.md and backend/app/assets/SILERO_LICENSE.
