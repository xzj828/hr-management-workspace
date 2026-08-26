from contextlib import contextmanager
from functools import wraps
import threading

from django.db import connection


# The desktop deployment uses one Waitress process with multiple request
# threads. SQLite's BEGIN IMMEDIATE supplies the cross-process/database fence;
# this re-entrant lock also prevents shared-cache/threaded SQLite from raising
# an immediate "database table is locked" before its busy timeout can apply.
_sqlite_lifecycle_lock = threading.RLock()


@contextmanager
def sqlite_lifecycle_serialized():
    if connection.vendor != "sqlite":
        yield
        return
    with _sqlite_lifecycle_lock:
        yield


def serialize_sqlite_lifecycle(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with sqlite_lifecycle_serialized():
            return function(*args, **kwargs)

    return wrapped
