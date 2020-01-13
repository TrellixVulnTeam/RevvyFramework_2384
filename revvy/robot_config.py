# SPDX-License-Identifier: GPL-3.0-only

import json
from json import JSONDecodeError

from revvy.robot.configurations import Motors, Sensors
from revvy.scripting.runtime import ScriptDescriptor
from revvy.utils.functions import b64_decode_str, dict_get_first, str_to_func
from revvy.scripting.builtin_scripts import builtin_scripts

motor_types = [
    None,
    Motors.RevvyMotor,
    # motor
    [
        [  # left
            Motors.RevvyMotor_CCW,
            Motors.RevvyMotor
        ],
        [  # right
            Motors.RevvyMotor,
            Motors.RevvyMotor_CCW
        ]
    ]
]

motor_sides = ["left", "right"]

sensor_types = [
    None,
    Sensors.HC_SR04,
    Sensors.BumperSwitch,
    Sensors.EV3_Color
]


class PortConfig:
    def __init__(self):
        self._ports = {}
        self._port_names = {}

    @property
    def names(self):
        return self._port_names

    def __getitem__(self, item):
        return self._ports.get(item)

    def __setitem__(self, item, value):
        self._ports[item] = value


class RemoteControlConfig:
    def __init__(self):
        self.analog = []
        self.buttons = [None] * 32


class ConfigError(Exception):
    pass


class RobotConfig:
    @staticmethod
    def create_runnable(script):
        try:
            script_name = dict_get_first(script, ['builtinScriptName', 'builtinscriptname'])

            try:
                return builtin_scripts[script_name]
            except KeyError as e:
                raise KeyError('Builtin script "{}" does not exist'.format(script_name)) from e

        except KeyError:
            try:
                source_b64_encoded = dict_get_first(script, ['pythonCode', 'pythoncode'])
                code = b64_decode_str(source_b64_encoded)
                return str_to_func(code)

            except KeyError as e:
                raise KeyError('Neither builtinScriptName, nor pythonCode is present for a script') from e

    @staticmethod
    def from_string(config_string):
        try:
            json_config = json.loads(config_string)
        except JSONDecodeError as e:
            raise ConfigError('Received configuration is not a valid json string') from e

        config = RobotConfig()
        try:
            robot_config = dict_get_first(json_config, ['robotConfig', 'robotconfig'])
            blockly_list = dict_get_first(json_config, ['blocklyList', 'blocklylist'])
        except KeyError as e:
            raise ConfigError('Received configuration is missing required parts') from e

        try:
            i = 0
            for script in blockly_list:
                runnable = RobotConfig.create_runnable(script)

                assignments = script['assignments']
                # script names are mostly relevant for logging
                if 'analog' in assignments:
                    for analog_assignment in assignments['analog']:
                        channels = ', '.join(map(str, analog_assignment['channels']))
                        script_name = '[script {}] analog channels {}'.format(i, channels)
                        priority = analog_assignment['priority']
                        config.controller.analog.append({
                            'channels': analog_assignment['channels'],
                            'script': ScriptDescriptor(script_name, runnable, priority)})
                        i += 1

                if 'buttons' in assignments:
                    for button_assignment in assignments['buttons']:
                        button_id = button_assignment['id']
                        script_name = '[script {}] button {}'.format(i, button_id)
                        priority = button_assignment['priority']
                        config.controller.buttons[button_id] = ScriptDescriptor(script_name, runnable, priority)
                        i += 1

                if 'background' in assignments:
                    script_name = '[script {}] background'.format(i)
                    priority = assignments['background']
                    config.background_scripts.append(ScriptDescriptor(script_name, runnable, priority))
                    i += 1
        except (TypeError, IndexError, KeyError, ValueError) as e:
            raise ConfigError('Failed to decode received controller configuration') from e

        try:
            i = 1
            motors = robot_config.get('motors', []) if type(robot_config) is dict else []
            for motor in motors:
                if not motor:
                    motor = {'type': 0}

                if motor['type'] == 0:
                    motor_type = motor_types[motor['type']]

                elif motor['type'] == 1:
                    # motor
                    motor_type = motor_types[1]
                    config.motors.names[motor['name']] = i

                elif motor['type'] == 2:
                    # drivetrain
                    motor_type = motor_types[2][motor['side']][motor['reversed']]
                    config.motors.names[motor['name']] = i
                    config.drivetrain[motor_sides[motor['side']]].append(i)

                else:
                    raise ValueError('Unknown motor type: {}'.format(motor['type']))

                config.motors[i] = motor_type
                i += 1
        except (TypeError, IndexError, KeyError, ValueError) as e:
            raise ConfigError('Failed to decode received motor configuration') from e

        try:
            i = 1
            sensors = robot_config.get('sensors', []) if type(robot_config) is dict else []
            for sensor in sensors:
                if not sensor:
                    sensor = {'type': 0}

                if sensor['type'] == 0:
                    sensor_type = sensor_types[sensor['type']]
                else:
                    sensor_type = sensor_types[sensor['type']]
                    config.sensors.names[sensor['name']] = i
                config.sensors[i] = sensor_type

                i += 1

        except (TypeError, IndexError, KeyError, ValueError) as e:
            raise ConfigError('Failed to decode received sensor configuration') from e

        return config

    def __init__(self):
        self.motors = PortConfig()
        self.sensors = PortConfig()
        self.drivetrain = {'left': [], 'right': []}
        self.controller = RemoteControlConfig()
        self.background_scripts = []


empty_robot_config = RobotConfig()
