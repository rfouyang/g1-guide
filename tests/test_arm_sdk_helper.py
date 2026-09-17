from __future__ import annotations

import unittest

from util.g1_helper.g1_action_helper.arm_sdk_helper import (
    G1ArmSdkBindings,
    G1ArmSdkHelper,
)


class FakeMotorCommand:
    def __init__(self) -> None:
        self.q = 0.0
        self.dq = 0.0
        self.tau = 0.0
        self.kp = 0.0
        self.kd = 0.0


class FakeCommand:
    def __init__(self) -> None:
        self.mode_pr = 0
        self.mode_machine = 0
        self.motor_cmd = [FakeMotorCommand() for _ in range(35)]
        self.crc = 0


class FakeMotorState:
    def __init__(self, position: float) -> None:
        self.q = position
        self.temperature = [25, 26]
        self.motorstate = 0


class FakeLowState:
    def __init__(self, mode_machine: int = 5) -> None:
        self.mode_pr = 3
        self.mode_machine = mode_machine
        self.motor_state = [FakeMotorState(float(index)) for index in range(35)]


class FakePublisher:
    def __init__(self) -> None:
        self.initialized = False
        self.commands: list[FakeCommand] = []

    def Init(self) -> None:
        self.initialized = True

    def Write(self, command: FakeCommand) -> bool:
        self.commands.append(command)
        return True


class FakeSubscriber:
    def __init__(self) -> None:
        self.callback = None

    def Init(self, callback: object, _: int) -> None:
        self.callback = callback

    def emit(self, state: FakeLowState) -> None:
        self.callback(state)


class FakeCrc:
    def Crc(self, _: FakeCommand) -> int:
        return 12345


class FakeSdkBoundary:
    def __init__(self) -> None:
        self.channel_calls: list[tuple[int, str]] = []
        self.publisher = FakePublisher()
        self.subscriber = FakeSubscriber()

    def initialize(self, domain_id: int, interface: str) -> None:
        self.channel_calls.append((domain_id, interface))

    def publisher_factory(self, _: str, __: type[object]) -> FakePublisher:
        return self.publisher

    def subscriber_factory(self, _: str, __: type[object]) -> FakeSubscriber:
        return self.subscriber

    def bindings(self) -> G1ArmSdkBindings:
        return G1ArmSdkBindings(
            channel_initializer=self.initialize,
            publisher_factory=self.publisher_factory,
            subscriber_factory=self.subscriber_factory,
            command_factory=FakeCommand,
            low_command_type=FakeCommand,
            low_state_type=FakeLowState,
            crc_factory=FakeCrc,
        )


class G1ArmSdkHelperTests(unittest.TestCase):
    def test_command_authority_is_limited_to_fourteen_arm_motors(self) -> None:
        boundary = FakeSdkBoundary()
        helper = G1ArmSdkHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )
        helper.connect()
        boundary.subscriber.emit(FakeLowState())

        helper.publish_arm_positions(
            [100.0 + index for index in range(14)],
            kp=30.0,
            kd=0.8,
            weight=0.5,
        )

        command = boundary.publisher.commands[0]
        self.assertEqual(boundary.channel_calls, [(0, "eth0")])
        self.assertEqual(command.mode_pr, 3)
        self.assertEqual(command.mode_machine, 5)
        self.assertEqual(command.crc, 12345)
        for motor_index in range(15):
            self.assertEqual(command.motor_cmd[motor_index].q, float(motor_index))
            self.assertEqual(command.motor_cmd[motor_index].kp, 0.0)
            self.assertEqual(command.motor_cmd[motor_index].kd, 0.0)
        for arm_offset, motor_index in enumerate(range(15, 29)):
            self.assertEqual(command.motor_cmd[motor_index].q, 100.0 + arm_offset)
            self.assertEqual(command.motor_cmd[motor_index].kp, 30.0)
            self.assertEqual(command.motor_cmd[motor_index].kd, 0.8)
        self.assertEqual(command.motor_cmd[29].q, 0.5)
        for motor_index in range(30, 35):
            self.assertEqual(command.motor_cmd[motor_index].kp, 0.0)
            self.assertEqual(command.motor_cmd[motor_index].kd, 0.0)

    def test_release_zeros_all_control_authority(self) -> None:
        boundary = FakeSdkBoundary()
        helper = G1ArmSdkHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: 10.0,
        )
        helper.connect()
        boundary.subscriber.emit(FakeLowState())

        helper.release()

        command = boundary.publisher.commands[0]
        self.assertEqual(command.motor_cmd[29].q, 0.0)
        for motor_index in range(29):
            self.assertEqual(command.motor_cmd[motor_index].q, float(motor_index))
            self.assertEqual(command.motor_cmd[motor_index].kp, 0.0)
            self.assertEqual(command.motor_cmd[motor_index].kd, 0.0)

    def test_stale_state_is_rejected(self) -> None:
        current_time = [10.0]
        boundary = FakeSdkBoundary()
        helper = G1ArmSdkHelper(
            "eth0",
            bindings=boundary.bindings(),
            clock=lambda: current_time[0],
            state_timeout=0.2,
        )
        helper.connect()
        boundary.subscriber.emit(FakeLowState())
        current_time[0] = 10.3

        with self.assertRaisesRegex(RuntimeError, "stale"):
            helper.publish_arm_positions([0.0] * 14)


if __name__ == "__main__":
    unittest.main()
