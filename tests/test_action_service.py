from __future__ import annotations

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

    def connect(self) -> None:
        self.connected = True

    def latest_state(self, **_: object) -> G1ArmState:
        return self.state

    def wait_for_state(self, _: float) -> G1ArmState:
        return self.state

    def publish_arm_positions(
        self,
        arm_positions: object,
        **_: object,
    ) -> None:
        self.commands.append(tuple(float(value) for value in arm_positions))

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
