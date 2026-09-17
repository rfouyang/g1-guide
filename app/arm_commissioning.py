from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path
from threading import Event

from loguru import logger

from app.application import ApplicationFactory
from component.action.action_preflight import ActionPreflightService, CommissioningGuard
from component.action.action_service import ActionService
from component.action.execution_policy import ExecutionMode, ExecutionPolicy
from util.g1_helper.g1_action_helper.action_state_helper import G1ActionStateHelper
from util.g1_helper.g1_action_helper.arm_sdk_helper import G1ArmSdkHelper


class ArmCommissioningApplication:
    """One slow arm-only commissioning run; no locomotion command client."""

    def __init__(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.cancel = Event()

    def request_cancel(self, signum: int, frame: object) -> None:
        self.cancel.set()

    def run(self) -> None:
        arguments = self.parse_arguments()
        application = ApplicationFactory(self.root).create_dry_run()
        if not arguments.live:
            execution = application.action_service.execute("present_left")
            assert not execution.hardware_executed
            print("present_left validated; dry-run only, no DDS or motion")
            return
        if not (
            arguments.confirm_arm_motion
            and arguments.confirm_clear_workspace
            and arguments.confirm_standing
            and arguments.observed_model_id
            and arguments.observed_firmware_version
        ):
            raise SystemExit(
                "Live commissioning requires model/firmware and explicit arm-motion, "
                "clear-workspace/operator emergency-stop, and stable-standing confirmation"
            )
        loader = application.action_service.loader
        reader = G1ActionStateHelper(
            network_interface=arguments.interface,
            state_timeout=loader.safety_limits.state_timeout_seconds,
        )
        preflight = ActionPreflightService(loader.contract, loader.safety_limits, reader)
        guard = CommissioningGuard(
            preflight, arguments.observed_model_id, arguments.observed_firmware_version
        )
        guard.check()
        report_directory = self.root / "output/arm_commissioning"
        stamp = guard.last_report.recorded_at_utc.replace(":", "").replace("-", "")
        preflight.save(guard.last_report, report_directory / f"{stamp}_before.json")
        arm_client = G1ArmSdkHelper(
            network_interface=reader.network_interface,
            state_timeout=loader.safety_limits.state_timeout_seconds,
            expected_mode_machine=loader.contract.mode_machine,
        )
        service = ActionService(
            loader, ExecutionPolicy(ExecutionMode.LIVE), application.motion_lease,
            arm_client=arm_client, base_is_stationary=guard.check,
            live_guard=guard.check,
        )
        previous_int = signal.signal(signal.SIGINT, self.request_cancel)
        previous_term = signal.signal(signal.SIGTERM, self.request_cancel)
        try:
            print("Single present_left: 4x duration, return to initial arms, fade authority; Ctrl-C cancels")
            execution = service.execute(
                "present_left", operator_confirmed=True, commissioning=True,
                cancel_event=self.cancel,
            )
            print(execution)
        finally:
            execution_failed = sys.exc_info()[0] is not None
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
            # Preserve failed observations too; a publication is not a stop ACK.
            try:
                report = preflight.inspect(guard.model_id, guard.firmware)
                preflight.save(report, report_directory / f"{stamp}_after.json")
                print(f"Observed final state saved; preflight passed={report.passed}")
                if not report.passed:
                    raise RuntimeError("Final state failed preflight; operator recovery required")
            except Exception:
                logger.exception("Final state not established; operator recovery required")
                if not execution_failed:
                    raise

    def parse_arguments(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(description="Single G1 two-arm commissioning")
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--confirm-arm-motion", action="store_true")
        parser.add_argument("--confirm-clear-workspace", action="store_true")
        parser.add_argument("--confirm-standing", action="store_true")
        parser.add_argument("--interface", default="eth0")
        parser.add_argument("--observed-model-id")
        parser.add_argument("--observed-firmware-version")
        return parser.parse_args()


def demo_arm_commissioning() -> None:
    application = ApplicationFactory().create_dry_run()
    execution = application.action_service.execute("present_left")
    assert not execution.hardware_executed
    print("Arm commissioning demo: validated present_left, hardware disabled")


def main() -> None:
    ArmCommissioningApplication().run()


if __name__ == "__main__":
    main()
