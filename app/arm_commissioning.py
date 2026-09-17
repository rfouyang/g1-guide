from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

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
        execution = None
        try:
            print("Single present_left: 4x duration, return to initial arms, fade authority; Ctrl-C cancels")
            execution = service.execute(
                "present_left", operator_confirmed=True, commissioning=True,
                cancel_event=self.cancel,
            )
            print(execution)
        finally:
            execution_failed = sys.exc_info()[0] is not None
            execution_error = sys.exc_info()[1]
            signal.signal(signal.SIGINT, previous_int)
            signal.signal(signal.SIGTERM, previous_term)
            # Keep the actual rejecting snapshot before acquiring any new state.
            try:
                if guard.last_report is not None and not guard.last_report.passed:
                    preflight.save(
                        guard.last_report, report_directory / f"{stamp}_rejected.json"
                    )
                self.save_execution_evidence(
                    report_directory / f"{stamp}_execution.json", arm_client,
                    execution_error, completed=execution is not None and not execution.cancelled,
                )
            except Exception:
                logger.exception("Could not persist commissioning execution evidence")
                # Continue to acquire final robot state even if storage failed.
            # Preserve failed observations too; a publication is not a stop ACK.
            try:
                report = preflight.inspect(guard.model_id, guard.firmware)
                preflight.save(report, report_directory / f"{stamp}_after.json")
                print(
                    f"Final snapshot saved; generic preflight passed={report.passed}. "
                    "This is not commissioning or physical handoff acceptance."
                )
                if not report.passed:
                    raise RuntimeError("Final state failed preflight; operator recovery required")
            except Exception:
                logger.exception("Final state not established; operator recovery required")
                if not execution_failed:
                    raise

    def save_execution_evidence(
        self, path: Path, arm_client: G1ArmSdkHelper,
        error: BaseException | None, *, completed: bool,
    ) -> None:
        evidence = {
            "schema_version": 1,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "action_name": "present_left",
            "execution_completed": completed,
            "error_type": type(error).__name__ if error is not None else None,
            "error": str(error) if error is not None else None,
            "position_commands_published": arm_client.position_commands_published,
            "release_commands_published": arm_client.release_commands_published,
            "publication_is_physical_acknowledgement": False,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary_path, path)
        finally:
            temporary_path.unlink(missing_ok=True)
        logger.info(
            "Arm publication counts: positions={}, releases={}; evidence={}",
            arm_client.position_commands_published,
            arm_client.release_commands_published, path,
        )

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
