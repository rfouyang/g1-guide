from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Protocol

from loguru import logger

from component.action.action_trajectory import (
    ActionSafetyLimits,
    ActionTrajectory,
    ActionTrajectoryLoader,
    G1ArmContract,
)
from component.action.execution_policy import ExecutionPolicy
from component.action.motion_lease import MotionLease, MotionOwner
from util.g1_helper.g1_action_helper.arm_sdk_helper import G1ArmState
from util.g1_helper.g1_action_helper.trajectory_helper import TrajectoryHelper


class ArmCommandClient(Protocol):
    """Small hardware interface used by the action workflow."""

    def connect(self) -> None: ...

    def latest_state(self, **kwargs: object) -> G1ArmState: ...

    def wait_for_state(self, timeout: float) -> G1ArmState: ...

    def publish_arm_positions(
        self,
        arm_positions: Sequence[float],
        **kwargs: object,
    ) -> None: ...

    def release(self) -> None: ...


@dataclass(frozen=True)
class ActionExecution:
    """Outcome of one validated dry-run or live action request."""

    action_name: str
    sample_count: int
    duration_seconds: float
    hardware_executed: bool
    cancelled: bool


class ActionService:
    """Validate and run one two-arm action under the shared motion lease."""

    def __init__(
        self,
        loader: ActionTrajectoryLoader,
        execution_policy: ExecutionPolicy,
        motion_lease: MotionLease,
        **kwargs: object,
    ) -> None:
        self.loader = loader
        self.execution_policy = execution_policy
        self.motion_lease = motion_lease
        self.arm_client = kwargs.get("arm_client")
        self.base_is_stationary = kwargs.get("base_is_stationary")
        self.stop_base = kwargs.get("stop_base")
        self.clock = kwargs.get("clock", time.monotonic)
        self.sleeper = kwargs.get("sleeper", time.sleep)
        self.trajectory_helper = kwargs.get(
            "trajectory_helper",
            TrajectoryHelper(),
        )
        if not callable(self.clock) or not callable(self.sleeper):
            raise TypeError("clock and sleeper must be callable")

    def execute(
        self,
        action_name: str,
        operator_confirmed: bool = False,
        **kwargs: object,
    ) -> ActionExecution:
        trajectory = self.loader.load(action_name)
        authorization = self.execution_policy.authorize(operator_confirmed)
        if not authorization.hardware_enabled:
            dry_run = ActionExecution(
                action_name=trajectory.action_name,
                sample_count=trajectory.sample_count,
                duration_seconds=trajectory.duration_seconds,
                hardware_executed=False,
                cancelled=False,
            )
            return dry_run
        if not self.loader.contract.hardware_verified:
            raise PermissionError(
                "Live action playback is locked until the target G1 hardware "
                "contract is verified"
            )

        cancel_event = kwargs.get("cancel_event", Event())
        if not isinstance(cancel_event, Event):
            raise TypeError("cancel_event must be threading.Event")
        return self._execute_live(trajectory, cancel_event)

    def _execute_live(
        self,
        trajectory: ActionTrajectory,
        cancel_event: Event,
    ) -> ActionExecution:
        if self.arm_client is None:
            raise RuntimeError("Live action playback requires an arm client")
        if not callable(self.base_is_stationary) or not callable(self.stop_base):
            raise RuntimeError("Live action playback requires base safety callbacks")

        self.motion_lease.acquire(MotionOwner.PRESENTATION)
        cancelled = False
        try:
            self.arm_client.connect()
            arm_state = self.arm_client.wait_for_state(
                self.loader.safety_limits.state_timeout_seconds
            )
            self._preflight(arm_state)
            self._require_stationary_base()
            measured_arms = tuple(
                arm_state.positions[index]
                for index in self.loader.contract.arm_indices
            )
            self._validate_transition(measured_arms, trajectory)
            cancelled = self._transition_to_start(
                measured_arms,
                trajectory,
                cancel_event,
            )
            if not cancelled:
                cancelled = self._play_trajectory(trajectory, cancel_event)
            if cancelled:
                self.stop_base()
        except Exception:
            self.stop_base()
            raise
        finally:
            try:
                self.arm_client.release()
            finally:
                self.motion_lease.release(MotionOwner.PRESENTATION)

        execution = ActionExecution(
            action_name=trajectory.action_name,
            sample_count=trajectory.sample_count,
            duration_seconds=trajectory.duration_seconds,
            hardware_executed=True,
            cancelled=cancelled,
        )
        return execution

    def _preflight(self, arm_state: G1ArmState) -> None:
        arm_indices = self.loader.contract.arm_indices
        required_motor_count = max(arm_indices) + 1
        if (
            len(arm_state.positions) < required_motor_count
            or len(arm_state.temperatures) < required_motor_count
            or len(arm_state.motor_faults) < required_motor_count
        ):
            raise RuntimeError("G1 low state does not contain all arm motors")
        faulty_joints = [
            index for index in arm_indices if arm_state.motor_faults[index] != 0
        ]
        if faulty_joints:
            raise RuntimeError(f"Arm motor faults are active at DDS indices {faulty_joints}")
        hot_joints = [
            index
            for index in arm_indices
            if arm_state.temperatures[index]
            > self.loader.safety_limits.max_motor_temperature
        ]
        if hot_joints:
            raise RuntimeError(f"Arm motors exceed temperature limit at {hot_joints}")

    def _validate_transition(
        self,
        measured_arms: Sequence[float],
        trajectory: ActionTrajectory,
    ) -> None:
        limits = self.loader.safety_limits
        for measured, target, joint in zip(
            measured_arms,
            trajectory.joint_positions[0],
            self.loader.contract.arm_joints,
            strict=True,
        ):
            if not joint.lower <= measured <= joint.upper:
                raise RuntimeError(f"Measured position is unsafe for {joint.name}")
            position_delta = abs(float(target) - measured)
            transition_velocity = 1.5 * position_delta / limits.transition_seconds
            transition_acceleration = (
                6.0 * position_delta / limits.transition_seconds**2
            )
            if transition_velocity > limits.max_velocity:
                raise RuntimeError(f"Start transition is too fast for {joint.name}")
            if transition_acceleration > limits.max_acceleration:
                raise RuntimeError(
                    f"Start transition accelerates too fast for {joint.name}"
                )

    def _transition_to_start(
        self,
        measured_arms: Sequence[float],
        trajectory: ActionTrajectory,
        cancel_event: Event,
    ) -> bool:
        limits = self.loader.safety_limits
        step_count = max(
            1,
            math.ceil(limits.transition_seconds * limits.control_frequency_hz),
        )
        first_positions = trajectory.joint_positions[0]
        for step in range(step_count + 1):
            if self._should_cancel(cancel_event):
                return True
            ratio = step / step_count
            smooth_ratio = ratio * ratio * (3.0 - 2.0 * ratio)
            arm_positions = [
                measured + (target - measured) * smooth_ratio
                for measured, target in zip(
                    measured_arms,
                    first_positions,
                    strict=True,
                )
            ]
            self.arm_client.publish_arm_positions(
                arm_positions,
                kp=limits.arm_kp,
                kd=limits.arm_kd,
                weight=ratio,
            )
            self.sleeper(1.0 / limits.control_frequency_hz)
        return False

    def _play_trajectory(
        self,
        trajectory: ActionTrajectory,
        cancel_event: Event,
    ) -> bool:
        limits = self.loader.safety_limits
        period = 1.0 / limits.control_frequency_hz
        start_time = float(self.clock())
        next_elapsed = 0.0
        while next_elapsed < trajectory.duration_seconds:
            if self._should_cancel(cancel_event):
                return True
            arm_positions = self.trajectory_helper.sample(
                trajectory.timestamps,
                trajectory.joint_positions,
                next_elapsed,
            )
            self.arm_client.publish_arm_positions(
                arm_positions,
                kp=limits.arm_kp,
                kd=limits.arm_kd,
            )
            next_elapsed += period
            remaining = start_time + next_elapsed - float(self.clock())
            if remaining > 0.0:
                self.sleeper(remaining)

        if self._should_cancel(cancel_event):
            return True
        self.arm_client.publish_arm_positions(
            trajectory.joint_positions[-1],
            kp=limits.arm_kp,
            kd=limits.arm_kd,
        )
        logger.info("Completed two-arm action {}", trajectory.action_name)
        return False

    def _should_cancel(self, cancel_event: Event) -> bool:
        if cancel_event.is_set():
            return True
        self._require_stationary_base()
        current_state = self.arm_client.latest_state()
        self._preflight(current_state)
        return False

    def _require_stationary_base(self) -> None:
        if not self.base_is_stationary():
            raise RuntimeError("G1 base must remain stationary during an arm action")


def demo_action_service() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contract = G1ArmContract.load(project_root / "asset/g1_arm_contract.json")
    limits = ActionSafetyLimits.load(project_root / "config/action_safety.json")
    loader = ActionTrajectoryLoader(
        project_root / "data/actions/trajectories",
        contract,
        limits,
    )
    service = ActionService(
        loader=loader,
        execution_policy=ExecutionPolicy(),
        motion_lease=MotionLease(),
    )
    execution = service.execute("present_left")
    assert not execution.hardware_executed
    print(
        f"Action service: validated {execution.action_name} in dry-run mode, "
        "no robot command sent"
    )


def main() -> None:
    demo_action_service()


if __name__ == "__main__":
    main()
