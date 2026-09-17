from __future__ import annotations

import unittest
from pathlib import Path

from component.action.action_trajectory import (
    ActionSafetyLimits,
    ActionTrajectoryLoader,
    G1ArmContract,
)


class ActionTrajectoryLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.contract = G1ArmContract.load(
            project_root / "asset/g1_arm_contract.json"
        )
        self.limits = ActionSafetyLimits.load(
            project_root / "config/action_safety.json"
        )
        self.loader = ActionTrajectoryLoader(
            project_root / "data/actions/trajectories",
            self.contract,
            self.limits,
        )

    def test_recorder_npz_is_normalized_to_exact_arm_allowlist(self) -> None:
        trajectory = self.loader.load("present_left")

        self.assertEqual(trajectory.action_name, "present_left")
        self.assertEqual(trajectory.joint_names, self.contract.arm_joint_names)
        self.assertEqual(trajectory.joint_positions.shape, (101, 14))
        self.assertEqual(trajectory.duration_seconds, 4.0)
        self.assertFalse(trajectory.joint_positions.flags.writeable)
        self.assertNotIn("waist_yaw_joint", trajectory.joint_names)
        self.assertLessEqual(
            trajectory.metrics.max_velocity,
            self.limits.max_velocity,
        )
        self.assertLessEqual(
            trajectory.metrics.max_acceleration,
            self.limits.max_acceleration,
        )

    def test_more_aggressive_recording_is_rejected_by_safety_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "velocity .* exceeds"):
            self.loader.load("concierge_speak_v1")

    def test_action_name_cannot_escape_data_directory(self) -> None:
        with self.assertRaisesRegex(ValueError, "Invalid action name"):
            self.loader.load("../present_left")

    def test_hardware_contract_starts_unverified(self) -> None:
        self.assertFalse(self.contract.hardware_verified)
        self.assertEqual(self.contract.arm_indices, tuple(range(15, 29)))


if __name__ == "__main__":
    unittest.main()
