from __future__ import annotations

import json
import math
import os
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from loguru import logger

from component.action.action_trajectory import ActionSafetyLimits, G1ArmContract
from util.g1_helper.g1_action_helper.action_state_helper import (
    G1ActionStateObservation,
    G1FsmStateObservation,
    G1LowStateObservation,
    G1MotionStateObservation,
)


class ActionStateReader(Protocol):
    """Subscriber-only boundary used by the action preflight workflow."""

    network_interface: str
    low_state_topic: str
    fsm_state_topic: str
    motion_state_topic: str
    fsm_state_schema: str
    motion_state_schema: str

    def connect(self) -> None: ...

    def wait_for_state(self, timeout: float) -> G1ActionStateObservation: ...


@dataclass(frozen=True)
class ArmMotorObservation:
    """Observed health and position for one allowlisted arm motor."""

    joint_name: str
    dds_index: int
    position: float
    temperature_celsius: int
    fault: int


@dataclass(frozen=True)
class ActionPreflightReport:
    """Persistable evidence from one subscriber-only action preflight."""

    schema_version: int
    recorded_at_utc: str
    read_only: bool
    network_interface: str
    low_state_topic: str
    fsm_state_topic: str
    motion_state_topic: str
    fsm_state_schema: str
    motion_state_schema: str
    identity_source: str
    expected_model_id: str
    observed_model_id: str
    observed_firmware_version: str | None
    contract_hardware_verified: bool
    expected_mode_machine: int
    low_state_version: tuple[int, int]
    low_state_tick: int
    mode_pr: int
    mode_machine: int
    fsm_id: int
    fsm_mode: int
    fsm_task_id: int
    fsm_task_time: float
    motion_mode: int
    motion_error_code: int
    motor_count: int
    low_state_age_seconds: float
    fsm_state_age_seconds: float
    motion_state_age_seconds: float
    base_linear_velocity: tuple[float, float, float]
    base_yaw_speed: float
    initial_state_wait_seconds: float
    max_state_age_seconds: float
    max_motor_temperature_celsius: int
    max_stationary_linear_speed: float
    max_stationary_yaw_speed: float
    arm_motors: tuple[ArmMotorObservation, ...]
    failures: tuple[str, ...]
    passed: bool

    def to_dict(self) -> dict[str, object]:
        report_payload = asdict(self)
        return report_payload


class ActionPreflightService:
    """Record action safety evidence without publishing a robot command."""

    SCHEMA_VERSION = 3
    DEFAULT_INITIAL_STATE_WAIT_SECONDS = 5.0
    SUPPORTED_ACTION_FSM_IDS = (500, 501, 801)
    SUPPORTED_FSM_801_MODES = (0, 3)

    def __init__(
        self,
        contract: G1ArmContract,
        safety_limits: ActionSafetyLimits,
        state_reader: ActionStateReader,
        **kwargs: object,
    ) -> None:
        self.contract = contract
        self.safety_limits = safety_limits
        self.state_reader = state_reader
        self.clock = kwargs.get("clock", time.monotonic)
        self.utc_now = kwargs.get(
            "utc_now",
            lambda: datetime.now(timezone.utc),
        )
        self.initial_state_wait_seconds = float(
            kwargs.get(
                "initial_state_wait_seconds",
                self.DEFAULT_INITIAL_STATE_WAIT_SECONDS,
            )
        )
        if not callable(self.clock) or not callable(self.utc_now):
            raise TypeError("clock and utc_now must be callable")
        if (
            not math.isfinite(self.initial_state_wait_seconds)
            or self.initial_state_wait_seconds <= 0.0
        ):
            raise ValueError(
                "initial_state_wait_seconds must be finite and positive"
            )

    def inspect(
        self,
        observed_model_id: str,
        observed_firmware_version: str | None = None,
    ) -> ActionPreflightReport:
        normalized_model_id = observed_model_id.strip()
        if not normalized_model_id:
            raise ValueError("observed_model_id cannot be empty")
        normalized_firmware = self._normalize_optional_text(
            observed_firmware_version
        )

        self.state_reader.connect()
        state = self.state_reader.wait_for_state(
            self.initial_state_wait_seconds
        )
        observed_at = float(self.clock())
        low_state_age = observed_at - state.low_state.received_at
        fsm_state_age = observed_at - state.fsm_state.received_at
        motion_state_age = observed_at - state.motion_state.received_at
        arm_motors = self._arm_motor_observations(state.low_state)
        failures = self._failures(
            normalized_model_id,
            normalized_firmware,
            state,
            low_state_age,
            fsm_state_age,
            motion_state_age,
            arm_motors,
        )
        report = ActionPreflightReport(
            schema_version=self.SCHEMA_VERSION,
            recorded_at_utc=self._utc_timestamp(),
            read_only=True,
            network_interface=self.state_reader.network_interface,
            low_state_topic=self.state_reader.low_state_topic,
            fsm_state_topic=self.state_reader.fsm_state_topic,
            motion_state_topic=self.state_reader.motion_state_topic,
            fsm_state_schema=self.state_reader.fsm_state_schema,
            motion_state_schema=self.state_reader.motion_state_schema,
            identity_source="operator_input",
            expected_model_id=self.contract.robot_model_id,
            observed_model_id=normalized_model_id,
            observed_firmware_version=normalized_firmware,
            contract_hardware_verified=self.contract.hardware_verified,
            expected_mode_machine=self.contract.mode_machine,
            low_state_version=state.low_state.version,
            low_state_tick=state.low_state.tick,
            mode_pr=state.low_state.mode_pr,
            mode_machine=state.low_state.mode_machine,
            fsm_id=state.fsm_state.fsm_id,
            fsm_mode=state.fsm_state.fsm_mode,
            fsm_task_id=state.fsm_state.task_id,
            fsm_task_time=state.fsm_state.task_time,
            motion_mode=state.motion_state.mode,
            motion_error_code=state.motion_state.error_code,
            motor_count=len(state.low_state.positions),
            low_state_age_seconds=low_state_age,
            fsm_state_age_seconds=fsm_state_age,
            motion_state_age_seconds=motion_state_age,
            base_linear_velocity=state.motion_state.linear_velocity,
            base_yaw_speed=state.motion_state.yaw_speed,
            initial_state_wait_seconds=self.initial_state_wait_seconds,
            max_state_age_seconds=self.safety_limits.state_timeout_seconds,
            max_motor_temperature_celsius=(
                self.safety_limits.max_motor_temperature
            ),
            max_stationary_linear_speed=(
                self.safety_limits.max_stationary_linear_speed
            ),
            max_stationary_yaw_speed=(
                self.safety_limits.max_stationary_yaw_speed
            ),
            arm_motors=arm_motors,
            failures=failures,
            passed=not failures,
        )
        return report

    def save(self, report: ActionPreflightReport, report_path: Path) -> Path:
        if report_path.suffix.lower() != ".json":
            raise ValueError("Action preflight report path must end with .json")
        resolved_path = report_path.resolve()
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = resolved_path.with_name(
            f".{resolved_path.name}.{uuid4().hex}.tmp"
        )
        serialized_report = json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        try:
            temporary_path.write_text(
                f"{serialized_report}\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, resolved_path)
        finally:
            temporary_path.unlink(missing_ok=True)
        logger.info("Saved read-only action preflight report {}", resolved_path)
        return resolved_path

    def _arm_motor_observations(
        self,
        low_state: G1LowStateObservation,
    ) -> tuple[ArmMotorObservation, ...]:
        observations = []
        field_count = min(
            len(low_state.positions),
            len(low_state.temperatures),
            len(low_state.motor_faults),
        )
        for joint in self.contract.arm_joints:
            if joint.dds_index >= field_count:
                continue
            observations.append(
                ArmMotorObservation(
                    joint_name=joint.name,
                    dds_index=joint.dds_index,
                    position=low_state.positions[joint.dds_index],
                    temperature_celsius=low_state.temperatures[joint.dds_index],
                    fault=low_state.motor_faults[joint.dds_index],
                )
            )
        return tuple(observations)

    def _failures(
        self,
        observed_model_id: str,
        observed_firmware_version: str | None,
        state: G1ActionStateObservation,
        low_state_age: float,
        fsm_state_age: float,
        motion_state_age: float,
        arm_motors: tuple[ArmMotorObservation, ...],
    ) -> tuple[str, ...]:
        failures = []
        if observed_model_id != self.contract.robot_model_id:
            failures.append("observed robot model does not match the arm contract")
        if observed_firmware_version is None:
            failures.append("firmware version was not independently observed")
        if state.low_state.mode_machine != self.contract.mode_machine:
            failures.append("mode_machine does not match the arm contract")
        self._append_freshness_failure(failures, low_state_age, "low state")
        self._append_freshness_failure(failures, fsm_state_age, "FSM state")
        self._append_freshness_failure(
            failures,
            motion_state_age,
            "motion state",
        )
        if state.fsm_state.fsm_id not in self.SUPPORTED_ACTION_FSM_IDS:
            failures.append(
                f"FSM id {state.fsm_state.fsm_id} does not support G1 arm actions"
            )
        if (
            state.fsm_state.fsm_id == 801
            and state.fsm_state.fsm_mode not in self.SUPPORTED_FSM_801_MODES
        ):
            failures.append(
                f"FSM 801 mode {state.fsm_state.fsm_mode} does not support "
                "G1 arm actions"
            )
        if state.motion_state.error_code != 0:
            failures.append(
                f"motion state reports error code {state.motion_state.error_code}"
            )

        low_state = state.low_state
        motor_field_lengths = {
            len(low_state.positions),
            len(low_state.temperatures),
            len(low_state.motor_faults),
        }
        required_motor_count = max(self.contract.arm_indices) + 1
        if len(motor_field_lengths) != 1:
            failures.append("low-state motor fields have inconsistent lengths")
        if min(motor_field_lengths) < required_motor_count:
            failures.append(
                f"low state has fewer than {required_motor_count} required motors"
            )
        if len(arm_motors) != len(self.contract.arm_joints):
            failures.append("not all allowlisted arm motors were observed")

        joint_contracts = {
            joint.dds_index: joint for joint in self.contract.arm_joints
        }
        for motor in arm_motors:
            joint = joint_contracts[motor.dds_index]
            if motor.fault != 0:
                failures.append(
                    f"{motor.joint_name} reports motor fault {motor.fault}"
                )
            if motor.temperature_celsius > self.safety_limits.max_motor_temperature:
                failures.append(
                    f"{motor.joint_name} temperature exceeds the safety limit"
                )
            if not joint.lower <= motor.position <= joint.upper:
                failures.append(
                    f"{motor.joint_name} position is outside the arm contract"
                )

        if any(
            abs(speed) > self.safety_limits.max_stationary_linear_speed
            for speed in state.motion_state.linear_velocity
        ):
            failures.append("observed base linear velocity is not stationary")
        if (
            abs(state.motion_state.yaw_speed)
            > self.safety_limits.max_stationary_yaw_speed
        ):
            failures.append("observed base yaw speed is not stationary")
        return tuple(failures)

    def _append_freshness_failure(
        self,
        failures: list[str],
        state_age: float,
        state_name: str,
    ) -> None:
        if (
            not math.isfinite(state_age)
            or state_age < 0.0
            or state_age > self.safety_limits.state_timeout_seconds
        ):
            failures.append(f"{state_name} is stale")

    def _utc_timestamp(self) -> str:
        timestamp = self.utc_now()
        if not isinstance(timestamp, datetime):
            raise TypeError("utc_now must return datetime")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("utc_now must return a timezone-aware datetime")
        utc_timestamp = timestamp.astimezone(timezone.utc).isoformat(
            timespec="seconds"
        )
        return utc_timestamp.replace("+00:00", "Z")

    @staticmethod
    def _normalize_optional_text(raw_text: str | None) -> str | None:
        if raw_text is None:
            return None
        normalized_text = raw_text.strip()
        return normalized_text or None


class CommissioningGuard:
    """Restrict first-run playback to the observed G1 configuration."""

    def __init__(
        self, preflight: ActionPreflightService, model_id: str, firmware: str
    ) -> None:
        self.preflight = preflight
        self.model_id = model_id
        self.firmware = firmware
        self.last_report: ActionPreflightReport | None = None

    def check(self) -> bool:
        if self.firmware != "1.5.4":
            raise RuntimeError("Commissioning is restricted to observed firmware 1.5.4")
        report = self.preflight.inspect(self.model_id, self.firmware)
        self.last_report = report
        if not report.passed:
            raise RuntimeError(
                "Arm commissioning preflight failed: " + "; ".join(report.failures)
            )
        if (report.fsm_id, report.fsm_mode, report.mode_pr) != (501, 0, 0):
            reason = (
                "Commissioning requires observed FSM 501/0 and mode_pr 0; "
                f"observed FSM {report.fsm_id}/{report.fsm_mode}, "
                f"mode_pr {report.mode_pr}, mode_machine {report.mode_machine}"
            )
            self.last_report = replace(
                report, passed=False, failures=report.failures + (reason,)
            )
            raise RuntimeError(reason)
        return True


class DemoActionStateReader:
    """Provide deterministic read-only state for the module demo."""

    def __init__(self, observation: G1ActionStateObservation) -> None:
        self.observation = observation
        self.network_interface = "offline-demo"
        self.low_state_topic = "offline/lowstate"
        self.fsm_state_topic = "offline/fsm_state"
        self.motion_state_topic = "offline/odommodestate"
        self.fsm_state_schema = "offline-demo"
        self.motion_state_schema = "offline-demo"

    def connect(self) -> None:
        return None

    def wait_for_state(self, timeout: float) -> G1ActionStateObservation:
        if timeout <= 0.0:
            raise ValueError("timeout must be positive")
        return self.observation


def demo_action_preflight() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contract = G1ArmContract.load(project_root / "asset/g1_arm_contract.json")
    limits = ActionSafetyLimits.load(project_root / "config/action_safety.json")
    observed_at = 10.0
    observation = G1ActionStateObservation(
        low_state=G1LowStateObservation(
            received_at=observed_at,
            version=(1, 0),
            mode_pr=0,
            mode_machine=contract.mode_machine,
            tick=100,
            positions=(0.0,) * 29,
            temperatures=(25,) * 29,
            motor_faults=(0,) * 29,
        ),
        fsm_state=G1FsmStateObservation(
            received_at=observed_at,
            fsm_id=501,
            fsm_mode=0,
            task_id=4,
            task_time=0.0,
        ),
        motion_state=G1MotionStateObservation(
            received_at=observed_at,
            error_code=0,
            mode=0,
            linear_velocity=(0.0, 0.0, 0.0),
            yaw_speed=0.0,
        ),
    )
    service = ActionPreflightService(
        contract,
        limits,
        DemoActionStateReader(observation),
        clock=lambda: observed_at,
        utc_now=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    report = service.inspect(contract.robot_model_id, "offline-demo")
    assert report.passed
    assert report.read_only
    print("Action preflight: offline read-only checks passed")


def main() -> None:
    demo_action_preflight()


if __name__ == "__main__":
    main()
