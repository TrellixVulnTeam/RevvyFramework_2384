import json
import traceback
from json import JSONDecodeError

from revvy.functions import b64_decode_str
from revvy.scripting.builtin_scripts import drive_joystick, drive_2sticks

motor_types = [
    # left             right
    ["NotConfigured",  "NotConfigured"],
    ["RevvyMotor_CCW", "RevvyMotor"],  # motor
    ["RevvyMotor_CCW", "RevvyMotor"],  # drivetrain
]
motor_sides = ["left", "right"]

sensor_types = ["NotConfigured", "HC_SR04", "BumperSwitch"]

builtin_scripts = {
    'drive_2sticks': drive_2sticks,
    'drive_joystick': drive_joystick
}


class PortConfig:
    def __init__(self):
        self._ports = {}
        self._port_names = {}

    @property
    def names(self):
        return self._port_names

    def __getitem__(self, item):
        return self._ports.get(item, "NotConfigured")

    def __setitem__(self, item, value):
        self._ports[item] = value


class RemoteControlConfig:
    def __init__(self):
        self.analog = []
        self.buttons = [None] * 32


def dict_get_first(dictionary, keys):
    for key in keys:
        if key in dictionary:
            return dictionary[key]
    raise KeyError


class RobotConfig:
    @staticmethod
    def from_string(config_string):
        try:
            json_config = json.loads(config_string)

            config = RobotConfig()

            robot_config = dict_get_first(json_config, ['robotConfig', 'robotconfig'])
            blockly_list = dict_get_first(json_config, ['blocklyList', 'blocklylist'])

            i = 0
            for script in blockly_list:
                try:
                    script_name = dict_get_first(script, ['builtinScriptName', 'builtinscriptname'])
                    runnable = builtin_scripts[script_name]
                except KeyError:
                    source_b64_encoded = dict_get_first(script, ['pythonCode', 'pythoncode'])
                    runnable = b64_decode_str(source_b64_encoded)

                assignments = script['assignments']
                if 'analog' in assignments:
                    for analog_assignment in assignments['analog']:
                        script_name = 'user_script_{}'.format(i)
                        priority = analog_assignment['priority']
                        config.scripts[script_name] = {'script':   runnable,
                                                       'priority': priority}
                        config.controller.analog.append({
                            'channels': analog_assignment['channels'],
                            'script': script_name})
                        i += 1

                if 'buttons' in assignments:
                    for button_assignment in assignments['buttons']:
                        script_name = 'user_script_{}'.format(i)
                        priority = button_assignment['priority']
                        config.scripts[script_name] = {'script': runnable, 'priority': priority}
                        config.controller.buttons[button_assignment['id']] = script_name
                        i += 1

                if 'background' in assignments:
                    script_name = 'user_script_{}'.format(i)
                    priority = assignments['background']
                    config.scripts[script_name] = {'script': runnable, 'priority': priority}
                    config.background_scripts.append(script_name)
                    i += 1

            if 'motors' in robot_config:
                i = 1
                for motor in robot_config['motors']:
                    if not motor or motor['type'] == 0:
                        motor_type = "NotConfigured"
                    else:
                        motor_type = motor_types[motor['type']][motor['direction']]
                        config.motors.names[motor['name']] = i

                        if motor['type'] == 2:  # drivetrain
                            config.drivetrain[motor_sides[motor['side']]].append(i)
                    config.motors[i] = motor_type

                    i += 1

            if 'sensors' in robot_config:
                i = 1
                for sensor in robot_config['sensors']:
                    if not sensor or sensor['type'] == 0:
                        sensor_type = "NotConfigured"
                    else:
                        sensor_type = sensor_types[sensor['type']]
                        config.sensors.names[sensor['name']] = i
                    config.sensors[i] = sensor_type

                    i += 1

            return config
        except (JSONDecodeError, KeyError):
            print('Failed to decode received configuration')
            print(traceback.format_exc())
            return None

    def __init__(self):
        self.motors = PortConfig()
        self.drivetrain = {'left': [], 'right': []}
        self.sensors = PortConfig()
        self.controller = RemoteControlConfig()
        self.scripts = {}
        self.background_scripts = []
