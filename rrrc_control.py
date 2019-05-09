from rrrc_transport import RevvyTransport, Command, CommandStart, Response, ResponseHeader


class RevvyControl:
    mcu_address = 0x2D

    command_ping = 0x00
    command_get_firmware_version = 0x01
    command_get_battery_status = 0x02
    command_set_master_status = 0x10
    command_set_bluetooth_status = 0x11

    def __init__(self, transport: RevvyTransport):
        self._transport = transport

    def ping(self):
        self._transport.send_command(CommandStart(self.command_ping))

    def set_master_status(self, status):
        self._transport.send_command(CommandStart(self.command_set_master_status, [status]))

    def set_bluetooth_connection_status(self, status):
        self._transport.send_command(CommandStart(self.command_set_bluetooth_status, [status]))

    def get_firmware_version(self):
        response = self._transport.send_command(CommandStart(self.command_get_firmware_version))
        return "".join(map(chr, response.payload))

    def get_battery_status(self):
        response = self._transport.send_command(CommandStart(self.command_get_battery_status))
        return {'chargerStatus': response.payload[0], 'main': response.payload[1], 'motor': response.payload[2]}
