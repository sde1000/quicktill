import sys
import locale
import curses, curses.ascii, curses.panel
from . import ui
from . import keyboard
from . import tillconfig

import logging
log = logging.getLogger(__name__)

c = locale.getpreferredencoding()

colours = {
    "black": curses.COLOR_BLACK,
    "red": curses.COLOR_RED,
    "green": curses.COLOR_GREEN,
    "yellow": curses.COLOR_YELLOW,
    "blue": curses.COLOR_BLUE,
    "magenta": curses.COLOR_MAGENTA,
    "cyan": curses.COLOR_CYAN,
    "white": curses.COLOR_WHITE,
}

# curses colorpairs indexed by (foreground, background)
_colourpair_cache = {}

# There doesn't appear to be a way to find the maximum number of
# colour pairs - the COLOR_PAIRS global variable described in man(3)
# color_pair isn't exposed by the python module
_curses_pair = iter(range(1, 256))

def _init_colourpairs():
    # If we create curses colorpairs for all the pre-defined colour
    # pairs at startup, we may avoid unnecessary screen redraws later
    for cp in ui.colourpair.all_colourpairs:
        _curses_attr(cp)

def _curses_attr(colour):
    if hasattr(colour, '_curses_attr'):
        return colour._curses_attr
    if hasattr(colour, '_reversed')\
       and hasattr(colour._reversed, '_curses_attr'):
        base_pair = colour._reversed._curses_attr
        new_pair = base_pair ^ curses.A_REVERSE
        colour._curses_attr = new_pair
        return new_pair
    foreground = colours[colour.foreground]
    background = colours[colour.background]
    if (foreground, background) in _colourpair_cache:
        number = _colourpair_cache[(foreground, background)]
    else:
        number = next(_curses_pair)
        curses.init_pair(number, foreground, background)
        _colourpair_cache[(foreground, background)] = number
    colour._curses_attr = curses.color_pair(number)
    return colour._curses_attr

class window_stack:
    def __init__(self, stack):
        self._stack = stack

    def restore(self):
        for i in self._stack:
            i._pan.show()
        i._check_on_top()

class curses_window:
    """A window to draw text in
    """
    def __init__(self, win, pan=None, colour = ui.colour_default,
                 always_on_top=False):
        self._win = win
        self._pan = pan
        # ui code can access the colour attribute to decide what
        # colour to use for (eg.) reversed text, etc.
        self.colour = colour
        self.always_on_top = always_on_top

    def destroy(self):
        if self._pan:
            self._pan.hide()
        del self._win, self._pan

    def flush(self):
        # Flush output to the display immediately, if possible
        _doupdate()

    def isendwin(self):
        """Has the display been shut down?
        """
        return curses.isendwin()

    def size(self):
        return self._win.getmaxyx()

    def new(self, height, width, y, x, colour=None, always_on_top=False):
        """Create and return a new window on top of the stack of windows
        """
        if not colour:
            colour = ui.colour_default
        win = curses.newwin(height, width, y, x)
        pan = curses.panel.new_panel(win)
        cw = curses_window(win, pan, colour=colour, always_on_top=always_on_top)
        pan.set_userptr(cw)
        self._check_on_top()
        win.bkgdset(ord(' '), _curses_attr(colour))
        win.erase()
        return cw

    def save_stack(self):
        # Hide this window and all windows on top of it (excluding
        # those marked "always on top") and return an object that can
        # be used to restore them.
        l = []
        t = curses.panel.top_panel()
        while t.userptr() != self:
            to_save = t.userptr()
            t = t.below()
            if not to_save.always_on_top:
                l.append(to_save)
                to_save._pan.hide()
        l.append(self)
        self._pan.hide()
        l.reverse()
        return window_stack(l)

    def _check_on_top(self):
        # Check the panel stack for panels that are supposed to be on
        # top of others and restore them to that position
        t = curses.panel.top_panel()
        to_raise = []
        while t:
            if t.userptr().always_on_top:
                to_raise.append(t)
            t = t.below()
        for p in to_raise:
            p.top()

    def addstr(self, y, x, s, colour=None):
        if colour is None:
            colour = self.colour
        try:
            self._win.addstr(y, x, s.encode(c), _curses_attr(colour))
        except curses.error:
            log.debug("addstr problem: len(s)=%d; s=%s", len(s), repr(s))

    def getyx(self):
        return self._win.getyx()

    def move(self, y, x):
        return self._win.move(y, x)

    def erase(self):
        return self._win.erase()

    def border(self):
        return self._win.border()

    def set_cursor(self, state):
        # Not yet implemented - we will have to keep track of which
        # window has the input focus and turn the cursor on and off
        # based on that
        pass

def _doupdate():
    curses.panel.update_panels()
    curses.doupdate()

# curses codes and their till keycode equivalents
kbcodes = {
    curses.KEY_LEFT: keyboard.K_LEFT,
    curses.KEY_RIGHT: keyboard.K_RIGHT,
    curses.KEY_UP: keyboard.K_UP,
    curses.KEY_DOWN: keyboard.K_DOWN,
    curses.KEY_PPAGE: keyboard.K_PAGEUP,
    curses.KEY_NPAGE: keyboard.K_PAGEDOWN,
    curses.KEY_ENTER: keyboard.K_CASH,
    curses.KEY_BACKSPACE: keyboard.K_BACKSPACE,
    curses.KEY_DC: keyboard.K_DEL,
    curses.KEY_HOME: keyboard.K_HOME,
    curses.KEY_END: keyboard.K_END,
    curses.KEY_EOL: keyboard.K_EOL,
    curses.ascii.TAB: keyboard.K_TAB,
    1: keyboard.K_HOME, # Ctrl-A
    4: keyboard.K_DEL, # Ctrl-D
    5: keyboard.K_END, # Ctrl-E
    10: keyboard.K_CASH,
    11: keyboard.K_EOL, # Ctrl-K
    15: keyboard.K_QUANTITY, # Ctrl-O
    16: keyboard.K_PRINT, # Ctrl-P
    20: keyboard.K_MANAGETRANS, # Ctrl-T
    24: keyboard.K_CLEAR, # Ctrl-X
    25: keyboard.K_CANCEL, # Ctrl-Y
}

def _curses_keyboard_input():
    """Called by the mainloop whenever data is available on sys.stdin
    """
    i = _stdwin.getch()
    if i == -1:
        return
    if i == curses.KEY_RESIZE:
        # Notify interested code that the screen has resized; NB this
        # doesn't reliably arrive until the next keypress;
        # _curses_keyboard_input() could be installed to handle
        # SIGWINCH as well?
        for f in ui.run_after_resize:
            f()
        return
    if i in kbcodes:
        ui.handle_raw_keyboard_input(kbcodes[i])
    elif curses.ascii.isprint(i):
        ui.handle_raw_keyboard_input(chr(i))

def _init(w):
    """ncurses has been initialised, and calls us with the root window.

    When we leave this function for whatever reason, ncurses will shut
    down and return the display to normal mode.  If we're leaving with
    an exception, ncurses will reraise it.
    """
    global _stdwin
    _stdwin = w
    w.nodelay(1)
    _init_colourpairs()
    ui.beep = curses.beep
    ui.rootwin = curses_window(w)
    ui.header = ui.clockheader(ui.rootwin)
    tillconfig.mainloop.add_fd(sys.stdin.fileno(), _curses_keyboard_input,
                               desc="stdin")
    ui.toaster.notify_display_initialised()
    for i in ui.run_after_init:
        i()
    while tillconfig.mainloop.exit_code is None:
        ui.basicpage._ensure_page_exists()
        _doupdate()
        tillconfig.mainloop.iterate()

def run():
    """Start running with the ncurses display system
    """
    curses.wrapper(_init)
