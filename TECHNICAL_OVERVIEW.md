# Ace-it: Technical Overview

Ace-it is an AI interview practice application that uses a candidate's resume, a job description and the interview conversation to generate questions and preparation guidance.

## Architecture

The frontend uses React, TypeScript and Vite. FastAPI handles authentication checks, document processing, interview state, AI requests and reports. In production, FastAPI serves both the built frontend and the API through one Render URL. During local development, Vite forwards API requests to FastAPI.

Supabase provides Google sign-in and a PostgreSQL database. The backend verifies the signed-in user's token and checks ownership before accessing sessions. The database stores document text, analysis, questions, submitted answers, evaluations, interview memory and reports. Alembic manages schema migrations. Account histories are stored in the database, not in the repository.

Groq provides language-model inference and speech-to-text. Database credentials and Groq keys remain on the backend. Only the Supabase project URL and public publishable key are included in the browser configuration.

## AI/LLM approach

The AI workflow separates content assessment from communication assessment:

- **Content and interview flow:** Analyzes the resume and JD, evaluates answer content, extracts compact memory updates and generates the next question.
- **Communication:** Independently evaluates the latest answer's grammar, sentence structure and disruptive repetition. Its key and model can be configured separately, or it can use the main Groq configuration.

These are separate responsibilities; they do not require two different model providers. The default configuration uses openai/gpt-oss-120b for text tasks and whisper-large-v3-turbo for transcription, subject to account access and model availability.

Model responses use structured schemas and are validated before being accepted. Normal content assessment returns the answer assessment and a memory update together, avoiding an extra summarization request for every answer.

Python merges memory updates, removes exact duplicates, tracks discussed topics and selects relevant facts within a request budget. Optional archive consolidation runs in the background. Full answers remain stored separately for reports and evidence checking. Long answers can be processed in chunks, although provider limits still apply.

## Voice implementation

The browser records microphone audio and sends it to the backend for transcription through Groq. The candidate can review and correct the transcript before submitting it. Typed answers are also supported.

Question playback uses the browser's speech synthesis. A Three.js interviewer provides an animated visual panel with speaking and listening states. The optional camera is a local preview: candidate video is not recorded, uploaded or assessed.

After recording stops, PyAV decodes the audio and Silero VAD runs through CPU ONNX Runtime to identify internal speech gaps. These observations are aligned with transcription timestamps to help assess pauses within incomplete sentences. Silence before speaking or after the final spoken segment is excluded. Missing audio or failed measurements do not produce an invented pause penalty. The application does not retain the original audio recording.

## Dynamic questioning logic

The interview has three levels, with default budgets of 4 Screening, 4 Competency and 7 Deep Dive questions:

- **Screening:** Background, motivation, relevant experience, role fit and basic understanding.
- **Competency:** Practical knowledge, projects, problem solving, decisions and teamwork.
- **Deep Dive:** Deeper explanations, trade-offs, follow-up questions and realistic scenarios.

The question-generation prompt receives the role requirements, resume evidence, relevant conversation memory, current level, previous assessment and competency coverage. The model can clarify, simplify, deepen a topic or move to another topic according to the answer and remaining interview opportunities.

Prompt instructions distinguish explicit resume claims from inferred experience, discourage repeated or declined requests, and avoid assigning an unsupported technology to a project. When a topic is exhausted or the candidate cannot explain it further, the interviewer is instructed to move to another relevant area. Missing dimensions are highlighted to encourage broader coverage.

Python controls level progression, question budgets, saved state and validation. The LLM chooses the contextual question; the interview does not select its questions from a fixed list. Adaptive behaviour is model-driven and can still be imperfect.

## Evaluation methodology

Answer content is evaluated against a question-specific rubric. Assessable targeted competencies receive scores from 0 to 4, supported by answer evidence and explanations.

The report covers seven dimensions:

- Role fit.
- Technical knowledge.
- Problem solving.
- Communication.
- Confidence — clarity and ownership.
- Depth of understanding.
- Behavioural fit.

Confidence refers to observable explanation, supported positions and ownership of work. It does not infer personality or emotion, and honest uncertainty is not automatically penalized.

Communication is assessed independently across submitted answers, with equal answer weighting. Spelling and likely transcription mistakes are ignored. Qualifying repetitive fillers or expressions occurring at least five times receive a 2-percentage-point adjustment per identified expression. The longest confirmed internal pause within an unfinished sentence determines one pause adjustment per answer: 2 points when over 6 seconds, or 5 points when over 25 seconds. These adjustments affect communication, not unrelated dimensions. Typed answers have no audio-pause adjustment.

Python aggregates saved assessments, grouping related content evidence so repeated follow-ups do not count as independent topics. Explicit skips adjust assessed dimension scores once, and the overall score is the average of those adjusted dimensions. Unasked questions after an early end do not create an extra penalty.

Documented job fit is calculated separately from interview performance. Readiness uses available competency evidence and JD alignment. Missing evidence remains visible rather than being replaced by an invented assessment.

Question feedback includes strengths, improvements and the direction a stronger answer could take. A separate AI step generates the personalized summary and preparation plan, linking gaps to evidence, review topics, exercises and success checks. Scores can be shown while that narrative is processing. PDF export uses the saved report and does not require a new LLM call. The results are preparation estimates, not hiring predictions.

## Key technical decisions

- **Save before provider work:** Accepted answers and completed checkpoints are saved so temporary model failures can be retried without asking the candidate to answer again.
- **Bounded memory with full history retained:** Compact context reduces repeated input and request size, while full answers remain available for review.
- **Separate language and content assessment:** Communication is not treated as a substitute for technical correctness, and missing audio does not block text assessment.
- **Deterministic score aggregation:** Python calculates report totals and applies defined adjustments instead of asking an LLM to invent the final percentage.
- **Background work for optional processing:** Memory consolidation and report narrative work are separated from the immediate interaction where possible. Shared HTTP connections and fewer repeated database reads reduce avoidable overhead.
- **One service for the frontend and API:** Native Render deployment simplifies configuration and uses the same public origin. Build checks verify audio decoding and the CPU pause-detection model.
- **Preserve attempts and ownership:** A new attempt keeps a separate answer history. Owner checks protect account-specific data, alongside database access restrictions.

The current deployment uses one application worker. Background tasks run inside that process rather than through a durable external queue. Provider quotas, free-tier hosting resources, network latency and occasional repetitive AI questions remain practical limitations.
