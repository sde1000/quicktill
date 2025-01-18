"""
This module defines classes whose instances are typically sent to
ui.handle_keyboard_input() by the keyboard driver.

Till configurations can define as many new keycodes as they need.

"""


class keycode:
    """A keyboard input from the user
    """
    def __new__(cls, name, keycap, *args, **kwargs):
        # If a keycode of this name already exists, return it instead
        existing = globals().get(name)
        if existing:
            return existing
        self = object.__new__(cls)
        self.name = name
        self.keycap = keycap
        self._register()
        return self

    def __init__(self, *args, **kwargs):
        pass

    def _register(self):
        globals()[self.name] = self

    def __str__(self):
        return self.keycap

    def __repr__(self):
        return '%s("%s","%s")' % (self.__class__.__name__,
                                  self.name, self.keycap)


class paymentkey(keycode):
    def __init__(self, name, keycap, method):
        self.paymentmethod = method


class notekey(paymentkey):
    def __init__(self, name, keycap, method, notevalue):
        paymentkey.__init__(self, name, keycap, method)
        self.notevalue = notevalue


class linekey(keycode):
    def __new__(cls, line):
        existing = globals().get("K_LINE%d" % line)
        if existing:
            return existing
        self = object.__new__(cls)
        self._line = line
        self._register()
        return self

    def __init__(self, *args, **kwargs):
        pass

    @property
    def name(self):
        return "K_LINE%d" % self._line

    @property
    def keycap(self):
        from . import td, models
        cap = td.s.get(models.KeyCap, self.name)
        if cap:
            return cap.keycap
        return ""

    @property
    def css_class(self):
        from . import td, models
        cap = td.s.get(models.KeyCap, self.name)
        if cap:
            return cap.css_class

    @property
    def line(self):
        return self._line

    def __repr__(self):
        return "linekey(%d)" % self._line


# The only keycodes that need to be defined here are those referred to
# explicitly in the till code.  All other keycodes are defined in the
# till configuration module.

# Text entry keys
keycode("K_BACKSPACE", "Backspace")
keycode("K_DEL", "Del")
keycode("K_HOME", "Home")
keycode("K_END", "End")
keycode("K_EOL", "Kill to EOL")
keycode("K_TAB", "Tab")

# Till management keys
keycode("K_USESTOCK", "Use Stock")
keycode("K_WASTE", "Record Waste")
keycode("K_MANAGETILL", "Manage Till")
keycode("K_CANCEL", "Cancel")
keycode("K_CLEAR", "Clear")
keycode("K_PRINT", "Print")
keycode("K_MARK", "Mark")
keycode("K_RECALLTRANS", "Recall Transaction")
keycode("K_MANAGETRANS", "Manage Transaction")
keycode("K_QUANTITY", "Quantity")
keycode("K_FOODORDER", "Order Food")
keycode("K_FOODMESSAGE", "Kitchen Message")
keycode("K_STOCKTERMINAL", "Stock Terminal")
keycode("K_APPS", "Apps")
keycode("K_MANAGESTOCK", "Manage Stock")
keycode("K_PRICECHECK", "Price Check")
keycode("K_LOCK", "Lock")
keycode("K_ONLINE_ORDERS", "Online Orders")

# Tendering keys referred to in the code
keycode("K_CASH", "Cash / Enter")
keycode("K_DRINKIN", "Drink 'In'")

numberkeys = [
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "00", ".",
]
cursorkeys = [
    keycode("K_LEFT", "◀"),
    keycode("K_RIGHT", "▶"),
    keycode("K_UP", "▲"),
    keycode("K_DOWN", "▼"),
    keycode("K_PAGEUP", "Page Up"),
    keycode("K_PAGEDOWN", "Page Down"),
]


class Key:
    """A key on the till's keyboard

    May be physical, on-screen, or both.
    """
    def __init__(self, keycode, css_class=None, width=1, height=1):
        self.keycode = keycode
        self._css_class = css_class
        self.width = width
        self.height = height

    @property
    def css_class(self):
        return getattr(self.keycode, 'css_class', None) or self._css_class

    def __str__(self):
        return str(self.keycode)
