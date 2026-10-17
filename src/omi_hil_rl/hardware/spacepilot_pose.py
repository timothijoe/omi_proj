#!/usr/bin/env python3
"""Native SpacePilot six-axis object viewer; Python stdlib + libspnav."""
import argparse
import ctypes as C
import json
import math
from pathlib import Path
import select
import socket
import time
import tkinter as tk
from tkinter import filedialog, font, ttk


# SpacePilot Pro (046d:c629), zero-based libspnav button IDs.
# Its numbered keys follow Menu/Fit/view keys; they are not IDs 0/1/2.
DEVICE_MODES = {12: 'translation', 13: 'rotation', 14: 'all'}
DEFAULT_YAW = -1.15 - math.pi/2


def map_motion(m):
    """Calibrated SpacePilot input -> X forward, Y left, Z up.

    Translation signs include the user's verified forward/back correction.
    Rotation includes the user's roll-direction correction after changing frames.
    """
    return [m.z, -m.x, m.y, m.rz, -m.rx, m.ry]


def multiply(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return (w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
            w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v)


def rotate(q, v):
    return multiply(multiply(q, (0, *v)), (q[0], -q[1], -q[2], -q[3]))[1:]


def integrate(p, q, velocity, omega, dt, local=False):
    velocity = rotate(q, velocity) if local else velocity
    p = [a + b*dt for a, b in zip(p, velocity)]
    speed = math.sqrt(sum(x*x for x in omega))
    if speed > 1e-12:
        angle = speed*dt/2
        dq = (math.cos(angle), *(x/speed*math.sin(angle) for x in omega))
        q = multiply(q, dq) if local else multiply(dq, q)
        norm = math.sqrt(sum(x*x for x in q))
        q = tuple(x/norm for x in q)
    return p, q


def euler(q):
    w, x, y, z = q
    return tuple(math.degrees(v) for v in (
        math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y)),
        math.asin(max(-1, min(1, 2*(w*y-z*x)))),
        math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z))))


def filtered(raw, deadzone):
    return math.copysign(min(1, max(0, abs(raw)-deadzone)/(350-deadzone)), raw)


def select_axes(values, mode, dominant=False, previous=None):
    """Suppress excluded axes before dominance selection; retain ties stably."""
    values = list(values)
    if mode == 'translation':
        values[3:] = [0.0]*3
    elif mode == 'rotation':
        values[:3] = [0.0]*3
    if not dominant:
        return values, None
    strongest = max(range(6), key=lambda i: abs(values[i]))
    if not any(values):
        return [0.0]*6, None
    # A challenger must be 35% stronger to avoid flicker between two axes.
    if previous is not None and abs(values[previous])*1.35 >= abs(values[strongest]):
        strongest = previous
    return [v if i == strongest else 0.0 for i, v in enumerate(values)], strongest


class Motion(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('type', 'x', 'y', 'z', 'rx', 'ry', 'rz')] + [
        ('period', C.c_uint), ('data', C.POINTER(C.c_int))]


class Button(C.Structure):
    _fields_ = [(n, C.c_int) for n in ('type', 'press', 'bnum')]


class Event(C.Union):
    _fields_ = [('type', C.c_int), ('motion', Motion), ('button', Button), ('buffer', C.c_int*16)]


class SpaceNav:
    def __init__(self, on_button=None, on_reset=None):
        self.lib = None
        self.connected = False
        self.name = ''
        self.message = '等待驱动连接'
        self.next_retry = 0
        self.next_check = 0
        self.raw = [0]*6
        self.device_raw = [0]*6
        self.last_motion = 0
        self.events = 0
        self.last_button = '—'
        self.on_button = on_button
        self.on_reset = on_reset
        self.button_events = 0

    def close(self):
        if self.connected:
            self.lib.spnav_close()
        self.connected = False
        self.name = ''
        self.raw = [0]*6
        self.device_raw = [0]*6
        self.last_motion = 0
        if self.on_reset is not None:
            self.on_reset()

    def poll(self, now):
        if not self.connected:
            if now < self.next_retry:
                return
            self.next_retry = now + 2
            try:
                if self.lib is None:
                    self.lib = C.CDLL('libspnav.so.0')
                    self.lib.spnav_poll_event.argtypes = [C.POINTER(Event)]
                    self.lib.spnav_dev_name.argtypes = [C.c_char_p, C.c_int]
                if self.lib.spnav_open() < 0:
                    self.message = '驱动未启动 · 每 2 秒自动重连'
                    return
                self.connected = True
                self.lib.spnav_client_name(b'SpacePilot 6D Pose Lab')
            except OSError:
                self.message = '等待安装 spacenavd / libspnav0'
                return
        # Detect daemon EOF without taking ownership of its descriptor.
        fd = self.lib.spnav_fd()
        if fd < 0:
            self.close()
            return
        if select.select([fd], [], [], 0)[0]:
            probe = socket.fromfd(fd, socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                if not probe.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT):
                    self.close()
                    return
            except BlockingIOError:
                pass
            finally:
                probe.close()
        event = Event()
        for _ in range(512):
            if self.lib.spnav_poll_event(C.byref(event)) <= 0:
                break
            if event.type == 1:
                m = event.motion
                self.device_raw = [m.x, m.y, m.z, m.rx, m.ry, m.rz]
                self.raw = map_motion(m)
                self.last_motion = now
                self.events += 1
            elif event.type == 2:
                number, pressed = event.button.bnum, bool(event.button.press)
                label = f'实体 {number-11}' if number in DEVICE_MODES else f'ID {number}'
                self.last_button = label + ' · ' + ('按下' if pressed else '松开')
                self.button_events += 1
                # Dispatch every event, even if press and release share one frame.
                if self.on_button is not None:
                    self.on_button(number, pressed)
            elif event.type == 3:
                self.raw = [0]*6
                self.device_raw = [0]*6
                self.last_motion = 0
                self.name = ''
                if self.on_reset is not None:
                    self.on_reset()
                self.next_check = 0
        if now >= self.next_check:
            self.next_check = now + 1
            buf = C.create_string_buffer(256)
            count = self.lib.spnav_dev_name(buf, len(buf))
            self.name = buf.value.decode(errors='replace').strip() if count > 0 else ''
            self.message = self.name or '驱动已连接 · 等待 USB 设备'
        # Lost release packets / unplug must not leave the object moving.
        if now-self.last_motion > 0.15 or not self.name:
            self.raw = [0]*6
            self.device_raw = [0]*6


class Viewer:
    BG = '#101824'
    def __init__(self, root, output_dir=None):
        self.root = root
        self.output_dir = Path(output_dir) if output_dir is not None else Path.cwd()/'local'/'spacepilot'
        root.title('SpacePilot · 六自由度位姿实验室')
        # Use a predictable layout on desktops with unusually large Xft DPI.
        root.tk.call('tk', 'scaling', 1.6)
        root.geometry('1440x1000')
        root.minsize(1100, 940)
        root.configure(bg=self.BG)
        root.option_add('*Font', '{Noto Sans CJK SC} -15')
        for name in font.names(root):
            font.nametofont(name).configure(size=-15)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('.', background='#1c2838', foreground='#dfebf6', font=('Noto Sans CJK SC', -15))
        style.configure('TButton', padding=8)
        style.map('TButton', background=[('active', '#37536b')])
        style.configure('TCheckbutton', background='#1c2838')
        style.configure('TScale', troughcolor='#101824')
        self.driver = SpaceNav(self.handle_button)
        self.p = [0., 0., 0.]
        self.q = (1., 0., 0., 0.)
        self.paused = tk.BooleanVar(value=False)
        self.local = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value='translation')
        self.dominant = tk.BooleanVar(value=False)
        self.active_axis = None
        self.speed = tk.DoubleVar(value=0.35)
        self.angular = tk.DoubleVar(value=75)
        self.deadzone = tk.DoubleVar(value=18)
        # The calibrated directions are included in map_motion.
        self.signs = [tk.BooleanVar(value=False) for _ in range(6)]
        self.yaw, self.elevation, self.zoom = DEFAULT_YAW, 0.48, 340
        self.drag = None
        self.last_tick = time.monotonic()
        self.status = tk.StringVar(value='正在连接…')
        self.pose_text = tk.StringVar()
        self.detail = tk.StringVar()
        self.build()
        root.bind('<space>', lambda e: self.paused.set(not self.paused.get()))
        root.bind('<Key-r>', lambda e: self.reset())
        for key, mode in (('1', 'translation'), ('2', 'rotation'), ('3', 'all')):
            root.bind(f'<Key-{key}>', lambda e, m=mode: self.set_mode(m))
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.tick()

    def build(self):
        header = tk.Frame(self.root, bg=self.BG)
        header.pack(fill='x', padx=24, pady=(18, 12))
        tk.Label(header, text='SPACEPILOT  /  6D POSE LAB', bg=self.BG, fg='#6fe0ce',
                 font=('Noto Sans CJK SC', -26, 'bold')).pack(anchor='w')
        tk.Label(header, textvariable=self.status, bg=self.BG, fg='#b0c5d8').pack(anchor='w', pady=(5, 0))
        body = tk.Frame(self.root, bg=self.BG)
        body.pack(fill='both', expand=True, padx=24, pady=(0, 20))
        side = ttk.Frame(body, padding=16, width=370)
        side.pack(side='right', fill='y', padx=(16, 0))
        side.pack_propagate(False)
        self.canvas = tk.Canvas(body, bg='#131e2c', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<ButtonPress-1>', lambda e: setattr(self, 'drag', (e.x, e.y)))
        self.canvas.bind('<B1-Motion>', self.orbit)
        self.canvas.bind('<Button-4>', lambda e: self.set_zoom(1.1))
        self.canvas.bind('<Button-5>', lambda e: self.set_zoom(1/1.1))
        ttk.Label(side, text='物体位姿', font=('Noto Sans CJK SC', -19, 'bold')).pack(anchor='w')
        ttk.Label(side, textvariable=self.pose_text, font=('DejaVu Sans Mono', -16), justify='left').pack(anchor='w', pady=10)
        ttk.Separator(side).pack(fill='x', pady=6)
        for label, var, lo, hi, unit in (
                ('平移速度', self.speed, .05, 1.5, 'm/s'),
                ('旋转速度', self.angular, 10, 180, '°/s'),
                ('中心死区', self.deadzone, 0, 80, '')):
            text = tk.StringVar()
            def update(*_, t=text, v=var, name=label, u=unit):
                t.set(f'{name}   {v.get():.2f} {u}')
            var.trace_add('write', update)
            update()
            ttk.Label(side, textvariable=text).pack(anchor='w', pady=(8, 0))
            ttk.Scale(side, from_=lo, to=hi, variable=var).pack(fill='x')
        ttk.Label(side, text='操控模式（实体键 / 键盘 1·2·3）').pack(anchor='w', pady=(8, 3))
        modes = ttk.Frame(side)
        modes.pack(fill='x')
        for label, mode in (('仅平移', 'translation'), ('仅旋转', 'rotation'), ('六轴', 'all')):
            ttk.Radiobutton(modes, text=label, value=mode, variable=self.mode,
                            command=lambda: self.set_mode(self.mode.get())).pack(side='left', padx=(0, 12))
        ttk.Checkbutton(side, text='单轴优先（只响应力度最大的一轴）', variable=self.dominant).pack(anchor='w')
        ttk.Checkbutton(side, text='使用物体局部坐标系', variable=self.local).pack(anchor='w')
        ttk.Checkbutton(side, text='暂停操控  [Space]', variable=self.paused).pack(anchor='w')
        ttk.Label(side, text='反转方向（默认：前 +X / 左 +Y / 上 +Z）').pack(anchor='w', pady=(7, 3))
        invert = ttk.Frame(side)
        invert.pack(fill='x')
        for i, name in enumerate(('前后 X', '左右 Y', '上下 Z', 'Rx', 'Ry', 'Rz')):
            ttk.Checkbutton(invert, text=name, variable=self.signs[i]).grid(row=i//3, column=i%3, sticky='w', padx=(0, 15))
        ttk.Button(side, text='物体复位  [R]', command=self.reset).pack(fill='x', pady=(8, 3))
        ttk.Button(side, text='恢复默认视角', command=self.center).pack(fill='x', pady=3)
        ttk.Button(side, text='导出位姿 JSON', command=self.export).pack(fill='x', pady=3)
        ttk.Label(side, textvariable=self.detail, wraplength=295, foreground='#9eb4c8').pack(anchor='w', pady=(10, 0))
        self.bars = tk.Canvas(side, height=96, bg='#1c2838', highlightthickness=0)
        self.bars.pack(fill='x', pady=(7, 0))

    def center(self):
        self.yaw, self.elevation, self.zoom = DEFAULT_YAW, .48, 340

    def set_mode(self, mode):
        self.mode.set(mode)
        self.active_axis = None

    def handle_button(self, number, pressed):
        if pressed and number in DEVICE_MODES:
            mode = DEVICE_MODES[number]
            self.set_mode(mode)
            print(f'SpacePilot button {number-11} (id={number}) -> {mode}', flush=True)

    def set_zoom(self, factor):
        self.zoom = max(60, min(900, self.zoom*factor))

    def orbit(self, event):
        if self.drag:
            self.yaw -= (event.x-self.drag[0])*.007
            self.elevation = max(.08, min(1.5, self.elevation+(event.y-self.drag[1])*.007))
        self.drag = (event.x, event.y)

    def reset(self):
        self.p, self.q = [0., 0., 0.], (1., 0., 0., 0.)

    def export(self):
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = filedialog.asksaveasfilename(defaultextension='.json', initialdir=str(self.output_dir.resolve()),
                                          initialfile='spacepilot_pose.json',
                                          filetypes=[('JSON', '*.json')])
        if path:
            Path(path).write_text(json.dumps({
                'frame': 'right-handed X-forward Y-left Z-up world', 'position_m': self.p,
                'position_order': ['x', 'y', 'z'],
                'quaternion_wxyz': self.q, 'rpy_degrees': euler(self.q),
                'rpy_convention': 'R = Rz(yaw) Ry(pitch) Rx(roll)',
            }, indent=2)+'\n')

    def project(self, point):
        # Orthographic orbit camera, tracking the object translation halfway.
        x, y, z = (point[i] - self.p[i]*.5 for i in range(3))
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        ce, se = math.cos(self.elevation), math.sin(self.elevation)
        right, forward = -s*x+c*y, c*x+s*y
        return (self.canvas.winfo_width()/2+right*self.zoom,
                self.canvas.winfo_height()*.50-(z*ce-forward*se)*self.zoom,
                forward*ce+z*se)

    def line(self, a, b, **kw):
        self.canvas.create_line(*self.project(a)[:2], *self.project(b)[:2], **kw)

    def draw(self):
        c = self.canvas
        c.delete('all')
        for i in range(-10, 11):
            n = i*.25
            color = '#35475a' if i == 0 else '#243346'
            self.line((n, -2.5, -.42), (n, 2.5, -.42), fill=color)
            self.line((-2.5, n, -.42), (2.5, n, -.42), fill=color)
        colors = ('#f57f87', '#70d6a0', '#71b9ff')
        for i, name in enumerate(('X', 'Y', 'Z')):
            v = [0, 0, 0]
            v[i] = .8
            self.line((0, 0, 0), v, fill=colors[i], width=2, dash=(4, 4), arrow=tk.LAST)
            px, py, _ = self.project(v)
            c.create_text(px+10, py, text=name, fill=colors[i], font=('DejaVu Sans', -16, 'bold'))
        vertices = [(-.35,-.24,-.18), (.35,-.24,-.18), (.35,.24,-.18), (-.35,.24,-.18),
                    (-.35,-.24,.18), (.35,-.24,.18), (.35,.24,.18), (-.35,.24,.18)]
        world = [tuple(a+b for a,b in zip(rotate(self.q, v), self.p)) for v in vertices]
        points = [self.project(v) for v in world]
        faces = [((0,1,2,3),'#237f84'), ((4,5,6,7),'#64d5c7'), ((0,1,5,4),'#39a8ac'),
                 ((1,2,6,5),'#e4ae62'), ((2,3,7,6),'#288890'), ((3,0,4,7),'#377b91')]
        for indices, color in sorted(faces, key=lambda f: sum(points[i][2] for i in f[0])):
            c.create_polygon(*[n for i in indices for n in points[i][:2]], fill=color, outline='#b7f0e5', width=2)
        for i in range(3):
            v = [0, 0, 0]
            v[i] = .62
            tip = tuple(a+b for a,b in zip(rotate(self.q, v), self.p))
            self.line(self.p, tip, fill=colors[i], width=3, arrow=tk.LAST)
        px, py, _ = self.project(self.p)
        c.create_oval(px-4, py-4, px+4, py+4, fill='white', outline='')
        mode = {'translation': '仅平移 · 姿态锁定', 'rotation': '仅旋转 · 位置锁定', 'all': '六轴同时操控'}[self.mode.get()]
        if self.dominant.get():
            mode += '  /  单轴优先'
        c.create_text(20, 20, anchor='nw', fill='#6fe0ce', text=f'{mode}    [1 平移 / 2 旋转 / 3 六轴]')
        c.create_text(20, 48, anchor='nw', fill='#829db6', text='前 +X · 左 +Y · 上 +Z    实线：物体轴 / 虚线：世界轴    网格：0.25 m')
        c.create_text(20, c.winfo_height()-22, anchor='sw', fill='#829db6',
                      text='普通鼠标拖动：观察视角    滚轮：缩放    原点为初始物体中心')
        if self.paused.get():
            c.create_text(c.winfo_width()/2, 84, text='已暂停', fill='#e4ae62', font=('Noto Sans CJK SC', -26, 'bold'))

    def tick(self):
        now = time.monotonic()
        dt = min(.05, now-self.last_tick)
        self.last_tick = now
        self.driver.poll(now)
        raw = self.driver.raw
        values = [filtered(v, self.deadzone.get())*(-1 if s.get() else 1) for v,s in zip(raw,self.signs)]
        values, self.active_axis = select_axes(values, self.mode.get(), self.dominant.get(), self.active_axis)
        if not self.paused.get():
            v = [x*self.speed.get() for x in values[:3]]
            w = [x*math.radians(self.angular.get()) for x in values[3:]]
            self.p, self.q = integrate(self.p, self.q, v, w, dt, self.local.get())
        self.status.set(('●  ' if self.driver.name else '○  ') + self.driver.message)
        rpy = euler(self.q)
        self.pose_text.set('X / Y / Z  (m)\n' + '  '.join(f'{x:+.3f}' for x in self.p) +
                           '\n\nROLL / PITCH / YAW / °\n' + '  '.join(f'{x:+.1f}' for x in rpy))
        self.detail.set(f'运动事件：{self.driver.events}    按键：{self.driver.last_button}')
        self.bars.delete('all')
        for i, (label, value) in enumerate(zip(('X','Y','Z','Rx','Ry','Rz'), raw)):
            y = 8+i*15
            self.bars.create_text(4, y, anchor='w', text=label, fill='#b0c5d8', font=('DejaVu Sans', -12))
            self.bars.create_line(50, y, 230, y, fill='#334559', width=5)
            self.bars.create_line(140, y, 140+max(-90,min(90,value/350*90)), y, fill='#6fe0ce', width=5)
            self.bars.create_text(280,y,anchor='e',text=str(value),fill='#b0c5d8',font=('DejaVu Sans Mono',-11))
        self.draw()
        self.root.after(16, self.tick)

    def close(self):
        self.driver.close()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description='SpacePilot 六自由度物体位姿演示（不发送机器人指令）')
    parser.add_argument('--probe', type=float, metavar='SECONDS', help='read actual device events without opening a window')
    parser.add_argument('--output-dir', type=Path, default=Path.cwd()/'local'/'spacepilot',
                        help='default pose export directory (default: ./local/spacepilot)')
    args = parser.parse_args()
    if args.probe is not None:
        driver = SpaceNav()
        end = time.monotonic()+args.probe
        previous = -1
        previous_buttons = 0
        try:
            while time.monotonic() < end:
                driver.poll(time.monotonic())
                if driver.events != previous:
                    print(driver.message, 'events=', driver.events, 'axes=', driver.raw, flush=True)
                    previous = driver.events
                if driver.button_events != previous_buttons:
                    print('button:', driver.last_button, 'events=', driver.button_events, flush=True)
                    previous_buttons = driver.button_events
                time.sleep(.01)
            print(json.dumps({'connected': driver.connected, 'device': driver.name,
                              'motion_events': driver.events, 'button_events': driver.button_events}))
        finally:
            driver.close()
    else:
        root = tk.Tk()
        Viewer(root, output_dir=args.output_dir)
        root.mainloop()


if __name__ == '__main__':
    main()
