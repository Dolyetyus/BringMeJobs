# BringMeJobs: Agent Build Plan

## Mission

Build a local-first personal job-discovery and application-assistance system. It runs on the user's computer, exposes a dashboard at `http://localhost:6767`, and executes scheduled searches without requiring a hosted backend.

The system may find, normalize, rank, enrich, and prepare applications. It must not submit an application, send a message, or make an irreversible change without an explicit user approval.

## Non-negotiable principles

1. **Local first:** CVs, writing samples, credentials, generated drafts, and application data stay local by default.
2. **Deterministic first:** use normal code for fetching, parsing, date windows, deduplication, filtering, scoring, caching, retries, and persistence. Use an LLM only where language understanding or generation is necessary.
3. **Human in the loop:** application submission always requires a visible approval step.
4. **Traceability:** every job, source, score, model decision, generated document, and user approval must be stored with timestamps and provenance.
5. **Explicit failures:** never silently convert a failed fetch, parse, model call, or browser action into a successful result.
6. **Provider abstraction:** local models and cloud APIs must be replaceable through one typed interface.
7. **Budget control:** enforce per-run token and cost limits, cache results, truncate inputs safely, and prefer batch/cheap models for ranking.
8. **Respect website rules:** use official APIs, feeds, public career pages, or user-provided portals where permitted. Do not bypass CAPTCHAs, authentication, rate limits, robots rules, or anti-bot controls.
9. **No model training by default:** represent writing style through local embeddings and retrieved examples, not repeated full-document prompts or fine-tuning.
10. **Security:** hash passwords with a modern password-hashing algorithm, encrypt or protect secrets, validate uploads, restrict local binds, and redact sensitive data from logs.

## Target architecture

Use a modular local web application:

- **Frontend:** dashboard, profile, configuration, jobs, job detail, application draft, and review screens.
- **Backend:** local HTTP API on port `6767`.
- **Database:** SQLite with migrations.
- **Scheduler:** Windows Task Scheduler and a cross-platform CLI entry point; cron support may be added for Linux/macOS.
- **Fetcher layer:** typed connectors for APIs, RSS/Atom feeds, JSON-LD career pages, and user-configured public job portals.
- **Browser assistance:** Playwright only for user-approved application-page inspection and form prefill. Never auto-submit.
- **LLM gateway:** one interface supporting a local Ollama-compatible endpoint and optional OpenAI/xAI-compatible cloud providers.
- **Document pipeline:** safe text extraction from PDF, DOCX, HTML, and plain text.
- **Retrieval:** local embeddings and a vector-capable SQLite strategy or sidecar index for profile and writing samples.

Keep components replaceable. Do not let UI code call providers, crawlers, or database internals directly.

## Delivery phases

### Phase 0: Repository and safety foundation

- Add a clear README, `.env.example`, `.gitignore`, license decision, and development commands.
- Add formatting, linting, type checking, test runner, and pre-commit checks appropriate to the chosen stack.
- Add configuration validation and a structured logger with secret redaction.
- Add a database migration mechanism.
- Add a local-only default bind (`127.0.0.1:6767`).
- Add a provider interface with a fake provider for tests.

### Phase 1: Authentication and candidate profile

- Implement local signup/login/logout.
- Store password hashes only; never store plaintext passwords.
- Add session expiration and CSRF protection if cookie-based authentication is used.
- Support CV upload and portfolio URL input.
- Extract candidate facts into a versioned structured profile.
- Let the user review, edit, add, or remove target titles, skills, locations, seniority, work authorization, salary preferences, and exclusions.
- Preserve the original uploaded files and the extracted version separately.

### Phase 2: Writing style profile

- Accept user-provided writing samples.
- Extract style attributes as an editable profile, such as tone, sentence length, formality, directness, vocabulary, and first-person preferences.
- Chunk and embed source samples locally.
- Retrieve relevant examples for each generated answer.
- Always show generated text as a draft with source examples and an edit history.

### Phase 3: Job-source connectors

Implement one connector at a time behind a common interface:

```text
search(source_config, search_window, filters) -> raw listings
normalize(raw listing) -> normalized job
health_check(source_config) -> status
```

Prioritize sources in this order:

1. Official job APIs with documented access.
2. Public feeds or structured career APIs such as Greenhouse, Lever, Ashby, Workable, or SmartRecruiters where available.
3. User-provided public company career pages.
4. Other public portals only after confirming their terms and technical stability.

Store connector errors and continue with other sources. Do not hide partial results.

### Phase 4: Incremental search and deterministic filtering

For each source, store the last successful run time.

The search window must be:

- First run: at most the previous 30 days.
- Later run: from the previous successful run to now.
- If the previous run is older than 30 days: only the previous 30 days.
- Never include jobs outside the selected source's available date range without marking the date as uncertain.

Use the following processing order:

1. Fetch.
2. Validate response and source metadata.
3. Normalize fields.
4. Canonicalize URLs.
5. Deduplicate.
6. Apply hard filters.
7. Compute deterministic score.
8. Send only borderline or high-value jobs to an LLM.
9. Persist all decisions.

The search must be idempotent. A failed run must not advance the successful-run timestamp.

### Phase 5: Ranking and compensation enrichment

Implement a transparent score with configurable weights:

- Target-title match.
- Required-skill overlap.
- Seniority.
- Location and remote preference.
- Work authorization.
- Salary compatibility.
- Industry/company preferences.
- Exclusions and missing hard requirements.

The LLM may explain ambiguity, infer related skills, and summarize fit, but must return strict structured JSON validated by a schema. Store model name, prompt version, input hash, output, and confidence.

Compensation estimates must distinguish:

- Employer-provided salary.
- Public salary range.
- User-entered estimate.
- Third-party estimate.
- Model inference.

Never present an inferred total compensation number as fact. Include the source, date, currency, and uncertainty range.

### Phase 6: Dashboard and configuration

Provide:

- Top matches with score explanation.
- New, reviewed, approved, rejected, and applied states.
- Source and last-run status.
- Search-window visibility.
- User-configurable locations, remote policy, titles, skills, exclusions, seniority, salary, source URLs, and schedule.
- Job detail with original URL and raw-source provenance.
- Manual re-run with dry-run mode.
- Cost/token usage dashboard.

### Phase 7: Application assistance

For an approved job only:

1. Open and inspect the apply page.
2. Detect fields and questions.
3. Pre-fill only fields with high-confidence mappings.
4. Generate draft answers using the candidate profile and retrieved writing samples.
5. Flag uncertainty and missing information.
6. Show every changed field to the user.
7. Require explicit confirmation before the user submits.

Do not defeat CAPTCHAs, hidden fields, anti-bot mechanisms, or login controls.

### Phase 8: CV adjustment

Add an “Adjust CV” action on a job detail page.

- Preserve factual truth.
- Never invent experience, skills, employers, dates, metrics, education, or authorization.
- Prefer reordering, emphasizing, and rephrasing existing evidence.
- Show a side-by-side diff.
- Store the base CV, job-specific version, prompt version, and approval state.
- Export to a user-selected format only after review.

### Phase 9: Reliability and polish

- Add connector contract tests with fixtures.
- Add migration tests.
- Add auth and upload security tests.
- Add deterministic date-window tests, including first-run, seven-day, and older-than-30-day cases.
- Add deduplication and idempotency tests.
- Add provider timeout, retry, budget, and malformed-JSON tests.
- Add Playwright tests for the local dashboard.
- Add an offline demo mode with fixture jobs.
- Add backup/export and deletion controls.
- Document setup, scheduling, provider configuration, and privacy behavior.

## LLM usage policy

Default routing:

- Local model: extraction, classification, embeddings, first-pass rewriting.
- Cheap cloud model: difficult classification, ambiguous job fit, compensation explanation.
- Strong model: only user-requested final drafts or hard application questions.

Every call must have:

- A purpose and prompt version.
- A maximum input and output token budget.
- A timeout and bounded retry policy.
- Schema validation where structured output is expected.
- An input-content hash for caching.
- Cost accounting.

Never send full CVs and all writing samples on every request. Retrieve only relevant profile fields and examples.

## Operational workflow

The scheduled job should:

1. Acquire a single-run lock.
2. Load and validate configuration.
3. Calculate source-specific date windows.
4. Fetch sources with bounded concurrency.
5. Normalize and deduplicate.
6. Apply deterministic filters and scores.
7. Run budgeted LLM analysis.
8. Enrich compensation only for the shortlist.
9. Persist results and metrics.
10. Release the lock.
11. Display a clear success, partial-success, or failure status in the dashboard.

Provide CLI commands for:

```text
bringmejobs doctor
bringmejobs search --dry-run
bringmejobs search
bringmejobs migrate
bringmejobs backup
bringmejobs cost
```

## Initial implementation constraints

- Start with one reliable source and fixture data before adding more connectors.
- Do not implement automatic final submission in the MVP.
- Do not add a hosted backend.
- Do not add fine-tuning.
- Do not put API keys in the database or repository.
- Do not commit CVs, writing samples, browser profiles, databases, logs, or generated applications.
- Keep all model prompts versioned in source control.

## Definition of done for the MVP

The MVP is complete when a local user can:

1. Create an account and log in.
2. Upload a CV or enter a portfolio URL.
3. Review and edit extracted profile keywords.
4. Add writing samples and review the style profile.
5. Configure locations, titles, filters, and at least one job source.
6. Run an incremental search with the specified date-window rules.
7. See deduplicated ranked jobs with transparent explanations.
8. Open a job detail page with source provenance and compensation uncertainty.
9. Generate a reviewed, job-specific CV draft and motivation-letter draft.
10. Inspect an apply page and prefill safe fields without automatic submission.
11. View logs, run status, and token/cost usage.
12. Run the complete flow offline against fixtures.

## Budget expectation

For a usable personal MVP, budget approximately 1–2 million coding-agent tokens. Normal runtime should target roughly 150,000–300,000 tokens per day before local-model savings. With deterministic filtering, caching, local embeddings, and local inference, the OpenAI API should be used as a bounded fallback rather than the default.
