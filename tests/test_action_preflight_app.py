from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app.action_preflight import ActionPreflightApplication


class ActionPreflightApplicationTests(unittest.TestCase):
    def test_default_mode_does_not_construct_a_dds_reader(self) -> None:
        application = ActionPreflightApplication()
        standard_output = io.StringIO()

        with (
            patch.object(sys, "argv", ["action-preflight"]),
            patch("app.action_preflight.G1ActionStateHelper") as reader_class,
            redirect_stdout(standard_output),
        ):
            application.run()

        reader_class.assert_not_called()
        self.assertIn("safe mode", standard_output.getvalue())

    def test_live_mode_requires_stationary_confirmation_before_dds(self) -> None:
        application = ActionPreflightApplication()

        with (
            patch.object(sys, "argv", ["action-preflight", "--live"]),
            patch("app.action_preflight.G1ActionStateHelper") as reader_class,
            self.assertRaisesRegex(SystemExit, "confirm-stationary"),
        ):
            application.run()

        reader_class.assert_not_called()

    def test_live_mode_requires_independent_identity_observations(self) -> None:
        application = ActionPreflightApplication()
        arguments = [
            "action-preflight",
            "--live",
            "--confirm-stationary",
            "--observed-model-id",
            "unitree_g1_29dof_rev_1_0_fake_hand",
        ]

        with (
            patch.object(sys, "argv", arguments),
            patch("app.action_preflight.G1ActionStateHelper") as reader_class,
            self.assertRaisesRegex(SystemExit, "observed-firmware-version"),
        ):
            application.run()

        reader_class.assert_not_called()


if __name__ == "__main__":
    unittest.main()
