# BringMeJobs

Local-first job discovery and review dashboard. The main idea is to automatically query the
most prestigious or high-paying tech companies in Europe to find new engineering job listings
so the good jobs end up on my table rather than me going through dozens of websites every day.

## Run locally

```bash
python3 bringmejobs.py migrate
python3 -m src.dispatcher
python3 bringmejobs.py serve
```

Open `http://127.0.0.1:6767` (SIX-SEVEEEEN).

Use **Config** to add and edit official careers pages or permitted JSON feeds.
The search pipeline filters European engineering roles, currently excludes senior and
early-career listings, deduplicates results, and stores run logs in SQLite.
Config also includes source-access health checks and timestamps.

The initial catalog contains 50 curated technology, AI, hardware, and fintech
companies. Local databases, logs, uploads, and environment files are ignored
by Git.

BringMeJobs does not submit applications for now.