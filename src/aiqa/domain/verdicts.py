"""Failure latch for a required check. A later result does not clear it."""

from __future__ import annotations


class FailureLatch:
    """Remember a required violation. The stored word is the latch, not a screen verdict."""

    def __init__(self) -> None:
        self.final = ""

    def note(self, required: bool, status: str) -> str:
        if self.final == "FAIL":
            return self.final
        if required and status == "violated":
            self.final = "FAIL"
        return self.final
