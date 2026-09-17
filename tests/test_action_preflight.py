from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from component.action.action_preflight import ActionPreflightService
from component.action.action_trajectory import ActionSafetyLimits, G1ArmContract
from util.g1_helper.g1_action_helper.action_state_helper import (
    G1ActionStateObservation,
    G1LowStateObservation,
    G1MotionStateObservation,
)


class FakeActionStateReader:
    def __init__(self, observation: G1ActionStateObservation) -> None:
        self.observation = observation
        self.network_interface = "eth0"
        self.low_state_topic = "rt/lowstate"
        self.motion_state_topic = "rt/sportmodestate"
        self.motion_state_schema = "unitree_go.msg.dds_.SportModeState_"
        self.connect_count = 0
        self.wait_timeouts: list[float] = []

    def connect(self) -> None:
        self.connect_count += 1

    def wait_for_state(self, timeout: float) -> G1ActionStateObservation:
        self.wait_timeouts.append(timeout)
        return self.observation


class ActionPreflightServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.contract = G1ArmContract.load(
            project_root / "asset/g1_arm_contract.json"
        )
        self.limits = ActionSafetyLimits.load(
            project_root / "config/action_safety.json"
        )
        self.observed_at = 100.0

    def test_passing_read_only_report_is_saved_atomically(self) -> None:
        reader = FakeActionStateReader(self._healthy_observation())
        service = self._service(reader)

        report = service.inspect(
            self.contract.robot_model_id,
            "g1-firmware-observed-1",
        )

        self.assertTrue(report.passed)
        self.assertTrue(report.read_only)
        self.assertFalse(report.contract_hardware_verified)
        self.assertEqual(report.identity_source, "operator_input")
        self.assertEqual(
            report.max_stationary_linear_speed,
            self.limits.max_stationary_linear_speed,
        )
        self.assertEqual(len(report.arm_motors), 14)
        self.assertEqual(reader.connect_count, 1)
        self.assertEqual(
            reader.wait_timeouts,
            [self.limits.state_timeout_seconds],
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "preflight.json"
            saved_path = service.save(report, report_path)
            report_payload = json.loads(saved_path.read_text(encoding="utf-8"))
            temporary_files = list(saved_path.parent.glob(".*.tmp"))

        self.assertEqual(report_payload["schema_version"], 1)
        self.assertEqual(report_payload["recorded_at_utc"], "2026-09-17T09:00:00Z")
        self.assertEqual(report_payload["failures"], [])
        self.assertEqual(temporary_files, [])

    def test_all_safety_failures_are_recorded_without_a_command(self) -> None:
        healthy = self._healthy_observation()
        positions = list(healthy.low_state.positions[:20])
        positions[15] = 99.0
        temperatures = list(healthy.low_state.temperatures[:20])
        temperatures[16] = self.limits.max_motor_temperature + 1
        motor_faults = list(healthy.low_state.motor_faults[:20])
        motor_faults[17] = 9
        unsafe_low_state = replace(
            healthy.low_state,
            received_at=self.observed_at - 1.0,
            mode_machine=self.contract.mode_machine + 1,
            positions=tuple(positions),
            temperatures=tuple(temperatures),
            motor_faults=tuple(motor_faults),
        )
        unsafe_motion_state = replace(
            healthy.motion_state,
            received_at=self.observed_at - 1.0,
            error_code=42,
            linear_velocity=(0.02, 0.0, 0.0),
            yaw_speed=0.02,
        )
        reader = FakeActionStateReader(
            G1ActionStateObservation(unsafe_low_state, unsafe_motion_state)
        )
        service = self._service(reader)

        report = service.inspect("wrong-model")
        failure_text = "\n".join(report.failures)

        self.assertFalse(report.passed)
        self.assertIn("model does not match", failure_text)
        self.assertIn("firmware version", failure_text)
        self.assertIn("mode_machine", failure_text)
        self.assertIn("low state is stale", failure_text)
        self.assertIn("motion state is stale", failure_text)
        self.assertIn("error code 42", failure_text)
        self.assertIn("fewer than 29", failure_text)
        self.assertIn("not all allowlisted", failure_text)
        self.assertIn("left_shoulder_pitch_joint position", failure_text)
        self.assertIn("left_shoulder_roll_joint temperature", failure_text)
        self.assertIn("left_shoulder_yaw_joint reports motor fault", failure_text)
        self.assertIn("linear velocity", failure_text)
        self.assertIn("yaw speed", failure_text)

    def test_observed_model_is_required_before_connecting(self) -> None:
        reader = FakeActionStateReader(self._healthy_observation())
        service = self._service(reader)

        with self.assertRaisesRegex(ValueError, "observed_model_id"):
            service.inspect("  ")

        self.assertEqual(reader.connect_count, 0)

    def _healthy_observation(self) -> G1ActionStateObservation:
        positions = [0.0] * 35
        low_state = G1LowStateObservation(
            received_at=self.observed_at,
            version=(1, 0),
            mode_pr=0,
            mode_machine=self.contract.mode_machine,
            tick=1000,
            positions=tuple(positions),
            temperatures=(25,) * 35,
            motor_faults=(0,) * 35,
        )
        motion_state = G1MotionStateObservation(
            received_at=self.observed_at,
            error_code=0,
            mode=0,
            linear_velocity=(0.0, 0.0, 0.0),
            yaw_speed=0.0,
        )
        observation = G1ActionStateObservation(low_state, motion_state)
        return observation

    def _service(
        self,
        reader: FakeActionStateReader,
    ) -> ActionPreflightService:
        service = ActionPreflightService(
            contract=self.contract,
            safety_limits=self.limits,
            state_reader=reader,
            clock=lambda: self.observed_at,
            utc_now=lambda: datetime(
                2026,
                9,
                17,
                9,
                0,
                tzinfo=timezone.utc,
            ),
        )
        return service


if __name__ == "__main__":
    unittest.main()
