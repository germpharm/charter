"""Charter home directory resolution.

Chokepoint for `~/.charter/` path lookups. Every module that reads or writes
under the Charter home should call `get_charter_home()` rather than building
the path itself, so that hosted multi-tenant deployments can isolate tenants
without touching the rest of the codebase.

Resolution order:
    1. `_charter_home_override` ContextVar — set by the MCP server's per-request
       middleware in multi-tenant deployments. Async-safe; each request gets
       its own context.
    2. `CHARTER_HOME` environment variable — for single-process overrides
       (tests, docker entrypoints).
    3. `~/.charter` — the historical default. Behavior unchanged for every
       existing single-tenant local install.
"""

import contextvars
import fcntl
import os
from contextlib import contextmanager


_charter_home_override: contextvars.ContextVar = contextvars.ContextVar(
    "charter_home_override", default=None
)


def get_charter_home() -> str:
    """Return the active Charter home directory for this call site.

    Multi-tenant servers set the ContextVar per request before dispatching
    into Charter; single-tenant local usage falls through to ~/.charter.
    """
    override = _charter_home_override.get()
    if override:
        return override
    env = os.environ.get("CHARTER_HOME")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".charter")


@contextmanager
def charter_home_scope(path: str):
    """Bind a Charter home for the duration of a `with` block.

    Used by the multi-tenant MCP middleware to scope each request to a
    specific tenant directory:

        with charter_home_scope(f"/data/tenants/{tenant_id}"):
            ...dispatch the MCP tool...
    """
    token = _charter_home_override.set(path)
    try:
        yield path
    finally:
        _charter_home_override.reset(token)


@contextmanager
def chain_write_lock(chain_path: str):
    """Advisory file lock around a chain write critical section.

    Acquired by every code path that appends to a JSONL chain file. Prevents
    two writers (e.g., two MCP server workers under multi-tenant load, or the
    Mini sync job overlapping with a live append) from interleaving partial
    writes and corrupting the hash chain.

    Lock file lives next to the chain (e.g., `chain.jsonl.lock`) so it
    inherits the chain's tenant isolation automatically.

    On non-Unix platforms (Windows), fcntl is unavailable; we degrade to a
    no-op rather than fail. Production targets Linux containers, so this
    only matters for local Windows dev.
    """
    os.makedirs(os.path.dirname(chain_path) or ".", exist_ok=True)
    lock_path = chain_path + ".lock"
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except (OSError, AttributeError):
            pass
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except (OSError, AttributeError):
            pass
        os.close(fd)
