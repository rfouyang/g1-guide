from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.arm_commissioning import ArmCommissioningApplication
from util.g1_helper.g1_action_helper.arm_sdk_helper import G1ArmSdkHelper


class ArmCommissioningApplicationTests(unittest.TestCase):
    def test_execution_evidence_records_failure_without_physical_ack_claim(self) -> None:
        helper = G1ArmSdkHelper("offline-demo")
        helper.position_commands_published = 2
        helper.release_commands_published = 1
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.json"
            ArmCommissioningApplication().save_execution_evidence(
                path, helper, RuntimeError("FSM 501/1"), completed=False
            )
            evidence = json.loads(path.read_text())
            self.assertEqual(evidence["schema_version"], 1)
            self.assertEqual(evidence["position_commands_published"], 2)
            self.assertEqual(evidence["release_commands_published"], 1)
            self.assertFalse(evidence["execution_completed"])
            self.assertFalse(evidence["publication_is_physical_acknowledgement"])
            self.assertEqual(evidence["error"], "FSM 501/1")
            self.assertEqual(list(Path(directory).iterdir()), [path])

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
