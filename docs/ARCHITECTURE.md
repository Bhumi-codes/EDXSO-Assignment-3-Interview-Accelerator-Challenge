# Architecture

## Application boundary

The frontend and API share one public origin. Development uses Vite's `/api` proxy; production serves Vite assets through FastAPI. PostgreSQL stores account-owned sessions, document snapshots, requirements, interview levels/turns, evaluations and reports. Alembic owns schema changes; no candidate data is seeded.

## Identity and storage

The browser signs in through Supabase Google OAuth and sends its bearer token to the API. The API verifies that token through Supabase before accepting the user identity. Session access uses explicit owner predicates; browser-supplied owner IDs are rejected. Database row-level security is enabled and direct browser-role table access is revoked. A privileged database connection can bypass RLS, so API owner checks remain essential; use appropriately scoped server credentials in deployment.

## Analysis and interviews

Document parsing preserves evidence references and separates explicit claims from inference. Job fit is computed from canonical requirement matches. Interviews progress through four Screening, four Competency and seven Deep Dive questions, with bounded follow-up chains. Accepted answers are immutable; attempts can end permanently, and a new attempt has a separate answer history.

Content assessment and question generation are sequential. Normal-answer assessment also extracts a source-linked memory update. Long answers are processed completely in chunks. Python maintains canonical records, selects a bounded context window and tracks coverage. Optional archive consolidation runs after the response and never blocks question generation. Limits, hypotheses and incomplete evidence remain distinct from completed experience.

Communication assessment runs independently from content. It evaluates language and redundant expressions; Python applies deterministic delivery adjustments using available observations. Typed answers have no audio-pause deduction. All seven scored dimensions permit a readiness conclusion from available assessments. Missing individual assessments remain recoverable and visible.

## Voice and avatar

The browser records audio temporarily, sends it for transcription and lets the user review accepted text. Local Silero VAD aligns internal gaps with transcription timestamps. Browser speech synthesis plays questions; Three.js animates the licensed interviewer. Camera preview stays in the browser and is not uploaded or scored.

## Recovery and execution

Answers and completed processing checkpoints are committed before provider work. Operation tokens prevent stale interview work from replacing newer state. Background jobs have independent database sessions and guarded merges. Provider HTTP connections are pooled for the application lifespan. Background tasks are process-local, not an external durable queue; retries use saved progress after interruption. Use a single Uvicorn worker as configured.

## Reports

Python computes dimension/overall/readiness results from saved assessments. A separate model call generates evidence-linked narrative guidance and preparation actions. PDF export is read-only and does not call a model. No response-duration section is included in reports.
