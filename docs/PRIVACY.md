# Privacy and data operation

The release contains application source, schema migrations, required assets and synthetic automated tests. It contains no local credentials, user histories, resumes, job descriptions, tokens, database dumps or recordings.

Authentication belongs to Supabase. The application verifies the signed-in user before accessing session data and uses owner-filtered queries. Separate accounts do not share interview histories. The same account on the same database retains its existing records after deployment. No destructive reset or sample-data import runs automatically.

Candidate documents and accepted answer text are sent to the configured AI provider as needed for analysis, transcription, assessment and relevant interview context. Provider retention follows the account's settings and terms. Camera video is not uploaded or analyzed. Audio is not retained by this application after processing. Stored text/evaluations support history, retry and reports.

Credentials are supplied through environment configuration. Only Supabase's public project URL and publishable/anon key belong in browser build variables. Private server credentials must not be placed in frontend configuration, logs or exports.

The app currently has no self-service account/history deletion feature. Operational retention and deletion requests must be handled by the database/project administrator. Database backup/export procedures must remain outside the repository.
