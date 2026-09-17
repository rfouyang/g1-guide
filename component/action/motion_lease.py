from __future__ import annotations

from enum import Enum
from threading import Lock


class MotionOwner(Enum):
    """Workflows that may exclusively control physical movement."""

    IDLE = "idle"
    PRESENTATION = "presentation"
    NAVIGATION = "navigation"
    MAPPING = "mapping"
    MANUAL = "manual"


class MotionLease:
    """Allow only one workflow to own robot motion at a time."""

    def __init__(self) -> None:
        self._owner = MotionOwner.IDLE
        self._lock = Lock()

    @property
    def owner(self) -> MotionOwner:
        with self._lock:
            current_owner = self._owner
        return current_owner

    def acquire(self, owner: MotionOwner) -> None:
        if owner is MotionOwner.IDLE:
            raise ValueError("IDLE cannot acquire the motion lease")

        with self._lock:
            if self._owner is not MotionOwner.IDLE:
                raise RuntimeError(
                    f"Motion lease is already owned by {self._owner.value}"
                )
            self._owner = owner

    def release(self, owner: MotionOwner) -> None:
        with self._lock:
            if self._owner is not owner:
                raise RuntimeError(
                    f"Motion lease belongs to {self._owner.value}, not {owner.value}"
                )
            self._owner = MotionOwner.IDLE


def demo_motion_lease() -> None:
    lease = MotionLease()
    lease.acquire(MotionOwner.PRESENTATION)
    assert lease.owner is MotionOwner.PRESENTATION
    lease.release(MotionOwner.PRESENTATION)
    assert lease.owner is MotionOwner.IDLE
    print("Motion lease: exclusive acquire and release verified")


def main() -> None:
    demo_motion_lease()


if __name__ == "__main__":
    main()
