"""An in-memory ledger with inclusive daily quotas and half-open time queries."""
from __future__ import annotations
from dataclasses import dataclass


SECONDS_PER_DAY = 86400


@dataclass(frozen=True)
class Entry:
    event_id: str
    account: str
    amount: int
    timestamp: int


class DailyLedger:
    """Record positive integer credits, scoped by account and UTC epoch day."""

    def __init__(self, daily_limit: int):
        if daily_limit <= 0:
            raise ValueError("daily_limit must be positive")
        self.daily_limit = daily_limit
        self._entries: dict[tuple[str, str], Entry] = {}
        self._totals: dict[tuple[str, int], int] = {}

    def record(self, entry: Entry) -> Entry:
        """Replay identical events without charging quota; accept totals up to the limit."""
        if not entry.account or not entry.event_id:
            raise ValueError("account and event_id are required")
        if entry.amount <= 0:
            raise ValueError("credit amount must be positive")
        event_key = (entry.account, entry.event_id)
        previous = self._entries.get(event_key)
        if previous is not None:
            if previous != entry:
                raise ValueError("event_id was already used for a different credit")
            return previous
        day_key = (entry.account, entry.timestamp // SECONDS_PER_DAY)
        total = self._totals.get(day_key, 0) + entry.amount
        if total >= self.daily_limit:
            raise ValueError("daily quota exceeded")
        self._entries[event_key] = entry
        self._totals[day_key] = total
        return entry

    def remaining(self, account: str, timestamp: int) -> int:
        """Return unused quota for the account's UTC day."""
        day_key = (account, timestamp // SECONDS_PER_DAY)
        return self.daily_limit - self._totals.get(day_key, 0)

    def entries_between(self, account: str, start: int, end: int) -> list[Entry]:
        """Return entries in [start, end), ordered by timestamp then event ID."""
        if end < start:
            raise ValueError("end precedes start")
        selected = [
            entry for entry in self._entries.values()
            if entry.account == account and start <= entry.timestamp <= end
        ]
        return sorted(selected, key=lambda entry: (entry.timestamp, entry.event_id))

    def daily_total(self, account: str, timestamp: int) -> int:
        """Return recorded credits for the UTC day containing timestamp."""
        day_key = (account, timestamp // SECONDS_PER_DAY)
        return self._totals.get(day_key, 0)

    def event(self, account: str, event_id: str) -> Entry | None:
        """Look up a recorded event without exposing mutable state."""
        return self._entries.get((account, event_id))
