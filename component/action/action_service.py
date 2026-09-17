from __future__ import annotations

import math
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Event, Thread
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
    """Validate and run one two-arm action under the shared motion lease.

    On the biped G1, ``stop_base`` must stop walking requests while preserving
    the robot's standing/balance controller. It must never disable leg motors,
    request damping, or change posture. Arm authority release is a control
    handoff, not proof that the robot has physically stopped safely.
    """

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
        self.live_guard = kwargs.get("live_guard")
        self.clock = kwargs.get("clock", time.monotonic)
        self.sleeper = kwargs.get("sleeper", time.sleep)
        self.trajectory_helper = kwargs.get(
            "trajectory_helper",
            TrajectoryHelper(),
        )
        self.initial_state_wait_seconds = 5.0
        self.cleanup_timeout_seconds = 1.0
        if not callable(self.clock) or not callable(self.sleeper):
            raise TypeError("clock and sleeper must be callable")

    def execute(
        self,
        action_name: str,
        operator_confirmed: bool = False,
        *,
        commissioning: bool = False,
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
        if commissioning:
            if action_name != "present_left" or not callable(self.live_guard):
                raise PermissionError(
                    "Commissioning requires present_left and a live state guard"
                )
            self.live_guard()
            trajectory = replace(trajectory, timestamps=trajectory.timestamps * 4.0)
        elif not self.loader.contract.hardware_verified:
            raise PermissionError(
                "Live action playback is locked until the target G1 hardware "
                "contract is verified"
            )

        cancel_event = kwargs.get("cancel_event", Event())
        if not isinstance(cancel_event, Event):
            raise TypeError("cancel_event must be threading.Event")
        return self._execute_live(trajectory, cancel_event, commissioning)

    def _execute_live(
        self,
        trajectory: ActionTrajectory,
        cancel_event: Event,
        commissioning: bool = False,
    ) -> ActionExecution:
        if self.arm_client is None:
            raise RuntimeError("Live action playback requires an arm client")
        if not callable(self.base_is_stationary):
            raise RuntimeError("Live action playback requires a stationary-state reader")

        self.motion_lease.acquire(MotionOwner.PRESENTATION)
        cancelled = False
        execution_error: BaseException | None = None
        try:
            self.arm_client.connect()
            arm_state = self.arm_client.wait_for_state(
                self.initial_state_wait_seconds
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
            if commissioning and not cancelled:
                cancelled = self._return_and_release(measured_arms, cancel_event)
        except BaseException as error:
            execution_error = error
            raise
        finally:
            cleanup_errors = self._cleanup()
            if not cleanup_errors:
                self.motion_lease.release(MotionOwner.PRESENTATION)
            elif execution_error is None:
                raise RuntimeError(
                    "Action cleanup failed; motion lease retained: "
                    + "; ".join(cleanup_errors)
                )
            else:
                logger.error(
                    "Action cleanup failed; motion lease retained: {}", cleanup_errors
                )

        execution = ActionExecution(
            action_name=trajectory.action_name,
            sample_count=trajectory.sample_count,
            duration_seconds=trajectory.duration_seconds,
            hardware_executed=True,
            cancelled=cancelled,
        )
        return execution

    def _cleanup(self) -> list[str]:
        """Attempt independent stops; retain ownership if completion is unknown.

        A timed-out Python thread cannot be killed. Its callback may still finish
        later, so no subsequent motion owner may acquire this lease.
        """
        operations = [
            ("arm release", self.arm_client.release),
        ]
        if callable(self.stop_base):
            operations.append(("base stop", self.stop_base))
        attempts = [StopAttempt(name, callback) for name, callback in operations]
        for attempt in attempts:
            attempt.start()
        deadline = time.monotonic() + self.cleanup_timeout_seconds
        for attempt in attempts:
            attempt.finished.wait(max(0.0, deadline - time.monotonic()))
        failures = [attempt.failure for attempt in attempts if attempt.failure]
        return failures

    def _preflight(self, arm_state: G1ArmState) -> None:
        state_age = float(self.clock()) - arm_state.received_at
        if (
            not math.isfinite(state_age)
            or not 0 <= state_age <= self.loader.safety_limits.state_timeout_seconds
        ):
            raise RuntimeError("G1 arm state is stale or has an invalid timestamp")
        if arm_state.mode_machine != self.loader.contract.mode_machine:
            raise RuntimeError("G1 mode_machine does not match the action contract")
        arm_indices = self.loader.contract.arm_indices
        required_motor_count = max(arm_indices) + 1
        if (
            len(arm_state.positions) < required_motor_count
            or len(arm_state.temperatures) < required_motor_count
            or len(arm_state.motor_faults) < required_motor_count
        ):
            raise RuntimeError("G1 low state does not contain all arm motors")
        for joint in self.loader.contract.arm_joints:
            position = arm_state.positions[joint.dds_index]
            if (
                not math.isfinite(position)
                or not joint.lower <= position <= joint.upper
            ):
                raise RuntimeError(f"Measured position is unsafe for {joint.name}")
        if any(
            not math.isfinite(arm_state.temperatures[index]) for index in arm_indices
        ):
            raise RuntimeError("Arm motor temperatures must be finite")
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
        expected_positions = measured_arms
        period = 1.0 / limits.control_frequency_hz
        deadline = float(self.clock())
        for step in range(step_count + 1):
            if self._should_cancel(cancel_event, expected_positions):
                return True
            self._require_deadline(deadline, period)
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
            expected_positions = arm_positions
            deadline += period
            self.sleeper(max(0.0, deadline - float(self.clock())))
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
        expected_positions = trajectory.joint_positions[0]
        while next_elapsed < trajectory.duration_seconds:
            if self._should_cancel(cancel_event, expected_positions):
                return True
            self._require_deadline(start_time + next_elapsed, period)
            arm_positions = self.trajectory_helper.sample(
                trajectory.timestamps,
                trajectory.joint_positions,
                next_elapsed,
            )
            expected_positions = arm_positions
            self.arm_client.publish_arm_positions(
                arm_positions,
                kp=limits.arm_kp,
                kd=limits.arm_kd,
            )
            next_elapsed += period
            remaining = start_time + next_elapsed - float(self.clock())
            if remaining > 0.0:
                self.sleeper(remaining)

        if self._should_cancel(cancel_event, expected_positions):
            return True
        self._require_deadline(start_time + next_elapsed, period)
        self.arm_client.publish_arm_positions(
            trajectory.joint_positions[-1],
            kp=limits.arm_kp,
            kd=limits.arm_kd,
        )
        self.sleeper(period)
        if self._should_cancel(cancel_event, trajectory.joint_positions[-1]):
            return True
        logger.info("Completed two-arm action {}", trajectory.action_name)
        return False

    def _require_deadline(self, deadline: float, period: float) -> None:
        lateness = float(self.clock()) - deadline
        if not math.isfinite(lateness) or lateness > period:
            raise RuntimeError("Arm control-loop deadline missed")

    def _should_cancel(
        self, cancel_event: Event, expected_positions: Sequence[float]
    ) -> bool:
        if cancel_event.is_set():
            return True
        self._require_stationary_base()
        current_state = self.arm_client.latest_state()
        self._preflight(current_state)
        for index, expected in zip(
            self.loader.contract.arm_indices, expected_positions, strict=True
        ):
            tracking_error = abs(current_state.positions[index] - expected)
            if tracking_error > self.loader.safety_limits.max_tracking_error:
                raise RuntimeError(
                    f"Arm tracking error exceeds limit at DDS index {index}"
                )
        return False

    def _require_stationary_base(self) -> None:
        if callable(self.live_guard):
            self.live_guard()
        if not self.base_is_stationary():
            raise RuntimeError("G1 base must remain stationary during an arm action")

    def _return_and_release(
        self, starting_positions: Sequence[float], cancel_event: Event
    ) -> bool:
        """Return to measured starting arms, then fade SDK authority like upstream."""
        limits = self.loader.safety_limits
        state = self.arm_client.latest_state()
        self._preflight(state)
        current = tuple(state.positions[i] for i in self.loader.contract.arm_indices)
        max_delta = max(abs(a - b) for a, b in zip(current, starting_positions))
        duration = max(
            8.0,
            1.5 * max_delta / limits.max_velocity,
            math.sqrt(6.0 * max_delta / limits.max_acceleration),
        )
        period = 1.0 / limits.control_frequency_hz
        steps = math.ceil(duration / period)
        expected = current
        deadline = float(self.clock())
        for step in range(steps + 1):
            if self._should_cancel(cancel_event, expected):
                return True
            self._require_deadline(deadline, period)
            ratio = step / steps
            blend = ratio * ratio * (3.0 - 2.0 * ratio)
            expected = tuple(
                a + (b - a) * blend for a, b in zip(current, starting_positions)
            )
            self.arm_client.publish_arm_positions(
                expected, kp=limits.arm_kp, kd=limits.arm_kd
            )
            deadline += period
            self.sleeper(max(0.0, deadline - float(self.clock())))
        # During handoff the standing controller may choose a different arm pose;
        # continue health/stationary checks, but don't compare to our old target.
        for step in range(151):
            if cancel_event.is_set():
                return True
            self._require_stationary_base()
            self._preflight(self.arm_client.latest_state())
            self._require_deadline(deadline, period)
            self.arm_client.publish_arm_positions(
                starting_positions, kp=limits.arm_kp, kd=limits.arm_kd,
                weight=1.0 - step / 150,
            )
            deadline += period
            self.sleeper(max(0.0, deadline - float(self.clock())))
        return False


class StopAttempt:
    """Run one potentially blocking stop without delaying another stop."""

    def __init__(self, name: str, callback: Callable[[], object]) -> None:
        self.name = name
        self.callback = callback
        self.finished = Event()
        self.error: BaseException | None = None

    def start(self) -> None:
        Thread(target=self._run, daemon=True, name=self.name).start()

    def _run(self) -> None:
        try:
            self.callback()
        except BaseException as error:
            self.error = error
        finally:
            self.finished.set()

    @property
    def failure(self) -> str:
        if not self.finished.is_set():
            return f"{self.name} timed out"
        if self.error is not None:
            return f"{self.name}: {type(self.error).__name__}"
        return ""


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
