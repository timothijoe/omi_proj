"""Nonblocking Linux joystick reader using kernel semantic axis/button maps."""
import array
import fcntl
import os
import struct

from .gamepad_control import ABS_X, ABS_Y, ABS_RX, ABS_RY, ABS_HAT0X, ABS_HAT0Y, BTN_TR


class LinuxGamepad:
    def __init__(self, path='/dev/input/js0'):
        self.path = path
        self.fd = None
        self.axes, self.buttons = {}, {}
        self.error = ''
        self.button_events = []

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None
        self.axes.clear()
        self.buttons.clear()

    def poll(self):
        self.button_events = []
        try:
            if self.fd is None:
                self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK)
                self.axis_map = array.array('B', [0]*64)
                self.button_map = array.array('H', [0]*512)
                fcntl.ioctl(self.fd, 0x80406a32, self.axis_map, True)
                fcntl.ioctl(self.fd, 0x84006a34, self.button_map, True)
                n_axes, n_buttons = bytearray(1), bytearray(1)
                fcntl.ioctl(self.fd, 0x80016a11, n_axes, True)
                fcntl.ioctl(self.fd, 0x80016a12, n_buttons, True)
                self.axis_map = self.axis_map[:n_axes[0]]
                self.button_map = self.button_map[:n_buttons[0]]
                if not {ABS_X, ABS_Y, ABS_RX, ABS_RY, ABS_HAT0X, ABS_HAT0Y} <= set(self.axis_map) or BTN_TR not in self.button_map:
                    raise OSError('Device lacks required sticks, D-pad or RB')
            # Drain queued events, including initialization events. Bound work per tick.
            for _ in range(4096):
                try:
                    event = os.read(self.fd, 8)
                except BlockingIOError:
                    self.error = ''
                    return True
                if len(event) != 8:
                    raise OSError('Joystick disconnected or partial event')
                _, value, kind, index = struct.unpack('IhBB', event)
                initial = bool(kind & 0x80)
                kind &= 0x7f
                if kind == 1:
                    code = self.button_map[index]
                    self.buttons[code] = bool(value)
                    self.button_events.append((code, bool(value), initial))
                elif kind == 2:
                    self.axes[self.axis_map[index]] = max(-1., value/32767.)
            raise OSError('Joystick event backlog')
        except (OSError, IndexError) as exc:
            self.error = str(exc)
            self.close()
            return False
