from __future__ import annotations

import unittest

import numpy as np

from util.g1_helper.g1_action_helper.trajectory_helper import TrajectoryHelper


class TrajectoryHelperTests(unittest.TestCase):
    def test_interpolates_between_samples(self) -> None:
        helper = TrajectoryHelper()
        timestamps = np.asarray([0.0, 1.0], dtype=np.float64)
        positions = np.asarray([[0.0, 1.0], [2.0, -1.0]], dtype=np.float64)

        midpoint = helper.sample(timestamps, positions, 0.5)

        np.testing.assert_allclose(midpoint, [1.0, 0.0])

    def test_calculates_peak_velocity_and_acceleration(self) -> None:
        helper = TrajectoryHelper()
        timestamps = np.asarray([0.0, 1.0, 2.0], dtype=np.float64)
        positions = np.asarray([[0.0], [1.0], [3.0]], dtype=np.float64)

        metrics = helper.metrics(timestamps, positions)

        self.assertEqual(metrics.max_velocity, 2.0)
        self.assertEqual(metrics.max_acceleration, 1.0)

    def test_rejects_non_increasing_timestamps(self) -> None:
        with self.assertRaisesRegex(ValueError, "increase strictly"):
            TrajectoryHelper().metrics(
                np.asarray([0.0, 0.0]),
                np.zeros((2, 1)),
            )


if __name__ == "__main__":
    unittest.main()
