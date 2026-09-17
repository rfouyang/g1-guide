from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from component.action.action_service import ActionService
from component.action.action_trajectory import (
    ActionSafetyLimits,
    ActionTrajectoryLoader,
    G1ArmContract,
)
from component.action.execution_policy import ExecutionMode, ExecutionPolicy
from component.action.motion_lease import MotionLease, MotionOwner


@dataclass(frozen=True)
class ApplicationStatus:
    """Small operator-facing snapshot of application safety state."""

    mode: ExecutionMode
    hardware_enabled: bool
    motion_owner: MotionOwner


class GuideApplication:
    """Composition root for guide services and shared safety state."""

    def __init__(
        self,
        execution_policy: ExecutionPolicy,
        motion_lease: MotionLease,
        action_service: ActionService,
    ) -> None:
        self.execution_policy = execution_policy
        self.motion_lease = motion_lease
        self.action_service = action_service

    def status(self) -> ApplicationStatus:
        authorization = self.execution_policy.authorize(operator_confirmed=False)
        application_status = ApplicationStatus(
            mode=authorization.mode,
            hardware_enabled=authorization.hardware_enabled,
            motion_owner=self.motion_lease.owner,
        )
        return application_status


class ApplicationFactory:
    """Construct the application without initializing external systems."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path(__file__).resolve().parents[1]

    def create_dry_run(self) -> GuideApplication:
        execution_policy = ExecutionPolicy(mode=ExecutionMode.DRY_RUN)
        motion_lease = MotionLease()
        arm_contract = G1ArmContract.load(
            self.project_root / "asset/g1_arm_contract.json"
        )
        safety_limits = ActionSafetyLimits.load(
            self.project_root / "config/action_safety.json"
        )
        trajectory_loader = ActionTrajectoryLoader(
            self.project_root / "data/actions/trajectories",
            arm_contract,
            safety_limits,
        )
        action_service = ActionService(
            loader=trajectory_loader,
            execution_policy=execution_policy,
            motion_lease=motion_lease,
        )
        guide_application = GuideApplication(
            execution_policy=execution_policy,
            motion_lease=motion_lease,
            action_service=action_service,
        )
        return guide_application


def demo_application() -> None:
    application = ApplicationFactory().create_dry_run()
    application_status = application.status()
    assert not application_status.hardware_enabled
    assert application_status.motion_owner is MotionOwner.IDLE
    action_execution = application.action_service.execute("present_left")
    assert not action_execution.hardware_executed
    print(
        "G1 Guide: dry-run ready, present_left validated, hardware disabled"
    )


def main() -> None:
    demo_application()


if __name__ == "__main__":
    main()
