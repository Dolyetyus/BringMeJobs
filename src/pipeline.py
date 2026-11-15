"""Search pipeline entry points.

The pipeline owns the repeatable fetch, normalize, filter, deduplicate, and
persist workflow. Keeping this boundary separate lets the CLI, web UI, and
scheduled dispatcher use the same search operation.
"""

from .app import run_search

__all__ = ["run_search"]
