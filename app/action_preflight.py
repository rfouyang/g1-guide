from __future__ import annotations

import argparse
from pathlib import Path

from component.action.action_preflight import ActionPreflightService
from component.action.action_trajectory import ActionSafetyLimits, G1ArmContract
from util.g1_helper.g1_action_helper.action_state_helper import (
    G1ActionStateHelper,
)


class ActionPreflightApplication:
    """Run and persist a subscriber-only target-G1 action preflight."""

    def __init__(self) -> None:
        self.project_root = Path(__file__).resolve().parents[1]
        self.contract_path = self.project_root / "asset/g1_arm_contract.json"
        self.safety_path = self.project_root / "config/action_safety.json"
        self.output_root = self.project_root / "output/action_preflight"

    def run(self) -> None:
        arguments = self._parse_arguments()
        if not arguments.live:
            print("Action preflight: safe mode, no DDS connection")
            return
        if not arguments.confirm_stationary:
            raise SystemExit(
                "Live preflight requires --confirm-stationary; no DDS connection made"
            )
        if not arguments.observed_model_id:
            raise SystemExit(
                "Live preflight requires --observed-model-id from the target robot"
            )
        if not arguments.observed_firmware_version:
            raise SystemExit(
                "Live preflight requires --observed-firmware-version from the "
                "target robot"
            )

        contract = G1ArmContract.load(self.contract_path)
        safety_limits = ActionSafetyLimits.load(self.safety_path)
        state_reader = G1ActionStateHelper(
            network_interface=arguments.interface,
            state_timeout=safety_limits.state_timeout_seconds,
            fsm_state_topic=arguments.fsm_state_topic,
            motion_state_topic=arguments.motion_state_topic,
        )
        service = ActionPreflightService(
            contract=contract,
            safety_limits=safety_limits,
            state_reader=state_reader,
        )
        report = service.inspect(
            arguments.observed_model_id,
            arguments.observed_firmware_version,
        )
        report_path = arguments.output or self._default_report_path(
            report.recorded_at_utc
        )
        saved_path = service.save(report, report_path)
        print(
            f"Read-only action preflight {'passed' if report.passed else 'failed'}; "
            f"report: {saved_path}"
        )
        if not report.passed:
            raise SystemExit(2)

    def _default_report_path(self, recorded_at_utc: str) -> Path:
        file_timestamp = recorded_at_utc.replace("-", "").replace(":", "")
        report_path = self.output_root / f"action_preflight_{file_timestamp}.json"
        return report_path

    def _parse_arguments(self) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            description="Subscriber-only Unitree G1 action preflight"
        )
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--confirm-stationary", action="store_true")
        parser.add_argument(
            "--interface",
            help=(
                "DDS network interface; defaults to the interface on "
                "192.168.123.0/24"
            ),
        )
        parser.add_argument("--observed-model-id")
        parser.add_argument("--observed-firmware-version")
        parser.add_argument(
            "--fsm-state-topic",
            default=G1ActionStateHelper.FSM_STATE_TOPIC,
            help="read-only G1 locomotion FSM state topic",
        )
        parser.add_argument(
            "--motion-state-topic",
            default=G1ActionStateHelper.MOTION_STATE_TOPIC,
            help="read-only G1 odometry state topic used for base velocities",
        )
        parser.add_argument("--output", type=Path)
        parsed_arguments = parser.parse_args()
        return parsed_arguments


def demo_action_preflight() -> None:
    ActionPreflightApplication().run()


def main() -> None:
    demo_action_preflight()


if __name__ == "__main__":
    main()
