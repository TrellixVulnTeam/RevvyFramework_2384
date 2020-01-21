# SPDX-License-Identifier: GPL-3.0-only
from contextlib import suppress
from threading import Timer

from revvy.mcu.rrrc_control import RevvyControl
from revvy.robot.imu import IMU
from revvy.robot.ports.common import PortInstance
from revvy.robot.ports.motor import MotorStatus
from revvy.scripting.robot_interface import MotorConstants
from revvy.utils.awaiter import AwaiterImpl
from revvy.utils.functions import clip, rpm2dps
from revvy.utils.logger import get_logger
from revvy.utils.stopwatch import Stopwatch


class DifferentialDrivetrain:
    max_rpm = 150

    def __init__(self, interface: RevvyControl, motor_port_count, imu: IMU):
        self._interface = interface
        self._motor_count = motor_port_count
        self._motors = []
        self._left_motors = []
        self._right_motors = []

        self._log = get_logger('Drivetrain')
        self._imu = imu

        self._awaiter = None
        self._update_callback = None
        self._target_angle = 0
        self._max_turn_wheel_speed = 0
        self._max_turn_power = None
        self._last_yaw_change_time = Stopwatch()
        self._last_yaw_angle = 0

    def _on_motor_config_changed(self, motor, config):
        # if a motor config changes, remove the motor from the drivetrain
        self._motors.remove(motor)

        with suppress(ValueError):
            self._left_motors.remove(motor)

        with suppress(ValueError):
            self._right_motors.remove(motor)

    def _on_motor_status_changed(self, motor):
        callback = self._update_callback
        if callback:
            callback(motor)

    @property
    def motors(self):
        return self._motors

    def reset(self):
        self._log('reset')
        self._cancel_awaiter()

        for motor in self._motors:
            motor.on_status_changed.remove(self._on_motor_status_changed)
            motor.on_config_changed.remove(self._on_motor_config_changed)

        self._motors.clear()
        self._left_motors.clear()
        self._right_motors.clear()

    def _add_motor(self, motor: PortInstance):
        self._motors.append(motor)

        motor.on_status_changed.add(self._on_motor_status_changed)
        motor.on_config_changed.add(self._on_motor_config_changed)

    def add_left_motor(self, motor: PortInstance):
        self._log('Add motor {} to left side'.format(motor.id))
        self._left_motors.append(motor)
        self._add_motor(motor)

    def add_right_motor(self, motor: PortInstance):
        self._log('Add motor {} to right side'.format(motor.id))
        self._right_motors.append(motor)
        self._add_motor(motor)

    def _cancel_awaiter(self):
        awaiter, self._awaiter = self._awaiter, None
        if awaiter:
            awaiter.cancel()

    def stop_release(self):
        self._log('stop and release')
        self._cancel_awaiter()

        self._apply_release()

    def _update_move(self, changed_motor):
        awaiter = self._awaiter

        if awaiter:
            if changed_motor.status == MotorStatus.BLOCKED:
                self._log('motor blocked, stop')
                awaiter.cancel()
            elif all(map(lambda m: m.status == MotorStatus.GOAL_REACHED, self._motors)):
                self._log('goal reached')
                awaiter.finish()
        else:
            if changed_motor.status == MotorStatus.BLOCKED:
                self._log('motor blocked, stop')
                self.stop_release()

    def set_speeds(self, left, right, power_limit=None):
        self._log('set speeds independent')
        self._cancel_awaiter()

        self._update_callback = self._update_move
        self._apply_speeds(left, right, power_limit)

    def set_speed(self, direction, speed, unit_speed=MotorConstants.UNIT_SPEED_RPM):
        self._log("set_speeds")
        multipliers = {
            MotorConstants.DIRECTION_FWD: 1,
            MotorConstants.DIRECTION_BACK: -1,
        }

        if unit_speed == MotorConstants.UNIT_SPEED_RPM:
            self.set_speeds(
                multipliers[direction] * rpm2dps(speed),
                multipliers[direction] * rpm2dps(speed)
            )
        elif unit_speed == MotorConstants.UNIT_SPEED_PWR:
            self.set_speeds(
                multipliers[direction] * rpm2dps(self.max_rpm),
                multipliers[direction] * rpm2dps(self.max_rpm),
                power_limit=speed
            )
        else:
            raise ValueError('Invalid unit_speed: {}'.format(unit_speed))

    def _apply_release(self):
        commands = [
            *(motor.create_set_power_command(0) for motor in self._left_motors),
            *(motor.create_set_power_command(0) for motor in self._right_motors)
        ]
        self._interface.set_motor_port_control_value(commands)

    def _apply_speeds(self, left, right, power_limit):
        commands = [
            *(motor.create_set_speed_command(left, power_limit) for motor in self._left_motors),
            *(motor.create_set_speed_command(right, power_limit) for motor in self._right_motors)
        ]
        self._interface.set_motor_port_control_value(commands)

    def _update_turn_speed(self):
        error = self._target_angle - self._imu.yaw_angle
        p = clip(error * 10, -self._max_turn_wheel_speed, self._max_turn_wheel_speed)
        self._apply_speeds(-p, p, self._max_turn_power)

    def _update_turn(self, changed_motor):
        awaiter = self._awaiter
        if awaiter:
            _cancel = awaiter.cancel
            _goal_reached = awaiter.finish
        else:
            _cancel = self.stop_release
            _goal_reached = self.stop_release

        if changed_motor.status == MotorStatus.BLOCKED:
            self._update_callback = None
            _cancel()
            self._log('motor blocked, cancel turn')
        else:
            if self._last_yaw_angle != self._imu.yaw_angle:
                self._last_yaw_angle = self._imu.yaw_angle
                self._last_yaw_change_time.reset()
                if abs(self._target_angle - self._imu.yaw_angle) < 1:
                    self._update_callback = None
                    _goal_reached()
                    self._log('turn finished')
                else:
                    self._update_turn_speed()

            elif self._last_yaw_change_time.elapsed > 3:
                # yaw angle has not changed for 3 seconds
                self._update_callback = None
                _cancel()
                self._log('turn blocked, cancel')

    def turn_impl(self, turn_angle, wheel_speed=0, power_limit=None):
        self._log('turn')
        self._cancel_awaiter()

        self._max_turn_wheel_speed = wheel_speed
        self._max_turn_power = power_limit

        self._target_angle = turn_angle + self._imu.yaw_angle
        self._last_yaw_change_time.reset()
        self._last_yaw_angle = self._imu.yaw_angle

        awaiter = AwaiterImpl()
        awaiter.on_cancelled(self._apply_release)
        awaiter.on_result(self._apply_release)

        self._awaiter = awaiter
        self._update_callback = self._update_turn

        self._update_turn_speed()

        return awaiter

    def _create_timer_awaiter(self, timeout):
        awaiter = AwaiterImpl()
        t = Timer(timeout, awaiter.finish)

        awaiter.on_cancelled(t.cancel)
        awaiter.on_cancelled(self._apply_release)
        awaiter.on_result(self._apply_release)

        t.start()
        self._awaiter = awaiter

        return awaiter

    def drive(self, direction, rotation, unit_rotation, speed, unit_speed):
        self._log("drive")
        self._cancel_awaiter()
        multipliers = {
            MotorConstants.DIRECTION_FWD:   1,
            MotorConstants.DIRECTION_BACK: -1,
        }

        if unit_rotation == MotorConstants.UNIT_ROT:
            if unit_speed == MotorConstants.UNIT_SPEED_RPM:
                awaiter = self.move(
                    360 * rotation * multipliers[direction],
                    360 * rotation * multipliers[direction],
                    left_speed=rpm2dps(speed),
                    right_speed=rpm2dps(speed))

            elif unit_speed == MotorConstants.UNIT_SPEED_PWR:
                awaiter = self.move(
                    360 * rotation * multipliers[direction],
                    360 * rotation * multipliers[direction],
                    power_limit=speed)

            else:
                raise ValueError('Invalid unit_speed: {}'.format(unit_speed))

        elif unit_rotation == MotorConstants.UNIT_SEC:
            if unit_speed == MotorConstants.UNIT_SPEED_RPM:
                self.set_speeds(
                    rpm2dps(speed) * multipliers[direction],
                    rpm2dps(speed) * multipliers[direction])

            elif unit_speed == MotorConstants.UNIT_SPEED_PWR:
                self.set_speeds(
                    rpm2dps(self.max_rpm) * multipliers[direction],
                    rpm2dps(self.max_rpm) * multipliers[direction],
                    power_limit=speed)

            else:
                raise ValueError('Invalid unit_speed: {}'.format(unit_speed))

            awaiter = self._create_timer_awaiter(timeout=rotation)

        else:
            raise ValueError('Invalid unit_rotation: {}'.format(unit_rotation))

        return awaiter

    def turn(self, direction, rotation, unit_rotation, speed, unit_speed):
        self._log("turn")
        self._cancel_awaiter()
        left_multipliers = {
            MotorConstants.DIRECTION_LEFT: -1,
            MotorConstants.DIRECTION_RIGHT: 1,
        }
        right_multipliers = {
            MotorConstants.DIRECTION_LEFT:  1,
            MotorConstants.DIRECTION_RIGHT: -1,
        }
        turn_multipliers = {
            MotorConstants.DIRECTION_LEFT:  1,  # +ve number -> CCW turn
            MotorConstants.DIRECTION_RIGHT: -1,  # -ve number -> CW turn
        }

        if unit_speed == MotorConstants.UNIT_SPEED_RPM:
            power = None
        elif unit_speed == MotorConstants.UNIT_SPEED_PWR:
            power, speed = speed, self.max_rpm
        else:
            raise ValueError('Invalid unit_speed: {}'.format(unit_speed))

        if unit_rotation == MotorConstants.UNIT_SEC:

            left_speed = rpm2dps(speed) * left_multipliers[direction]
            right_speed = rpm2dps(speed) * right_multipliers[direction]
            self.set_speeds(left_speed, right_speed, power_limit=power)

            awaiter = self._create_timer_awaiter(timeout=rotation)

        elif unit_rotation == MotorConstants.UNIT_TURN_ANGLE:

            awaiter = self.turn_impl(
                rotation * turn_multipliers[direction],
                rpm2dps(speed),
                power_limit=power)

        else:
            raise ValueError('Invalid unit_rotation: {}'.format(unit_rotation))

        return awaiter

    def move(self, left, right, left_speed=None, right_speed=None, power_limit=None):
        self._log('move')
        self._cancel_awaiter()

        commands = [
            *(motor.create_relative_position_command(left, left_speed, power_limit) for motor in self._left_motors),
            *(motor.create_relative_position_command(right, right_speed, power_limit) for motor in self._right_motors)
        ]

        awaiter = AwaiterImpl()
        awaiter.on_cancelled(self._apply_release)
        awaiter.on_result(self._apply_release)

        self._awaiter = awaiter
        self._update_callback = self._update_move

        self._interface.set_motor_port_control_value(commands)

        return awaiter
