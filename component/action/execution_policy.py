from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExecutionMode(Enum):
    """Available application execution modes."""

    DRY_RUN = "dry_run"
    LIVE = "live"


@dataclass(frozen=True)
class ExecutionAuthorization:
    """Resolved permission to access hardware boundaries."""

    mode: ExecutionMode
    hardware_enabled: bool


class ExecutionPolicy:
    """Fail closed unless live mode and operator confirmation are explicit."""

    def __init__(self, mode: ExecutionMode = ExecutionMode.DRY_RUN) -> None:
        self.mode = mode

    def authorize(self, operator_confirmed: bool) -> ExecutionAuthorization:
        if self.mode is ExecutionMode.LIVE and not operator_confirmed:
            raise PermissionError("Live mode requires operator confirmation")

        hardware_enabled = self.mode is ExecutionMode.LIVE
        authorization = ExecutionAuthorization(
            mode=self.mode,
            hardware_enabled=hardware_enabled,
        )
        return authorization


def demo_execution_policy() -> None:
    policy = ExecutionPolicy()
    authorization = policy.authorize(operator_confirmed=False)
    assert not authorization.hardware_enabled
    print("Execution policy: dry-run mode, hardware disabled")


def main() -> None:
    demo_execution_policy()


if __name__ == "__main__":
    main()
