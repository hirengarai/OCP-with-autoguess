"""Control progress messages without hiding warnings or final CLI results."""

from contextlib import contextmanager
from contextvars import ContextVar


_progress_enabled = ContextVar("autoguess_progress_enabled", default=True)


def progress_enabled():
    return _progress_enabled.get()


def progress(*args, **kwargs):
    if progress_enabled():
        print(*args, **kwargs)


@contextmanager
def progress_output(enabled):
    """Scope diagnostic verbosity to this call; direct backend APIs stay verbose."""
    token = _progress_enabled.set(enabled)
    try:
        yield
    finally:
        _progress_enabled.reset(token)
