# BringMeJobs

Local-first AI job discovery and application assistant.

The project is currently in the planning/foundation stage. See [BUILD_PLAN.md](./BUILD_PLAN.md) for the implementation contract that coding agents must follow.

## Product boundary

BringMeJobs discovers and ranks jobs, explains fit, estimates compensation with uncertainty, and prepares application drafts. It does not submit applications without explicit user approval.

## Planned local URL

`http://127.0.0.1:6767`

## Planned provider strategy

- Local model first.
- Optional OpenAI/xAI-compatible provider for difficult or user-requested tasks.
- Token and cost budgets enforced per run.

## OpenAI $10 build credit

The $10 balance should be enough for a meaningful MVP build and several polish/debugging cycles if used carefully, especially with caching, short prompts, structured outputs, and cheaper models. It is not a safe budget for repeatedly sending full repositories, CVs, job pages, and long browser traces to a premium model.

Keep the API key in a local environment file or operating-system secret store. Never commit it.
