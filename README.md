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

Open `http://127.0.0.1:6767`.

Use **Discovery** for new listings, **Saved Jobs** for retained listings, and
**Config** for careers pages and configurable title filters.

The search pipeline filters European engineering roles by include/exclude title
patterns, deduplicates using canonical listing URLs, and stores run logs and
source-health checks in SQLite. Discarded listings keep only their internal ID
and URL key; saved listings retain full metadata.

The initial catalog contains 50 curated technology, AI, hardware, and fintech
companies. Local databases, logs, uploads, and environment files are ignored
by Git.

BringMeJobs does not submit applications for now.

For Windows startup, register `scripts/windows-startup.ps1` in Task Scheduler.
Adjust the WSL distro and repository path in the script if needed.