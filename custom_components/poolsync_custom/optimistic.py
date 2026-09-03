"""Shared optimistic-write tracking for PoolSync write entities."""

from __future__ import annotations


class PoolSyncOptimisticMixin:
    """Track an optimistic write until a post-write refresh confirms it.

    Write entities set their displayed value immediately after a successful
    write, then keep it until a coordinator fetch that started *after* the
    write completes. The coordinator's monotonic ``refresh_seq`` distinguishes
    a pre-write read-back (which would revert the optimistic value) from a
    post-write read-back (which supersedes it).
    """

    _optimistic: bool
    _optimistic_seq: int

    def _init_optimistic(self) -> None:
        """Initialize optimistic-write tracking."""
        self._optimistic = False
        self._optimistic_seq = self.coordinator.refresh_seq

    def _begin_optimistic_write(self) -> int:
        """Capture the coordinator sequence before a write."""
        return self.coordinator.refresh_seq

    def _commit_optimistic_write(self, seq_before: int) -> None:
        """Mark the entity optimistic after a successful write."""
        self._optimistic = True
        self._optimistic_seq = seq_before

    def _clear_optimistic_if_stale(self) -> None:
        """Clear the optimistic flag once a post-write refresh has completed."""
        if self._optimistic and self.coordinator.refresh_seq > self._optimistic_seq:
            self._optimistic = False

    @property
    def _optimistic_pending(self) -> bool:
        """Return True while an optimistic write awaits post-write data."""
        return self._optimistic
