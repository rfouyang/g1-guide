from __future__ import annotations

import time
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event

from component.action.action_service import ActionService
from component.action.action_trajectory import (
    ActionSafetyLimits,
    ActionTrajectoryLoader,
    G1ArmContract,
)
from component.action.execution_policy import ExecutionMode, ExecutionPolicy
from component.action.motion_lease import MotionLease, MotionOwner
from util.g1_helper.g1_action_helper.arm_sdk_helper import G1ArmState


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeArmClient:
    def __init__(self, state: G1ArmState) -> None:
        self.state = state
        self.connected = False
        self.commands: list[tuple[float, ...]] = []
        self.released = False
        self.clock = time.monotonic
        self.track_commands = True
        self.refresh_state = True
        self.wait_timeout = None
        self.weights: list[float] = []

    def connect(self) -> None:
        self.connected = True

    def latest_state(self, **_: object) -> G1ArmState:
        if self.refresh_state:
            self.state = replace(self.state, received_at=self.clock())
        return self.state

    def wait_for_state(self, _: float) -> G1ArmState:
        self.wait_timeout = _
        return self.latest_state()

    def publish_arm_positions(
        self,
        arm_positions: object,
        **_: object,
    ) -> None:
        self.commands.append(tuple(float(value) for value in arm_positions))
        weight = float(_.get("weight", 1.0))
        self.weights.append(weight)
        if self.track_commands:
            positions = list(self.state.positions)
            positions[15:29] = self.commands[-1]
            self.state = replace(self.state, positions=tuple(positions))

    def release(self) -> None:
        self.released = True


class ActionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        contract = G1ArmContract.load(project_root / "asset/g1_arm_contract.json")
        limits = ActionSafetyLimits.load(project_root / "config/action_safety.json")
        self.loader = ActionTrajectoryLoader(
            project_root / "data/actions/trajectories",
            contract,
            limits,
        )
        self.motion_lease = MotionLease()

    def test_dry_run_validates_without_touching_hardware(self) -> None:
        service = ActionService(
            loader=self.loader,
            execution_policy=ExecutionPolicy(),
            motion_lease=self.motion_lease,
        )

        execution = service.execute("present_left")

        self.assertFalse(execution.hardware_executed)
        self.assertFalse(execution.cancelled)
        self.assertEqual(execution.sample_count, 101)
        self.assertIs(self.motion_lease.owner, MotionOwner.IDLE)

    def test_live_run_requires_operator_confirmation(self) -> None:
        service = ActionService(
            loader=self.loader,
            execution_policy=ExecutionPolicy(ExecutionMode.LIVE),
            motion_lease=self.motion_lease,
        )

        with self.assertRaisesRegex(PermissionError, "operator confirmation"):
            service.execute("present_left")

    def test_live_run_remains_locked_before_hardware_verification(self) -> None:
        service = ActionService(
            loader=self.loader,
            execution_policy=ExecutionPolicy(ExecutionMode.LIVE),
            motion_lease=self.motion_lease,
        )

        with self.assertRaisesRegex(PermissionError, "hardware contract"):
            service.execute("present_left", operator_confirmed=True)

    def test_verified_live_path_uses_arm_only_commands_and_releases_lease(self) -> None:
        verified_loader, arm_client = self._verified_loader_and_client()
        clock = FakeClock()
        arm_client.clock = clock
        service = ActionService(
            loader=verified_loader,
            execution_policy=ExecutionPolicy(ExecutionMode.LIVE),
            motion_lease=self.motion_lease,
            arm_client=arm_client,
            base_is_stationary=lambda: True,
            stop_base=lambda: None,
            clock=clock,
            sleeper=clock.sleep,
        )

        execution = service.execute("present_left", operator_confirmed=True)

        self.assertTrue(execution.hardware_executed)
        self.assertFalse(execution.cancelled)
        self.assertTrue(arm_client.connected)
        self.assertTrue(arm_client.released)
        self.assertGreater(len(arm_client.commands), 200)
        self.assertTrue(all(len(command) == 14 for command in arm_client.commands))
        self.assertIs(self.motion_lease.owner, MotionOwner.IDLE)

    def test_tracking_divergence_stops_and_releases(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        arm_client.track_commands = False
        with self.assertRaisesRegex(RuntimeError, "tracking error"):
            service.execute("present_left", operator_confirmed=True)
        self.assertTrue(arm_client.released)
        self.assertEqual(stops, [True])
        self.assertIs(self.motion_lease.owner, MotionOwner.IDLE)

    def test_tracking_error_reports_observed_expected_error_and_limit(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        arm_client.track_commands = False
        with self.assertRaisesRegex(
            RuntimeError,
            r"observed=.*expected=.*error=.*limit=0\.010000",
        ):
            service.execute("present_left", operator_confirmed=True)

    def test_commissioning_runs_once_without_verification_or_base_commands(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        service.loader = self.loader
        service.live_guard = lambda: True
        service.stop_base = None
        initial_arms = arm_client.state.positions[15:29]
        execution = service.execute("present_left", True, commissioning=True)
        self.assertFalse(self.loader.contract.hardware_verified)
        self.assertEqual(execution.duration_seconds, 16.0)
        self.assertEqual(arm_client.commands[-1], initial_arms)
        self.assertEqual(arm_client.weights[-1], 0.0)
        self.assertTrue(all(weight == 1.0 for weight in arm_client.weights[:101]))
        self.assertEqual(stops, [])
        self.assertGreater(clock.now, 29.0)
        self.assertTrue(arm_client.released)

    def test_commissioning_requires_live_guard(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        service.loader = self.loader
        with self.assertRaisesRegex(PermissionError, "live state guard"):
            service.execute("present_left", True, commissioning=True)
        self.assertFalse(arm_client.connected)

    def test_commissioning_guard_failure_prevents_connection(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        service.loader = self.loader
        service.live_guard = self._fail_stop
        with self.assertRaisesRegex(RuntimeError, "injected stop failure"):
            service.execute("present_left", True, commissioning=True)
        self.assertFalse(arm_client.connected)

    def test_stale_state_stops_before_publication(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        arm_client.refresh_state = False
        clock.now = 1.0
        with self.assertRaisesRegex(RuntimeError, "stale"):
            service.execute("present_left", operator_confirmed=True)
        self.assertEqual(arm_client.commands, [])
        self.assertEqual(stops, [True])
        self.assertEqual(arm_client.wait_timeout, 5.0)

    def test_control_overrun_aborts_without_catch_up(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        service.sleeper = lambda seconds: clock.sleep(seconds + 0.1)
        with self.assertRaisesRegex(RuntimeError, "deadline missed"):
            service.execute("present_left", operator_confirmed=True)
        self.assertEqual(len(arm_client.commands), 1)
        self.assertEqual(stops, [True])

    def test_blocked_base_stop_does_not_delay_arm_release(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        unblock = Event()
        service.stop_base = unblock.wait
        service.cleanup_timeout_seconds = 0.02
        cancel = Event()
        cancel.set()
        try:
            with self.assertRaisesRegex(RuntimeError, "base stop timed out"):
                service.execute("present_left", True, cancel_event=cancel)
            self.assertTrue(arm_client.released)
            self.assertIs(self.motion_lease.owner, MotionOwner.PRESENTATION)
        finally:
            unblock.set()

    def test_cleanup_failure_preserves_original_error_and_lease(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        arm_client.state = replace(arm_client.state, mode_machine=999)
        service.stop_base = self._fail_stop
        with self.assertRaisesRegex(RuntimeError, "mode_machine"):
            service.execute("present_left", True)
        self.assertTrue(arm_client.released)
        self.assertIs(self.motion_lease.owner, MotionOwner.PRESENTATION)

    def test_release_failure_still_attempts_base_stop(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        arm_client.release = self._fail_stop
        cancel = Event()
        cancel.set()
        with self.assertRaisesRegex(RuntimeError, "arm release"):
            service.execute("present_left", True, cancel_event=cancel)
        self.assertEqual(stops, [True])
        self.assertIs(self.motion_lease.owner, MotionOwner.PRESENTATION)

    def _fail_stop(self) -> None:
        raise RuntimeError("injected stop failure")

    def test_playback_overrun_aborts_without_catch_up(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        service.sleeper = lambda seconds: clock.sleep(
            seconds + (0.1 if clock.now > 2.1 else 0.0)
        )
        with self.assertRaisesRegex(RuntimeError, "deadline missed"):
            service.execute("present_left", True)
        self.assertGreater(len(arm_client.commands), 101)
        self.assertLess(len(arm_client.commands), 120)
        self.assertEqual(stops, [True])

    def test_nonfinite_measured_position_is_rejected(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        positions = list(arm_client.state.positions)
        positions[15] = float("nan")
        arm_client.state = replace(arm_client.state, positions=tuple(positions))
        with self.assertRaisesRegex(RuntimeError, "Measured position"):
            service.execute("present_left", True)
        self.assertEqual(arm_client.commands, [])

    def test_mid_transition_cancellation_prevents_next_command(self) -> None:
        service, arm_client, clock, stops = self._live_service()
        cancel = Event()
        service.sleeper = lambda seconds: (clock.sleep(seconds), cancel.set())
        execution = service.execute("present_left", True, cancel_event=cancel)
        self.assertTrue(execution.cancelled)
        self.assertEqual(len(arm_client.commands), 1)
        self.assertEqual(stops, [True])

    def _live_service(
        self,
    ) -> tuple[ActionService, FakeArmClient, FakeClock, list[bool]]:
        loader, arm_client = self._verified_loader_and_client()
        clock = FakeClock()
        arm_client.clock = clock
        stops: list[bool] = []
        service = ActionService(
            loader, ExecutionPolicy(ExecutionMode.LIVE), self.motion_lease,
            arm_client=arm_client, clock=clock, sleeper=clock.sleep,
            base_is_stationary=lambda: True, stop_base=lambda: stops.append(True),
        )
        return service, arm_client, clock, stops

    def test_cancellation_stops_base_releases_arms_and_lease(self) -> None:
        verified_loader, arm_client = self._verified_loader_and_client()
        base_stop_calls: list[bool] = []
        cancel_event = Event()
        cancel_event.set()
        service = ActionService(
            loader=verified_loader,
            execution_policy=ExecutionPolicy(ExecutionMode.LIVE),
            motion_lease=self.motion_lease,
            arm_client=arm_client,
            base_is_stationary=lambda: True,
            stop_base=lambda: base_stop_calls.append(True),
            sleeper=lambda _: None,
        )

        execution = service.execute(
            "present_left",
            operator_confirmed=True,
            cancel_event=cancel_event,
        )

        self.assertTrue(execution.cancelled)
        self.assertEqual(base_stop_calls, [True])
        self.assertTrue(arm_client.released)
        self.assertEqual(arm_client.commands, [])
        self.assertIs(self.motion_lease.owner, MotionOwner.IDLE)

    def _verified_loader_and_client(
        self,
    ) -> tuple[ActionTrajectoryLoader, FakeArmClient]:
        verified_contract = replace(
            self.loader.contract,
            hardware_verified=True,
        )
        verified_loader = ActionTrajectoryLoader(
            self.loader.trajectory_directory,
            verified_contract,
            self.loader.safety_limits,
        )
        trajectory = verified_loader.load("present_left")
        positions = [0.0] * 29
        for offset, dds_index in enumerate(verified_contract.arm_indices):
            positions[dds_index] = float(trajectory.joint_positions[0, offset])
        state = G1ArmState(
            received_at=0.0,
            mode_pr=0,
            mode_machine=verified_contract.mode_machine,
            positions=tuple(positions),
            temperatures=(25,) * 29,
            motor_faults=(0,) * 29,
        )
        arm_client = FakeArmClient(state)
        return verified_loader, arm_client


if __name__ == "__main__":
    unittest.main()
