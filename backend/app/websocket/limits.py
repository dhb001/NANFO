"""Per-user concurrent WebSocket admission (ADR-028 C1).

Counted per API process across all four channels. Exceeding the cap yields
``WS_CONNECTION_LIMIT`` + close 1008; clients stop and offer a manual retry.
"""

from __future__ import annotations


class ConnectionRegistry:
    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def acquire(self, user_id: str, limit: int) -> bool:
        current = self._counts.get(user_id, 0)
        if current >= limit:
            return False
        self._counts[user_id] = current + 1
        return True

    def release(self, user_id: str) -> None:
        current = self._counts.get(user_id, 0)
        if current <= 1:
            self._counts.pop(user_id, None)
        else:
            self._counts[user_id] = current - 1

    def count(self, user_id: str) -> int:
        return self._counts.get(user_id, 0)


connection_registry = ConnectionRegistry()
