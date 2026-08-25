# Bounded Change Logs

Create one concise Markdown log per approved phase or bounded repository change. Name it after the phase or change, and update it only at meaningful verification boundaries.

Each log records:

- approved scope and non-goals;
- focused checks and their exact results;
- final Browser or manual checks when applicable;
- final `make preflight` result;
- independent review and accepted remediation summary;
- PR-head CI and integration result when publishing is authorized;
- blocked, skipped, manual, cloud, GPU, voice, and external-channel checks.

Do not append a new entry after every small remediation. Preserve full command transcripts outside the model context when needed and record only the command, exit status, concise outcome, and artifact path here.

`harness/build-log.md` remains the historical log through the Harness v2 migration. It is not the default destination for new entries and should be read only for a named historical claim or audit.
