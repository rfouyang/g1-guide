from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True)
class TrajectoryMetrics:
    """Peak numeric motion rates in a sampled trajectory."""

    max_velocity: float
    max_acceleration: float


class TrajectoryHelper:
    """Interpolate trajectories and calculate their peak motion rates."""

    def sample(
        self,
        timestamps: NDArray[np.float64],
        joint_positions: NDArray[np.float64],
        elapsed_seconds: float,
    ) -> NDArray[np.float64]:
        self.validate(timestamps, joint_positions)
        if not np.isfinite(elapsed_seconds):
            raise ValueError("Elapsed time must be finite")
        if elapsed_seconds <= timestamps[0]:
            return joint_positions[0].copy()
        if elapsed_seconds >= timestamps[-1]:
            return joint_positions[-1].copy()

        upper_index = int(np.searchsorted(timestamps, elapsed_seconds, side="right"))
        lower_index = upper_index - 1
        interval = timestamps[upper_index] - timestamps[lower_index]
        ratio = (elapsed_seconds - timestamps[lower_index]) / interval
        interpolated_positions = (
            joint_positions[lower_index] * (1.0 - ratio)
            + joint_positions[upper_index] * ratio
        )
        return interpolated_positions

    def metrics(
        self,
        timestamps: NDArray[np.float64],
        joint_positions: NDArray[np.float64],
    ) -> TrajectoryMetrics:
        self.validate(timestamps, joint_positions)
        if len(timestamps) < 2:
            return TrajectoryMetrics(max_velocity=0.0, max_acceleration=0.0)

        intervals = np.diff(timestamps)
        velocities = np.diff(joint_positions, axis=0) / intervals[:, None]
        max_velocity = float(np.max(np.abs(velocities)))
        if len(velocities) < 2:
            max_acceleration = 0.0
        else:
            velocity_intervals = (intervals[:-1] + intervals[1:]) / 2.0
            accelerations = np.diff(velocities, axis=0) / velocity_intervals[:, None]
            max_acceleration = float(np.max(np.abs(accelerations)))
        trajectory_metrics = TrajectoryMetrics(
            max_velocity=max_velocity,
            max_acceleration=max_acceleration,
        )
        return trajectory_metrics

    def validate(
        self,
        timestamps: NDArray[np.float64],
        joint_positions: NDArray[np.float64],
    ) -> None:
        if timestamps.ndim != 1 or joint_positions.ndim != 2:
            raise ValueError("Trajectory timestamps and positions have invalid dimensions")
        if len(timestamps) == 0 or len(timestamps) != len(joint_positions):
            raise ValueError("Trajectory timestamps and positions must align")
        if not np.all(np.isfinite(timestamps)) or not np.all(
            np.isfinite(joint_positions)
        ):
            raise ValueError("Trajectory values must be finite")
        if len(timestamps) > 1 and not np.all(np.diff(timestamps) > 0.0):
            raise ValueError("Trajectory timestamps must increase strictly")


def demo_trajectory_helper() -> None:
    helper = TrajectoryHelper()
    timestamps = np.asarray([0.0, 1.0], dtype=np.float64)
    positions = np.asarray([[0.0, 0.0], [1.0, -1.0]], dtype=np.float64)
    midpoint = helper.sample(timestamps, positions, 0.5)
    assert np.allclose(midpoint, [0.5, -0.5])
    print("Trajectory helper: interpolation verified")


def main() -> None:
    demo_trajectory_helper()


if __name__ == "__main__":
    main()
