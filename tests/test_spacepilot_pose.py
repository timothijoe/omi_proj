"""SpacePilot input and pose contract; no display, USB, or daemon required."""
import ctypes as C
import math
import socket
import time
import unittest
from types import SimpleNamespace

from omi_hil_rl.hardware.spacepilot_pose import (
    Event, SpaceNav, Viewer, euler, filtered, integrate, map_motion, rotate, select_axes,
)


class SpacePilotTests(unittest.TestCase):
    def test_native_motion_events_keep_three_translation_axes_distinct(self):
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)

        class Library:
            pending = None

            def spnav_fd(self):
                return left.fileno()

            def spnav_poll_event(self, ptr):
                if self.pending is None:
                    return 0
                event = C.cast(ptr, C.POINTER(Event)).contents
                event.type = 1
                for field, value in zip(('x', 'y', 'z', 'rx', 'ry', 'rz'), self.pending):
                    setattr(event.motion, field, value)
                self.pending = None
                return 1

        driver = SpaceNav()
        driver.lib, driver.connected, driver.name = Library(), True, 'SpacePilot PRO'
        driver.next_check = float('inf')
        for native, mapped in [
            ([350, 0, 0, 0, 0, 0], [0, -350, 0, 0, 0, 0]),
            ([0, 350, 0, 0, 0, 0], [0, 0, 350, 0, 0, 0]),
            ([0, 0, 350, 0, 0, 0], [350, 0, 0, 0, 0, 0]),
        ]:
            driver.lib.pending = native
            driver.poll(1.)
            self.assertEqual(driver.device_raw, native)
            self.assertEqual(driver.raw, mapped)
        driver.poll(1.2)
        self.assertEqual(driver.device_raw, [0]*6)
        self.assertEqual(driver.raw, [0]*6)

    def test_calibrated_directions(self):
        def sample(**values):
            return SimpleNamespace(**(dict(x=0, y=0, z=0, rx=0, ry=0, rz=0) | values))
        for source, expected in [
            ({'z': 100}, [100, 0, 0, 0, 0, 0]),  # forward +X
            ({'x': 100}, [0, -100, 0, 0, 0, 0]), # right -Y
            ({'y': 100}, [0, 0, 100, 0, 0, 0]),  # up +Z
            ({'rz': 100}, [0, 0, 0, 100, 0, 0]), # corrected roll
            ({'rx': 100}, [0, 0, 0, 0, -100, 0]),
            ({'ry': 100}, [0, 0, 0, 0, 0, 100]),
        ]:
            with self.subTest(source=source):
                self.assertEqual(map_motion(sample(**source)), expected)

    def test_mode_locks_and_six_axis(self):
        raw = [.3, .2, .1, .8, .7, .6]
        values, _ = select_axes(raw, 'translation')
        p, q = integrate([0, 0, 0], (1, 0, 0, 0), values[:3], values[3:], 1)
        self.assertEqual(p, raw[:3])
        self.assertEqual(q, (1, 0, 0, 0))
        values, _ = select_axes(raw, 'rotation')
        p, q = integrate([1, 2, 3], (1, 0, 0, 0), values[:3], values[3:], 1)
        self.assertEqual(p, [1, 2, 3])
        self.assertNotEqual(q, (1, 0, 0, 0))
        self.assertEqual(select_axes(raw, 'all')[0], raw)

    def test_dominance_hysteresis_and_release(self):
        values, axis = select_axes([.3, .2, .1, 1, 1, 1], 'translation', True)
        self.assertEqual((values, axis), ([.3, 0, 0, 0, 0, 0], 0))
        self.assertEqual(select_axes([.3, .35, 0, 0, 0, 0], 'translation', True, 0)[1], 0)
        self.assertEqual(select_axes([.3, .5, 0, 0, 0, 0], 'translation', True, 0)[1], 1)
        self.assertEqual(select_axes([0]*6, 'all', True, 0), ([0]*6, None))

    def test_quaternion_and_local_translation(self):
        _, q = integrate([0]*3, (1, 0, 0, 0), [0]*3, [0, 0, math.pi/2], 1)
        for actual, expected in zip(rotate(q, [1, 0, 0]), [0, 1, 0]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(euler(q)[2], 90)
        p, _ = integrate([0]*3, q, [1, 0, 0], [0]*3, 1, local=True)
        for actual, expected in zip(p, [0, 1, 0]):
            self.assertAlmostEqual(actual, expected)
        for _ in range(1000):
            _, q = integrate([0]*3, q, [0]*3, [.1, .2, .3], .016)
        self.assertAlmostEqual(sum(x*x for x in q), 1)

    def test_deadzone(self):
        self.assertEqual(filtered(18, 18), 0)
        self.assertEqual(filtered(-10, 18), 0)
        self.assertEqual(filtered(350, 18), 1)
        self.assertEqual(filtered(-700, 18), -1)

    def test_button_batch_and_stale_motion(self):
        # Exercise the ctypes polling path with press/release in the same frame.
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)

        class Library:
            def __init__(self):
                self.events = iter([(13, 1), (13, 0), (14, 1), (14, 0), (12, 1), (12, 0), (0, 1)])

            def spnav_fd(self):
                return left.fileno()

            def spnav_poll_event(self, ptr):
                number, pressed = next(self.events, (None, None))
                if number is None:
                    return 0
                event = C.cast(ptr, C.POINTER(Event)).contents
                event.type = 2
                event.button.bnum, event.button.press = number, pressed
                return 2

        viewer = Viewer.__new__(Viewer)
        states = []
        viewer.mode = SimpleNamespace(set=states.append)
        viewer.active_axis = 1
        driver = SpaceNav(viewer.handle_button)
        driver.lib, driver.connected, driver.name = Library(), True, 'SpacePilot PRO'
        driver.next_check = float('inf')
        driver.raw = [100]*6
        driver.poll(time.monotonic())
        self.assertEqual(states, ['rotation', 'all', 'translation'])
        self.assertEqual(driver.button_events, 7)
        self.assertIsNone(viewer.active_axis)
        self.assertEqual(driver.raw, [0]*6)


if __name__ == '__main__':
    unittest.main()
