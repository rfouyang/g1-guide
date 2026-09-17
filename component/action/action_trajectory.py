from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from util.g1_helper.g1_action_helper.npz_helper import NpzHelper
from util.g1_helper.g1_action_helper.trajectory_helper import (
    TrajectoryHelper,
    TrajectoryMetrics,
)


@dataclass(frozen=True)
class ArmJointContract:
    """One allowlisted G1 arm joint and its physical position limits."""

    name: str
    dds_index: int
    lower: float
    upper: float


@dataclass(frozen=True)
class G1ArmContract:
    """Pinned robot model and immutable two-arm allowlist."""

    robot_model_id: str
    mode_machine: int
    hardware_verified: bool
    source_joint_names: tuple[str, ...]
    arm_joints: tuple[ArmJointContract, ...]

    @property
    def arm_joint_names(self) -> tuple[str, ...]:
        joint_names = tuple(joint.name for joint in self.arm_joints)
        return joint_names

    @property
    def arm_indices(self) -> tuple[int, ...]:
        joint_indices = tuple(joint.dds_index for joint in self.arm_joints)
        return joint_indices

    @classmethod
    def load(cls, contract_path: Path) -> G1ArmContract:
        payload = cls._read_json(contract_path)
        if payload.get("schema_version") != 1:
            raise ValueError("Unsupported G1 arm contract schema")
        raw_joints = payload.get("arm_joints")
        if not isinstance(raw_joints, list):
            raise ValueError("G1 arm contract must define arm_joints")
        hardware_verified = payload.get("hardware_verified")
        if not isinstance(hardware_verified, bool):
            raise ValueError("G1 arm contract hardware_verified must be boolean")
        try:
            arm_joints = tuple(
                ArmJointContract(
                    name=str(raw_joint["name"]),
                    dds_index=int(raw_joint["dds_index"]),
                    lower=float(raw_joint["lower"]),
                    upper=float(raw_joint["upper"]),
                )
                for raw_joint in raw_joints
            )
            source_joint_names = tuple(
                str(name) for name in payload["source_joint_names"]
            )
            contract = cls(
                robot_model_id=str(payload["robot_model_id"]),
                mode_machine=int(payload["mode_machine"]),
                hardware_verified=hardware_verified,
                source_joint_names=source_joint_names,
                arm_joints=arm_joints,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid G1 arm contract: {error}") from error
        contract._validate()
        return contract

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read G1 arm contract: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("G1 arm contract must be a JSON object")
        return payload

    def _validate(self) -> None:
        if not self.robot_model_id:
            raise ValueError("G1 arm contract robot_model_id cannot be empty")
        if len(self.source_joint_names) != 17:
            raise ValueError("Recorder source contract must contain 17 joints")
        expected_waist_joints = (
            "waist_yaw_joint",
            "waist_roll_joint",
            "waist_pitch_joint",
        )
        if self.source_joint_names[:3] != expected_waist_joints:
            raise ValueError("Recorder source contract must begin with waist joints")
        if len(self.arm_joints) != 14:
            raise ValueError("G1 arm contract must contain exactly 14 joints")
        if self.arm_indices != tuple(range(15, 29)):
            raise ValueError("G1 arm contract DDS indices must be 15 through 28")
        if len(set(self.arm_joint_names)) != 14:
            raise ValueError("G1 arm contract contains duplicate joint names")
        if self.source_joint_names[3:] != self.arm_joint_names:
            raise ValueError("Recorder source and arm joint orders do not match")
        if any(joint.lower >= joint.upper for joint in self.arm_joints):
            raise ValueError("G1 arm contract contains invalid joint limits")


@dataclass(frozen=True)
class ActionSafetyLimits:
    """Conservative limits applied before a trajectory reaches the SDK."""

    control_frequency_hz: float
    state_timeout_seconds: float
    transition_seconds: float
    arm_kp: float
    arm_kd: float
    max_velocity: float
    max_acceleration: float
    max_tracking_error: float
    max_motor_temperature: int

    @classmethod
    def load(cls, safety_path: Path) -> ActionSafetyLimits:
        try:
            payload = json.loads(safety_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Could not read action safety configuration: {error}") from error
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("Unsupported action safety configuration schema")
        try:
            limits = cls(
                control_frequency_hz=float(payload["control_frequency_hz"]),
                state_timeout_seconds=float(payload["state_timeout_seconds"]),
                transition_seconds=float(payload["transition_seconds"]),
                arm_kp=float(payload["arm_kp"]),
                arm_kd=float(payload["arm_kd"]),
                max_velocity=float(payload["max_velocity_radians_per_second"]),
                max_acceleration=float(
                    payload["max_acceleration_radians_per_second_squared"]
                ),
                max_tracking_error=float(payload["max_tracking_error_radians"]),
                max_motor_temperature=int(
                    payload["max_motor_temperature_celsius"]
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid action safety configuration: {error}") from error
        numeric_limits = (
            limits.control_frequency_hz,
            limits.state_timeout_seconds,
            limits.transition_seconds,
            limits.arm_kp,
            limits.max_velocity,
            limits.max_acceleration,
            limits.max_tracking_error,
        )
        if not all(np.isfinite(value) and value > 0.0 for value in numeric_limits):
            raise ValueError("Action safety limits must be finite and positive")
        if (
            not np.isfinite(limits.arm_kd)
            or limits.arm_kd < 0.0
            or limits.max_motor_temperature <= 0
        ):
            raise ValueError("Action damping and temperature limits are invalid")
        return limits


@dataclass(frozen=True)
class ActionTrajectory:
    """A validated trajectory containing only the two allowlisted arms."""

    action_name: str
    robot_model_id: str
    frames_per_second: float
    joint_names: tuple[str, ...]
    timestamps: NDArray[np.float64]
    joint_positions: NDArray[np.float64]
    keyframe_sample_indices: tuple[int, ...]
    source_pose_names: tuple[str, ...]
    keyframe_hold_seconds: tuple[float, ...]
    metrics: TrajectoryMetrics

    @property
    def sample_count(self) -> int:
        return len(self.timestamps)

    @property
    def duration_seconds(self) -> float:
        return float(self.timestamps[-1])


class ActionTrajectoryLoader:
    """Load recorder NPZ files and normalize them to the 14-arm contract."""

    REQUIRED_ARRAYS = {
        "schema_version",
        "action_name",
        "robot_model_id",
        "fps",
        "joint_names",
        "timestamps",
        "joint_positions",
        "keyframe_sample_indices",
        "source_pose_names",
        "keyframe_hold_seconds",
        "max_tracking_error",
    }
    ACTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

    def __init__(
        self,
        trajectory_directory: Path,
        contract: G1ArmContract,
        safety_limits: ActionSafetyLimits,
        **kwargs: object,
    ) -> None:
        self.trajectory_directory = trajectory_directory.resolve()
        self.contract = contract
        self.safety_limits = safety_limits
        self.npz_helper = kwargs.get("npz_helper", NpzHelper())
        self.trajectory_helper = kwargs.get(
            "trajectory_helper",
            TrajectoryHelper(),
        )

    def load(self, action_name: str) -> ActionTrajectory:
        if not self.ACTION_NAME_PATTERN.fullmatch(action_name):
            raise ValueError(f"Invalid action name: {action_name!r}")
        archive_path = self.trajectory_directory / f"{action_name}.npz"
        arrays = self.npz_helper.read(archive_path)
        if set(arrays) != self.REQUIRED_ARRAYS:
            missing = sorted(self.REQUIRED_ARRAYS - set(arrays))
            unknown = sorted(set(arrays) - self.REQUIRED_ARRAYS)
            raise ValueError(
                f"Invalid action archive arrays: missing={missing}, unknown={unknown}"
            )
        return self._normalize(action_name, arrays)

    def _normalize(
        self,
        expected_name: str,
        arrays: dict[str, NDArray[np.generic]],
    ) -> ActionTrajectory:
        schema_version = self._scalar_int(arrays["schema_version"], "schema_version")
        if schema_version != 2:
            raise ValueError(f"Unsupported action archive schema: {schema_version}")
        action_name = self._scalar_string(arrays["action_name"], "action_name")
        if action_name != expected_name:
            raise ValueError("Action archive name does not match its file name")
        model_id = self._scalar_string(arrays["robot_model_id"], "robot_model_id")
        if model_id != self.contract.robot_model_id:
            raise ValueError("Action archive targets a different G1 model")

        frames_per_second = self._scalar_float(arrays["fps"], "fps")
        if frames_per_second <= 0.0:
            raise ValueError("Action frames per second must be positive")
        source_joint_names = self._string_tuple(arrays["joint_names"], "joint_names")
        if source_joint_names != self.contract.source_joint_names:
            raise ValueError("Action source joint order does not match the G1 contract")

        if not np.issubdtype(arrays["timestamps"].dtype, np.number):
            raise ValueError("Action timestamps must use a numeric dtype")
        if not np.issubdtype(arrays["joint_positions"].dtype, np.number):
            raise ValueError("Action joint positions must use a numeric dtype")
        timestamps = np.asarray(arrays["timestamps"], dtype=np.float64)
        source_positions = np.asarray(arrays["joint_positions"], dtype=np.float64)
        self.trajectory_helper.validate(timestamps, source_positions)
        if source_positions.shape[1] != len(source_joint_names):
            raise ValueError("Action position columns do not match joint names")
        if not np.isclose(timestamps[0], 0.0):
            raise ValueError("Action timestamps must start at zero")
        expected_interval = 1.0 / frames_per_second
        if len(timestamps) > 1 and not np.allclose(
            np.diff(timestamps),
            expected_interval,
            rtol=1e-6,
            atol=1e-9,
        ):
            raise ValueError("Action timestamps do not match its frame rate")

        arm_positions = source_positions[:, 3:].copy()
        self._validate_position_limits(arm_positions)
        metrics = self.trajectory_helper.metrics(timestamps, arm_positions)
        if metrics.max_velocity > self.safety_limits.max_velocity:
            raise ValueError(
                f"Action velocity {metrics.max_velocity:.3f} exceeds "
                f"{self.safety_limits.max_velocity:.3f} rad/s"
            )
        if metrics.max_acceleration > self.safety_limits.max_acceleration:
            raise ValueError(
                f"Action acceleration {metrics.max_acceleration:.3f} exceeds "
                f"{self.safety_limits.max_acceleration:.3f} rad/s^2"
            )
        archive_tracking_error = self._scalar_float(
            arrays["max_tracking_error"],
            "max_tracking_error",
        )
        if archive_tracking_error < 0.0 or (
            archive_tracking_error > self.safety_limits.max_tracking_error
        ):
            raise ValueError("Action archive tracking error exceeds the safety limit")

        keyframe_indices = self._integer_tuple(
            arrays["keyframe_sample_indices"],
            "keyframe_sample_indices",
        )
        source_pose_names = self._string_tuple(
            arrays["source_pose_names"],
            "source_pose_names",
        )
        hold_seconds = self._float_tuple(
            arrays["keyframe_hold_seconds"],
            "keyframe_hold_seconds",
        )
        self._validate_keyframes(
            keyframe_indices,
            source_pose_names,
            hold_seconds,
            len(timestamps),
        )

        timestamps.setflags(write=False)
        arm_positions.setflags(write=False)
        trajectory = ActionTrajectory(
            action_name=action_name,
            robot_model_id=model_id,
            frames_per_second=frames_per_second,
            joint_names=self.contract.arm_joint_names,
            timestamps=timestamps,
            joint_positions=arm_positions,
            keyframe_sample_indices=keyframe_indices,
            source_pose_names=source_pose_names,
            keyframe_hold_seconds=hold_seconds,
            metrics=metrics,
        )
        return trajectory

    def _validate_position_limits(
        self,
        arm_positions: NDArray[np.float64],
    ) -> None:
        for column, joint in enumerate(self.contract.arm_joints):
            positions = arm_positions[:, column]
            if np.any(positions < joint.lower) or np.any(positions > joint.upper):
                raise ValueError(f"Action exceeds position limits for {joint.name}")

    def _validate_keyframes(
        self,
        indices: tuple[int, ...],
        pose_names: tuple[str, ...],
        hold_seconds: tuple[float, ...],
        sample_count: int,
    ) -> None:
        if not indices or not (
            len(indices) == len(pose_names) == len(hold_seconds)
        ):
            raise ValueError("Action keyframe metadata must align")
        if indices[0] != 0 or indices[-1] != sample_count - 1:
            raise ValueError("Action keyframes must include both trajectory endpoints")
        if any(first >= second for first, second in zip(indices, indices[1:])):
            raise ValueError("Action keyframe indices must increase strictly")
        if any(not name for name in pose_names):
            raise ValueError("Action source pose names cannot be empty")
        if any(not np.isfinite(seconds) or seconds < 0.0 for seconds in hold_seconds):
            raise ValueError("Action keyframe hold durations are invalid")

    def _scalar_int(self, array: NDArray[np.generic], name: str) -> int:
        if array.ndim != 0 or not np.issubdtype(array.dtype, np.integer):
            raise ValueError(f"Action array {name} must be an integer scalar")
        scalar_value = int(array.item())
        return scalar_value

    def _scalar_float(self, array: NDArray[np.generic], name: str) -> float:
        if array.ndim != 0 or not np.issubdtype(array.dtype, np.number):
            raise ValueError(f"Action array {name} must be a numeric scalar")
        scalar_value = float(array.item())
        if not np.isfinite(scalar_value):
            raise ValueError(f"Action array {name} must be finite")
        return scalar_value

    def _scalar_string(self, array: NDArray[np.generic], name: str) -> str:
        if array.ndim != 0 or array.dtype.kind not in ("U", "S"):
            raise ValueError(f"Action array {name} must be a string scalar")
        scalar_value = str(array.item())
        if not scalar_value:
            raise ValueError(f"Action array {name} cannot be empty")
        return scalar_value

    def _integer_tuple(
        self,
        array: NDArray[np.generic],
        name: str,
    ) -> tuple[int, ...]:
        if array.ndim != 1 or not np.issubdtype(array.dtype, np.integer):
            raise ValueError(f"Action array {name} must be a one-dimensional integer array")
        integer_values = tuple(int(value) for value in array)
        return integer_values

    def _float_tuple(
        self,
        array: NDArray[np.generic],
        name: str,
    ) -> tuple[float, ...]:
        if array.ndim != 1 or not np.issubdtype(array.dtype, np.number):
            raise ValueError(f"Action array {name} must be a one-dimensional numeric array")
        float_values = tuple(float(value) for value in array)
        return float_values

    def _string_tuple(
        self,
        array: NDArray[np.generic],
        name: str,
    ) -> tuple[str, ...]:
        if array.ndim != 1 or array.dtype.kind not in ("U", "S"):
            raise ValueError(f"Action array {name} must be a one-dimensional string array")
        string_values = tuple(str(value) for value in array)
        return string_values


def demo_action_trajectory() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contract = G1ArmContract.load(project_root / "asset/g1_arm_contract.json")
    limits = ActionSafetyLimits.load(project_root / "config/action_safety.json")
    loader = ActionTrajectoryLoader(
        project_root / "data/actions/trajectories",
        contract,
        limits,
    )
    trajectory = loader.load("present_left")
    assert trajectory.joint_positions.shape == (101, 14)
    print(
        f"Action trajectory: {trajectory.action_name}, "
        f"{trajectory.sample_count} samples, arms only"
    )


def main() -> None:
    demo_action_trajectory()


if __name__ == "__main__":
    main()
