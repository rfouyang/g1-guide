from __future__ import annotations

import unittest

from component.action.execution_policy import ExecutionMode, ExecutionPolicy


class ExecutionPolicyTests(unittest.TestCase):
    def test_dry_run_disables_hardware(self) -> None:
        policy = ExecutionPolicy()

        authorization = policy.authorize(operator_confirmed=False)

        self.assertEqual(authorization.mode, ExecutionMode.DRY_RUN)
        self.assertFalse(authorization.hardware_enabled)

    def test_live_mode_requires_operator_confirmation(self) -> None:
        policy = ExecutionPolicy(mode=ExecutionMode.LIVE)

        with self.assertRaisesRegex(PermissionError, "operator confirmation"):
            policy.authorize(operator_confirmed=False)

    def test_confirmed_live_mode_enables_hardware(self) -> None:
        policy = ExecutionPolicy(mode=ExecutionMode.LIVE)

        authorization = policy.authorize(operator_confirmed=True)

        self.assertTrue(authorization.hardware_enabled)


if __name__ == "__main__":
    unittest.main()
