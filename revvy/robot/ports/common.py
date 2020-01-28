# SPDX-License-Identifier: GPL-3.0-only
from contextlib import suppress

from revvy.mcu.rrrc_control import RevvyControl
from revvy.utils.logger import get_logger


class FunctionAggregator:
    def __init__(self):
        self._callbacks = []

        self.add = self._callbacks.append
        self.clear = self._callbacks.clear

    def remove(self, callback):
        with suppress(ValueError):
            self._callbacks.remove(callback)

    def __call__(self, *args, **kwargs):
        for func in self._callbacks:
            func(*args, **kwargs)


class PortDriver:
    def __init__(self, driver):
        self._driver = driver
        self._on_status_changed = FunctionAggregator()

    @property
    def driver(self):
        return self._driver

    @property
    def on_status_changed(self):
        return self._on_status_changed

    def on_port_type_set(self):
        raise NotImplementedError

    def uninitialize(self):
        self._on_status_changed.clear()


class PortCollection:
    def __init__(self, ports):
        self._ports = list(ports)
        self._alias_map = {}

    @property
    def aliases(self):
        return self._alias_map

    def __getitem__(self, item):
        if type(item) is str:
            item = self._alias_map[item]

        return self._ports[item - 1]

    def __iter__(self):
        return self._ports.__iter__()


class PortHandler:
    def __init__(self, name, interface: RevvyControl, drivers: dict,
                 default_driver: PortDriver, amount: int, supported: dict):
        self._log = get_logger(f"PortHandler[{name}]")
        self._drivers = drivers
        self._types = supported
        self._port_count = amount
        self._default_driver = default_driver
        self._ports = {i: PortInstance(i, interface, self.configure_port) for i in range(1, amount + 1)}

        self._log(f'Created handler for {amount} ports')
        self._log('Supported types:\n  {}'.format("\n  ".join(self.available_types)))

    def __getitem__(self, port_idx):
        return self._ports[port_idx]

    def __iter__(self):
        return self._ports.values().__iter__()

    @property
    def available_types(self):
        """List of names of the supported drivers"""
        return self._types.keys()

    @property
    def port_count(self):
        return self._port_count

    def reset(self):
        for port in self:
            port.uninitialize()

    def _set_port_type(self, port, port_type): raise NotImplementedError

    def configure_port(self, port, config) -> PortDriver:
        if config is None:
            self._log(f'set port {port.id} to not configured')
            driver = self._default_driver

        else:
            new_driver_name = config['driver']
            self._log(f'Configuring port {port.id} to {new_driver_name}')
            driver = self._drivers[new_driver_name](port, config['config'])

        self._set_port_type(port.id, self._types[driver.driver])
        driver.on_port_type_set()

        return driver


class PortInstance:
    def __init__(self, port_idx, interface: RevvyControl, configurator):
        self._port_idx = port_idx
        self._configurator = configurator
        self._interface = interface
        self._driver = None
        self._config_changed_callbacks = FunctionAggregator()

    @property
    def id(self):
        return self._port_idx

    @property
    def interface(self):
        return self._interface

    @property
    def on_config_changed(self):
        return self._config_changed_callbacks

    def configure(self, config) -> PortDriver:
        # temporarily disable reading port
        self._config_changed_callbacks(self, None)
        if self._driver:
            self._driver.uninitialize()
        self._driver = self._configurator(self, config)
        self._config_changed_callbacks(self, config)

        return self._driver

    def uninitialize(self):
        self.configure(None)

    def __getattr__(self, name):
        return self._driver.__getattribute__(name)
