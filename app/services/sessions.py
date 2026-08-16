"""In-memory conversation history.

v1 was stateless - every message was a fresh conversation, so "what about the
other one?" could never work. This keeps a short rolling window per session.

Deliberately in-process: state dies with the worker and is not shared across
replicas. That is fine for a single-container demo; see the README's
"What's upgradable" section for the Redis path when you outgrow it.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class SessionStore:
    def __init__(self, max_turns: int, ttl_seconds: int, max_sessions: int) -> None:
        self._max_messages = max_turns * 2  # a "turn" is one user + one bot
        self._ttl = ttl_seconds
        self._max_sessions = max_sessions
        self._lock = threading.Lock()
        # OrderedDict gives us LRU eviction for free via move_to_end.
        self._sessions: OrderedDict[str, tuple[float, deque[dict[str, str]]]] = (
            OrderedDict()
        )

    def history(self, session_id: str) -> list[dict[str, str]]:
        with self._lock:
            self._evict_expired()
            entry = self._sessions.get(session_id)
            if entry is None:
                return []
            self._sessions.move_to_end(session_id)
            return list(entry[1])

    def append(self, session_id: str, role: str, content: str) -> None:
        with self._lock:
            self._evict_expired()
            entry = self._sessions.get(session_id)
            if entry is None:
                entry = (time.monotonic(), deque(maxlen=self._max_messages))
                self._sessions[session_id] = entry
            entry[1].append({"role": role, "content": content})
            self._sessions[session_id] = (time.monotonic(), entry[1])
            self._sessions.move_to_end(session_id)

            while len(self._sessions) > self._max_sessions:
                self._sessions.popitem(last=False)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        """Caller must hold the lock."""
        cutoff = time.monotonic() - self._ttl
        expired = [k for k, (ts, _) in self._sessions.items() if ts < cutoff]
        for key in expired:
            del self._sessions[key]
