from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from loguru import logger

from util.g1_helper.g1_network_helper import G1NetworkHelper


@dataclass(frozen=True)
class G1ArmState:
    """Validated state needed by the two-arm command boundary."""

    received_at: float
    mode_pr: int
    mode_machine: int
    positions: tuple[float, ...]
    temperatures: tuple[int, ...]
    motor_faults: tuple[int, ...]


@dataclass(frozen=True)
class G1ArmSdkBindings:
    """Injectable constructors for the Unitree DDS boundary."""

    channel_initializer: Callable[..., object]
    publisher_factory: Callable[..., Any]
    subscriber_factory: Callable[..., Any]
    command_factory: Callable[[], Any]
    low_command_type: type[Any]
    low_state_type: type[Any]
    crc_factory: Callable[[], Any]


class G1ArmSdkHelper:
    """Publish commands only to the 14 G1 arm motors on ``rt/arm_sdk``."""

    ARM_INDICES = tuple(range(15, 29))
    ROBOT_MOTOR_COUNT = 29
    AUTHORITY_INDEX = 29
    COMMAND_TOPIC = "rt/arm_sdk"
    STATE_TOPIC = "rt/lowstate"

    def __init__(
        self,
        network_interface: str | None = None,
        **kwargs: object,
    ) -> None:
        if network_interface is None:
            network_interface = G1NetworkHelper.detect()
        self.network_interface = network_interface.strip()
        self.expected_mode_machine = int(kwargs.get("expected_mode_machine", 5))
        self.state_timeout = float(kwargs.get("state_timeout", 0.2))
        self.clock = kwargs.get("clock", time.monotonic)
        self._bindings = kwargs.get("bindings")
        self._publisher: Any | None = None
        self._subscriber: Any | None = None
        self._crc: Any | None = None
        self._state: G1ArmState | None = None
        self._state_lock = threading.Lock()
        self._state_ready = threading.Event()

        if not self.network_interface:
            raise ValueError("network_interface cannot be empty")
        if not math.isfinite(self.state_timeout) or self.state_timeout <= 0.0:
            raise ValueError("state_timeout must be positive")
        if not callable(self.clock):
            raise TypeError("clock must be callable")
        if self._bindings is not None and not isinstance(
            self._bindings,
            G1ArmSdkBindings,
        ):
            raise TypeError("bindings must be G1ArmSdkBindings")

    @property
    def connected(self) -> bool:
        return self._publisher is not None and self._subscriber is not None

    def connect(self) -> None:
        if self.connected:
            return
        bindings = self._bindings or self._resolve_sdk()
        bindings.channel_initializer(0, self.network_interface)

        publisher = bindings.publisher_factory(
            self.COMMAND_TOPIC,
            bindings.low_command_type,
        )
        subscriber = bindings.subscriber_factory(
            self.STATE_TOPIC,
            bindings.low_state_type,
        )
        publisher.Init()
        subscriber.Init(self._receive_state, 10)

        self._bindings = bindings
        self._publisher = publisher
        self._subscriber = subscriber
        self._crc = bindings.crc_factory()
        logger.info(
            "Initialized G1 two-arm DDS boundary on interface {}",
            self.network_interface,
        )

    def latest_state(self, **kwargs: object) -> G1ArmState:
        allow_stale = bool(kwargs.get("allow_stale", False))
        with self._state_lock:
            arm_state = self._state
        if arm_state is None:
            raise RuntimeError("No G1 low-state sample has been received")
        state_age = float(self.clock()) - arm_state.received_at
        if not allow_stale and state_age > self.state_timeout:
            raise RuntimeError(f"G1 low-state sample is stale ({state_age:.3f}s)")
        if arm_state.mode_machine != self.expected_mode_machine:
            raise RuntimeError(
                "G1 mode_machine does not match the action contract: "
                f"{arm_state.mode_machine} != {self.expected_mode_machine}"
            )
        return arm_state

    def wait_for_state(self, timeout: float) -> G1ArmState:
        if timeout <= 0.0 or not math.isfinite(timeout):
            raise ValueError("State wait timeout must be finite and positive")
        if not self._state_ready.wait(timeout):
            raise TimeoutError("Timed out waiting for G1 low state")
        arm_state = self.latest_state()
        return arm_state

    def publish_arm_positions(
        self,
        arm_positions: Sequence[float],
        **kwargs: object,
    ) -> None:
        if not self.connected:
            raise RuntimeError("G1 arm SDK helper is not connected")
        positions = tuple(float(position) for position in arm_positions)
        if len(positions) != len(self.ARM_INDICES):
            raise ValueError("Exactly 14 arm positions are required")
        if not all(math.isfinite(position) for position in positions):
            raise ValueError("Arm positions must be finite")

        kp = float(kwargs.get("kp", 40.0))
        kd = float(kwargs.get("kd", 1.0))
        weight = float(kwargs.get("weight", 1.0))
        if not all(math.isfinite(value) for value in (kp, kd, weight)):
            raise ValueError("Arm gains and authority weight must be finite")
        if kp <= 0.0 or kd < 0.0:
            raise ValueError("Arm gains must be nonnegative and kp must be positive")
        if not 0.0 <= weight <= 1.0:
            raise ValueError("Arm SDK authority weight must be between 0 and 1")

        arm_state = self.latest_state()
        command = self._build_command(
            arm_state=arm_state,
            arm_positions=positions,
            kp=kp,
            kd=kd,
            weight=weight,
        )
        self._write(command)

    def release(self) -> None:
        """Drop arm authority while preserving every measured robot position."""
        if not self.connected:
            return
        with self._state_lock:
            arm_state = self._state
        if arm_state is None:
            logger.warning("Cannot release arm_sdk authority before low state arrives")
            return
        measured_arms = tuple(
            arm_state.positions[index] for index in self.ARM_INDICES
        )
        command = self._build_command(
            arm_state=arm_state,
            arm_positions=measured_arms,
            kp=0.0,
            kd=0.0,
            weight=0.0,
        )
        self._write(command)
        logger.info("Released G1 arm_sdk authority")

    def _receive_state(self, message: Any) -> None:
        try:
            motor_states = message.motor_state
            if len(motor_states) < self.ROBOT_MOTOR_COUNT:
                raise ValueError("G1 low state has fewer than 29 motors")
            positions = tuple(
                float(motor_states[index].q)
                for index in range(self.ROBOT_MOTOR_COUNT)
            )
            if not all(math.isfinite(position) for position in positions):
                raise ValueError("G1 low state contains non-finite positions")
            temperatures = tuple(
                max(int(value) for value in motor_states[index].temperature)
                for index in range(self.ROBOT_MOTOR_COUNT)
            )
            motor_faults = tuple(
                int(motor_states[index].motorstate)
                for index in range(self.ROBOT_MOTOR_COUNT)
            )
            arm_state = G1ArmState(
                received_at=float(self.clock()),
                mode_pr=int(message.mode_pr),
                mode_machine=int(message.mode_machine),
                positions=positions,
                temperatures=temperatures,
                motor_faults=motor_faults,
            )
        except (AttributeError, TypeError, ValueError) as error:
            logger.error("Rejected malformed G1 low state: {}", error)
            return
        with self._state_lock:
            self._state = arm_state
        self._state_ready.set()

    def _build_command(
        self,
        *,
        arm_state: G1ArmState,
        arm_positions: Sequence[float],
        kp: float,
        kd: float,
        weight: float,
    ) -> Any:
        command = self._bindings.command_factory()
        command.mode_pr = arm_state.mode_pr
        command.mode_machine = arm_state.mode_machine

        for index in range(self.ROBOT_MOTOR_COUNT):
            motor_command = command.motor_cmd[index]
            motor_command.q = arm_state.positions[index]
            motor_command.dq = 0.0
            motor_command.tau = 0.0
            motor_command.kp = 0.0
            motor_command.kd = 0.0
        for arm_offset, motor_index in enumerate(self.ARM_INDICES):
            motor_command = command.motor_cmd[motor_index]
            motor_command.q = arm_positions[arm_offset]
            motor_command.kp = kp
            motor_command.kd = kd

        command.motor_cmd[self.AUTHORITY_INDEX].q = weight
        command.crc = self._crc.Crc(command)
        return command

    def _write(self, command: Any) -> None:
        write_result = self._publisher.Write(command)
        if write_result is False:
            raise RuntimeError("Unitree arm_sdk command publication failed")

    def _resolve_sdk(self) -> G1ArmSdkBindings:
        from unitree_sdk2py.core.channel import (
            ChannelFactoryInitialize,
            ChannelPublisher,
            ChannelSubscriber,
        )
        from unitree_sdk2py.idl.default import unitree_hg_msg_dds__LowCmd_
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowCmd_, LowState_
        from unitree_sdk2py.utils.crc import CRC

        sdk_bindings = G1ArmSdkBindings(
            channel_initializer=ChannelFactoryInitialize,
            publisher_factory=ChannelPublisher,
            subscriber_factory=ChannelSubscriber,
            command_factory=unitree_hg_msg_dds__LowCmd_,
            low_command_type=LowCmd_,
            low_state_type=LowState_,
            crc_factory=CRC,
        )
        return sdk_bindings


def demo_arm_sdk_helper() -> None:
    helper = G1ArmSdkHelper(network_interface="offline-demo")
    assert not helper.connected
    print("G1 arm SDK helper: safe demo only, no DDS connection")


def main() -> None:
    demo_arm_sdk_helper()


if __name__ == "__main__":
    main()
