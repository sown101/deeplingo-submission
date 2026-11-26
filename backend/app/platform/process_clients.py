"""Process-owned infrastructure cache. Imported aliases never capture sockets."""
import os
from threading import Lock


class ProcessClientCache:
    def __init__(self, factory, close=None):
        self.factory, self.close = factory, close
        self._pid, self._client = os.getpid(), None
        self._lock = Lock()
        if hasattr(os, "register_at_fork"):
            os.register_at_fork(after_in_child=self._after_fork)

    def _after_fork(self):
        # Do not acquire a parent's locked mutex or close inherited vendor state.
        self._pid, self._client = os.getpid(), None
        self._lock = Lock()

    def get(self):
        if self._pid != os.getpid():
            self._after_fork()
        with self._lock:
            if self._client is None:
                self._client = self.factory()
                self._pid = os.getpid()
            return self._client

    def shutdown(self):
        if self._pid != os.getpid():
            self._after_fork()
            return
        with self._lock:
            client, self._client, self._pid = self._client, None, os.getpid()
            if client is not None and self.close is not None:
                self.close(client)


class ProcessClientProxy:
    """Stable import alias resolves concrete state in current PID on each operation."""
    def __init__(self, owner):
        self._owner = owner

    def __getattr__(self, name):
        client = self._owner.client
        if client is None:
            raise RuntimeError("Supabase client is not configured")
        return getattr(client, name)

    def __bool__(self):
        return self._owner.is_connected()
