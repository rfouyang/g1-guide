from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger

from util.g1_helper.g1_network_helper import G1NetworkHelper


@dataclass(frozen=True)
class G1LowStateObservation:
    """Validated fields observed from one G1 low-state sample."""

    received_at: float
    version: tuple[int, int]
    mode_pr: int
    mode_machine: int
    tick: int
    positions: tuple[float, ...]
    temperatures: tuple[int, ...]
    motor_faults: tuple[int, ...]


@dataclass(frozen=True)
class G1MotionStateObservation:
    """Validated read-only base-motion fields from one sport-state sample."""

    received_at: float
    error_code: int
    mode: int
    linear_velocity: tuple[float, float, float]
    yaw_speed: float


@dataclass(frozen=True)
class G1FsmStateObservation:
    """Validated G1 locomotion FSM fields from one sport-state sample."""

    received_at: float
    fsm_id: int
    fsm_mode: int
    task_id: int
    task_time: float


@dataclass(frozen=True)
class G1ActionStateObservation:
    """Low-level, FSM, and base-motion observations for action preflight."""

    low_state: G1LowStateObservation
    fsm_state: G1FsmStateObservation
    motion_state: G1MotionStateObservation


@dataclass(frozen=True)
class G1ActionStateBindings:
    """Injectable constructors for the subscriber-only DDS boundary."""

    channel_initializer: Callable[..., object]
    subscriber_factory: Callable[..., Any]
    low_state_type: type[Any]
    fsm_state_type: type[Any]
    motion_state_type: type[Any]


class G1ActionStateHelper:
    """Observe G1 action safety state without constructing a command publisher."""

    LOW_STATE_TOPIC = "rt/lowstate"
    FSM_STATE_TOPIC = "rt/sportmodestate"
    FSM_STATE_SCHEMA = "unitree_hg.msg.dds_.SportModeState_"
    MOTION_STATE_TOPIC = "rt/odommodestate"
    MOTION_STATE_SCHEMA = "unitree_go.msg.dds_.SportModeState_"

    def __init__(
        self,
        network_interface: str | None = None,
        **kwargs: object,
    ) -> None:
        if network_interface is None:
            network_interface = G1NetworkHelper.detect()
        self.network_interface = network_interface.strip()
        self.state_timeout = float(kwargs.get("state_timeout", 0.2))
        self.clock = kwargs.get("clock", time.monotonic)
        self.low_state_topic = str(
            kwargs.get("low_state_topic", self.LOW_STATE_TOPIC)
        ).strip()
        self.fsm_state_topic = str(
            kwargs.get("fsm_state_topic", self.FSM_STATE_TOPIC)
        ).strip()
        self.motion_state_topic = str(
            kwargs.get("motion_state_topic", self.MOTION_STATE_TOPIC)
        ).strip()
        self.fsm_state_schema = self.FSM_STATE_SCHEMA
        self.motion_state_schema = self.MOTION_STATE_SCHEMA
        self._bindings = kwargs.get("bindings")
        self._low_state_subscriber: Any | None = None
        self._fsm_state_subscriber: Any | None = None
        self._motion_state_subscriber: Any | None = None
        self._low_state: G1LowStateObservation | None = None
        self._fsm_state: G1FsmStateObservation | None = None
        self._motion_state: G1MotionStateObservation | None = None
        self._state_lock = threading.Lock()
        self._low_state_ready = threading.Event()
        self._fsm_state_ready = threading.Event()
        self._motion_state_ready = threading.Event()

        if not self.network_interface:
            raise ValueError("network_interface cannot be empty")
        if not math.isfinite(self.state_timeout) or self.state_timeout <= 0.0:
            raise ValueError("state_timeout must be finite and positive")
        if not callable(self.clock):
            raise TypeError("clock must be callable")
        if not all(
            (self.low_state_topic, self.fsm_state_topic, self.motion_state_topic)
        ):
            raise ValueError("DDS state topics cannot be empty")
        if self._bindings is not None and not isinstance(
            self._bindings,
            G1ActionStateBindings,
        ):
            raise TypeError("bindings must be G1ActionStateBindings")

    @property
    def connected(self) -> bool:
        subscribers_ready = (
            self._low_state_subscriber is not None
            and self._fsm_state_subscriber is not None
            and self._motion_state_subscriber is not None
        )
        return subscribers_ready

    def connect(self) -> None:
        if self.connected:
            return
        bindings = self._bindings or self._resolve_sdk()
        bindings.channel_initializer(0, self.network_interface)
        low_state_subscriber = bindings.subscriber_factory(
            self.low_state_topic,
            bindings.low_state_type,
        )
        fsm_state_subscriber = bindings.subscriber_factory(
            self.fsm_state_topic,
            bindings.fsm_state_type,
        )
        motion_state_subscriber = bindings.subscriber_factory(
            self.motion_state_topic,
            bindings.motion_state_type,
        )
        low_state_subscriber.Init(self._receive_low_state, 10)
        fsm_state_subscriber.Init(self._receive_fsm_state, 10)
        motion_state_subscriber.Init(self._receive_motion_state, 10)

        self._bindings = bindings
        self._low_state_subscriber = low_state_subscriber
        self._fsm_state_subscriber = fsm_state_subscriber
        self._motion_state_subscriber = motion_state_subscriber
        logger.info(
            "Initialized read-only G1 action state on interface {}",
            self.network_interface,
        )

    def wait_for_state(self, timeout: float) -> G1ActionStateObservation:
        if not math.isfinite(timeout) or timeout <= 0.0:
            raise ValueError("State wait timeout must be finite and positive")
        deadline = float(self.clock()) + timeout
        self._wait_for_event(self._low_state_ready, deadline, "low state")
        self._wait_for_event(self._fsm_state_ready, deadline, "FSM state")
        self._wait_for_event(self._motion_state_ready, deadline, "motion state")
        state_observation = self.latest_state(allow_stale=True)
        return state_observation

    def latest_state(self, **kwargs: object) -> G1ActionStateObservation:
        allow_stale = bool(kwargs.get("allow_stale", False))
        with self._state_lock:
            low_state = self._low_state
            fsm_state = self._fsm_state
            motion_state = self._motion_state
        if low_state is None or fsm_state is None or motion_state is None:
            raise RuntimeError("G1 action preflight state is incomplete")
        if not allow_stale:
            self._require_fresh(low_state.received_at, "low state")
            self._require_fresh(fsm_state.received_at, "FSM state")
            self._require_fresh(motion_state.received_at, "motion state")
        state_observation = G1ActionStateObservation(
            low_state=low_state,
            fsm_state=fsm_state,
            motion_state=motion_state,
        )
        return state_observation

    def _wait_for_event(
        self,
        state_event: threading.Event,
        deadline: float,
        state_name: str,
    ) -> None:
        remaining = deadline - float(self.clock())
        if remaining <= 0.0 or not state_event.wait(remaining):
            raise TimeoutError(f"Timed out waiting for G1 {state_name}")

    def _require_fresh(self, received_at: float, state_name: str) -> None:
        state_age = float(self.clock()) - received_at
        if (
            not math.isfinite(state_age)
            or state_age < 0.0
            or state_age > self.state_timeout
        ):
            raise RuntimeError(
                f"G1 {state_name} sample is stale ({state_age:.3f}s)"
            )

    def _receive_low_state(self, message: Any) -> None:
        try:
            version = tuple(int(part) for part in message.version)
            if len(version) != 2:
                raise ValueError("version must contain two integers")
            motor_states = tuple(message.motor_state)
            if not motor_states:
                raise ValueError("motor_state cannot be empty")
            positions = tuple(float(motor_state.q) for motor_state in motor_states)
            if not all(math.isfinite(position) for position in positions):
                raise ValueError("motor positions must be finite")
            temperatures = tuple(
                max(int(value) for value in motor_state.temperature)
                for motor_state in motor_states
            )
            motor_faults = tuple(
                int(motor_state.motorstate) for motor_state in motor_states
            )
            low_state = G1LowStateObservation(
                received_at=float(self.clock()),
                version=(version[0], version[1]),
                mode_pr=int(message.mode_pr),
                mode_machine=int(message.mode_machine),
                tick=int(message.tick),
                positions=positions,
                temperatures=temperatures,
                motor_faults=motor_faults,
            )
        except (AttributeError, OverflowError, TypeError, ValueError) as error:
            logger.error("Rejected malformed G1 low state: {}", error)
            return
        with self._state_lock:
            self._low_state = low_state
        self._low_state_ready.set()

    def _receive_fsm_state(self, message: Any) -> None:
        try:
            fsm_id = int(message.fsm_id)
            fsm_mode = int(message.fsm_mode)
            task_id = int(message.task_id)
            task_time = float(message.task_time)
            if min(fsm_id, fsm_mode, task_id) < 0:
                raise ValueError("FSM identifiers must be nonnegative")
            if not math.isfinite(task_time) or task_time < 0.0:
                raise ValueError("task_time must be finite and nonnegative")
            fsm_state = G1FsmStateObservation(
                received_at=float(self.clock()),
                fsm_id=fsm_id,
                fsm_mode=fsm_mode,
                task_id=task_id,
                task_time=task_time,
            )
        except (AttributeError, OverflowError, TypeError, ValueError) as error:
            logger.error("Rejected malformed G1 FSM state: {}", error)
            return
        with self._state_lock:
            self._fsm_state = fsm_state
        self._fsm_state_ready.set()

    def _receive_motion_state(self, message: Any) -> None:
        try:
            raw_velocity = tuple(float(speed) for speed in message.velocity)
            if len(raw_velocity) < 3:
                raise ValueError("velocity must contain three values")
            linear_velocity = (
                raw_velocity[0],
                raw_velocity[1],
                raw_velocity[2],
            )
            yaw_speed = float(message.yaw_speed)
            if not all(
                math.isfinite(speed)
                for speed in (*linear_velocity, yaw_speed)
            ):
                raise ValueError("base velocities must be finite")
            motion_state = G1MotionStateObservation(
                received_at=float(self.clock()),
                error_code=int(message.error_code),
                mode=int(message.mode),
                linear_velocity=linear_velocity,
                yaw_speed=yaw_speed,
            )
        except (AttributeError, OverflowError, TypeError, ValueError) as error:
            logger.error("Rejected malformed G1 motion state: {}", error)
            return
        with self._state_lock:
            self._motion_state = motion_state
        self._motion_state_ready.set()

    def _resolve_sdk(self) -> G1ActionStateBindings:
        from unitree_sdk2py.core.channel import (
            ChannelFactoryInitialize,
            ChannelSubscriber,
        )
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import SportModeState_
        from unitree_sdk2py.idl.unitree_hg.msg.dds_ import LowState_

        from util.g1_helper.g1_action_helper.g1_sport_mode_state_helper import (
            G1SportModeState,
        )

        sdk_bindings = G1ActionStateBindings(
            channel_initializer=ChannelFactoryInitialize,
            subscriber_factory=ChannelSubscriber,
            low_state_type=LowState_,
            fsm_state_type=G1SportModeState,
            motion_state_type=SportModeState_,
        )
        return sdk_bindings


def demo_action_state_helper() -> None:
    helper = G1ActionStateHelper(network_interface="offline-demo")
    assert not helper.connected
    print("G1 action state helper: safe demo only, no DDS connection")


def main() -> None:
    demo_action_state_helper()


if __name__ == "__main__":
    main()
