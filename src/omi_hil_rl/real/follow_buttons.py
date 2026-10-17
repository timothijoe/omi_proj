"""Pure button arbitration shared by gamepad follow and read-only input previews."""

BTN_LB, BTN_START, BTN_SAVE, BTN_RB = 310, 304, 305, 311


class FollowButtons:
    """One action per A/B press; ignore connection/init holds and ambiguous chords."""
    def __init__(self):
        self.connected = False
        self.held = {}
        self.ready = False

    def select(self, connected, buttons, events=()):
        if not connected:
            self.connected, self.ready, self.held = False, False, {}
            return 'stop'
        if not self.connected:
            self.connected = True
            self.held = dict(buttons)
            self.ready = not (buttons.get(BTN_START) or buttons.get(BTN_SAVE))
            return None
        if buttons.get(BTN_RB):
            self.held = dict(buttons)
            self.ready = False
            return 'stop'
        if any(code == BTN_RB and pressed and not initial for code, pressed, initial in events):
            self.held = dict(buttons)
            self.ready = False
            return 'stop'
        # Event order captures even a quick press/release within one poll.
        if not events:
            events = [(k, bool(buttons.get(k)), False)
                      for k in (BTN_LB, BTN_START, BTN_SAVE)
                      if bool(buttons.get(k)) != bool(self.held.get(k))]
        actions = []
        pressed_codes = {code for code, pressed, initial in events
                         if pressed and not initial and code in (BTN_START, BTN_SAVE)}
        for code, pressed, initial in events:
            self.held[code] = pressed
            if code in (BTN_START, BTN_SAVE):
                other = BTN_SAVE if code == BTN_START else BTN_START
                if (pressed and not initial and self.ready and self.held.get(BTN_LB)
                        and not self.held.get(other) and not self.held.get(BTN_RB)):
                    actions.append('save' if code == BTN_SAVE else 'toggle')
                self.ready = not (self.held.get(BTN_START) or self.held.get(BTN_SAVE))
        self.held = dict(buttons)
        self.ready = not (buttons.get(BTN_START) or buttons.get(BTN_SAVE))
        if (len(actions) == 1 and len(pressed_codes) < 2
                and not (buttons.get(BTN_START) and buttons.get(BTN_SAVE))):
            return actions[0]
        return None


