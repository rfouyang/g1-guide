from __future__ import annotations

import unittest

from app.application import ApplicationFactory
from component.action.execution_policy import ExecutionMode
from component.action.motion_lease import MotionOwner


class ApplicationTests(unittest.TestCase):
    def test_factory_creates_safe_default_application(self) -> None:
        application = ApplicationFactory().create_dry_run()

        application_status = application.status()

        self.assertEqual(application_status.mode, ExecutionMode.DRY_RUN)
        self.assertFalse(application_status.hardware_enabled)
        self.assertEqual(application_status.motion_owner, MotionOwner.IDLE)
        execution = application.action_service.execute("present_left")
        self.assertFalse(execution.hardware_executed)


if __name__ == "__main__":
    unittest.main()
