from __future__ import annotations

import unittest
from unittest.mock import patch

from app.arm_commissioning import ArmCommissioningApplication


class ArmCommissioningApplicationTests(unittest.TestCase):
    def test_default_run_never_constructs_dds(self) -> None:
        with patch("sys.argv", ["arm_commissioning"]), patch(
            "app.arm_commissioning.G1ActionStateHelper"
        ) as reader:
            ArmCommissioningApplication().run()
        reader.assert_not_called()

    def test_live_requires_confirmations_before_dds(self) -> None:
        with patch("sys.argv", ["arm_commissioning", "--live"]), patch(
            "app.arm_commissioning.G1ActionStateHelper"
        ) as reader:
            with self.assertRaises(SystemExit):
                ArmCommissioningApplication().run()
        reader.assert_not_called()


if __name__ == "__main__":
    unittest.main()
