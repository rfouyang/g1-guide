from __future__ import annotations

import unittest

from util.g1_helper.g1_action_helper.action_state_helper import (
    G1ActionStateBindings,
    G1ActionStateHelper,
)


class FakeMotorState:
    def __init__(self, position: float) -> None:
        self.q = position
        self.temperature = [25, 26]
        self.motorstate = 0


class FakeLowState:
    def __init__(self, motor_count: int = 35) -> None:
        self.version = [1, 2]
        self.mode_pr = 3
        self.mode_machine = 5
        self.tick = 1234
        self.motor_state = [
            FakeMotorState(float(index)) for index in range(motor_count)
        ]


class FakeMotionState:
    def __init__(self) -> None:
        self.error_code = 0
        self.mode = 1
        self.velocity = [0.001, -0.002, 0.0]
        self.yaw_speed = 0.003


class FakeFsmState:
    def __init__(self) -> None:
        self.fsm_id = 501
        self.fsm_mode = 0
        self.task_id = 4
        self.task_time = 0.0


class FakeSubscriber:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.callback = None
        self.queue_depth = 0

    def Init(self, callback: object, queue_depth: int) -> None:
        self.callback = callback
        self.queue_depth = queue_depth

    def emit(self, message: object) -> None:
        self.callback(message)


class FakeSubscriberBoundary:
    def __init__(self) -> None:
        self.channel_calls: list[tuple[int, str]] = []
        self.subscribers: dict[str, FakeSubscriber] = {}

    def initialize(self, domain_id: int, interface: str) -> None:
        self.channel_calls.append((domain_id, interface))

    def subscriber_factory(
        self,
        topic: str,
        _: type[object],
    ) -> FakeSubscriber:
        subscriber = FakeSubscriber(topic)
        self.subscribers[topic] = subscriber
        return subscriber

    def bindings(self) -> G1ActionStateBindings:
        return G1ActionStateBindings(
            channel_initializer=self.initialize,
            subscriber_factory=self.subscriber_factory,
            low_state_type=FakeLowState,
            fsm_state_type=FakeFsmState,
            motion_state_type=FakeMotionState,
        )


class G1ActionStateHelperTests(unittest.TestCase):
    def test_connects_only_three_read_only_state_subscribers(self) -> None:
        boundary = FakeSubscriberBoundary()
        helper = G1ActionStateHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )

        helper.connect()
        boundary.subscribers[helper.low_state_topic].emit(FakeLowState())
        boundary.subscribers[helper.fsm_state_topic].emit(FakeFsmState())
        boundary.subscribers[helper.motion_state_topic].emit(FakeMotionState())
        observation = helper.wait_for_state(0.1)

        self.assertEqual(boundary.channel_calls, [(0, "eth0")])
        self.assertEqual(
            set(boundary.subscribers),
            {"rt/lowstate", "rt/sportmodestate", "rt/odommodestate"},
        )
        self.assertEqual(observation.low_state.version, (1, 2))
        self.assertEqual(observation.low_state.mode_machine, 5)
        self.assertEqual(len(observation.low_state.positions), 35)
        self.assertEqual(observation.fsm_state.fsm_id, 501)
        self.assertEqual(observation.fsm_state.fsm_mode, 0)
        self.assertEqual(
            observation.motion_state.linear_velocity,
            (0.001, -0.002, 0.0),
        )
        self.assertEqual(observation.motion_state.yaw_speed, 0.003)

    def test_malformed_motion_state_is_rejected(self) -> None:
        boundary = FakeSubscriberBoundary()
        helper = G1ActionStateHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )
        helper.connect()
        boundary.subscribers[helper.low_state_topic].emit(FakeLowState())
        boundary.subscribers[helper.fsm_state_topic].emit(FakeFsmState())
        malformed_motion = FakeMotionState()
        malformed_motion.velocity = [float("nan"), 0.0, 0.0]
        boundary.subscribers[helper.motion_state_topic].emit(malformed_motion)

        with self.assertRaisesRegex(TimeoutError, "motion state"):
            helper.wait_for_state(0.001)

    def test_malformed_fsm_state_is_rejected(self) -> None:
        boundary = FakeSubscriberBoundary()
        helper = G1ActionStateHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )
        helper.connect()
        boundary.subscribers[helper.low_state_topic].emit(FakeLowState())
        malformed_fsm = FakeFsmState()
        malformed_fsm.task_time = float("nan")
        boundary.subscribers[helper.fsm_state_topic].emit(malformed_fsm)
        boundary.subscribers[helper.motion_state_topic].emit(FakeMotionState())

        with self.assertRaisesRegex(TimeoutError, "FSM state"):
            helper.wait_for_state(0.001)

    def test_malformed_low_state_is_rejected(self) -> None:
        boundary = FakeSubscriberBoundary()
        helper = G1ActionStateHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )
        helper.connect()
        malformed_low_state = FakeLowState()
        malformed_low_state.version = [1]
        boundary.subscribers[helper.low_state_topic].emit(malformed_low_state)
        boundary.subscribers[helper.fsm_state_topic].emit(FakeFsmState())
        boundary.subscribers[helper.motion_state_topic].emit(FakeMotionState())

        with self.assertRaisesRegex(TimeoutError, "low state"):
            helper.wait_for_state(0.001)

    def test_stale_state_is_rejected(self) -> None:
        current_time = [10.0]
        boundary = FakeSubscriberBoundary()
        helper = G1ActionStateHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: current_time[0],
            state_timeout=0.2,
        )
        helper.connect()
        boundary.subscribers[helper.low_state_topic].emit(FakeLowState())
        boundary.subscribers[helper.fsm_state_topic].emit(FakeFsmState())
        boundary.subscribers[helper.motion_state_topic].emit(FakeMotionState())
        current_time[0] = 10.3

        with self.assertRaisesRegex(RuntimeError, "stale"):
            helper.latest_state()


if __name__ == "__main__":
    unittest.main()
