import sys
import os
import array
import termios
import fcntl
import locale
import textwrap
import time
import math
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

class curses_root:
    """Root window with single-line header

    Has a clock at the right-hand side.  Can be passed text for the
    top-left and the middle.  Draws directly on the root window, not
    into a panel.

    "new" method is used to create panels on top of the panel stack.
    """
    supports_fullscreen = False

    def __init__(self, win, left="Quicktill", middle=""):
        self._win = win
        self.left = left
        self.middle = middle
        self._clockalarm()

    def _redraw(self):
        """Draw the header based on the current left and middle text

        The header line consists of the title of the page at the left,
        optionally a summary of what's on other pages in the middle,
        and the clock at the right.  If we do not have enough space,
        we truncate the summary section until we do.  If we still
        don't, we truncate the page name.
        """
        my, mx = self.size()
        m = self.left
        s = self.middle
        t = time.strftime("%a %d %b %Y %H:%M:%S %Z")
        def cat(m, s, t):
            w = len(m) + len(s) + len(t)
            pad1 = (mx - w) // 2
            pad2 = pad1
            if w + pad1 + pad2 != mx:
                pad1 = pad1 + 1
            return ''.join([m, ' ' * pad1, s, ' ' * pad2, t])
        x = cat(m, s, t)
        while len(x) > mx:
            if len(s) > 0:
                s = s[:-1]
            elif len(m) > 0:
                m = m[:-1]
            else:
                t = t[1:]
            x = cat(m, s, t)
        self._win.addstr(0, 0, x.encode(c), _curses_attr(ui.colour_header))

    def update_header(self, left, middle):
        self.left = left
        self.middle = middle
        self._redraw()

    def _clockalarm(self):
        self._redraw()
        now = time.time()
        nexttime = math.ceil(now) + 0.01
        tillconfig.mainloop.add_timeout(nexttime - now, self._clockalarm,
                                        "clock")

    def size(self):
        """Size of screen in characters
        """
        return self._win.getmaxyx()

    def isendwin(self):
        """Has the display been shut down?
        """
        return curses.isendwin()

    def flush(self):
        """Flush pending output to the display immediately
        """
        _doupdate()

    def new(self, height, width, y, x, colour=None, always_on_top=False):
        """Create and return a new window on top of the stack of windows
        """
        if not colour:
            colour = ui.colour_default
        my, mx = self.size()
        if height == "max":
            height = my
        if height == "page":
            height = my - 1
        if width == "max":
            width = mx
        if y == "center":
            y = (my - height) // 2
        if y == "page":
            y = 1
        if x == "center":
            x = (mx - width) // 2
        win = curses.newwin(height, width, y, x)
        pan = curses.panel.new_panel(win)
        cw = curses_window(win, pan, colour=colour, always_on_top=always_on_top)
        pan.set_userptr(cw)
        self._check_on_top()
        win.bkgdset(ord(' '), _curses_attr(colour))
        win.erase()
        return cw

    def set_fullscreen(self, fullscreen):
        """Set whether the display takes the full screen
        """
        # Can't be implemented using ncurses
        return False

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

class window_stack:
    def __init__(self, stack):
        self._stack = stack

    def restore(self):
        for i in self._stack:
            i._pan.show()
        ui.rootwin._check_on_top()

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

    def size(self):
        return self._win.getmaxyx()

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

    def clear(self, y, x, height, width, colour=None):
        """Clear a rectangle to a solid colour
        """
        l = ' ' * width
        for i in range(y, y + height):
            self.addstr(i, x, l, colour)

    def addstr(self, y, x, s, colour=None):
        if colour is None:
            colour = self.colour
        try:
            self._win.addstr(y, x, s.encode(c), _curses_attr(colour))
        except curses.error:
            log.debug("addstr problem: len(s)=%d; s=%s", len(s), repr(s))

    def wrapstr(self, y, x, width, s, colour=None, display=True):
        """Display a string wrapped to specified width.

        Returns the number of lines that the string was wrapped over.
        """
        lines = 0
        for line in s.splitlines():
            if line:
                for wrappedline in textwrap.wrap(line, width):
                    if display:
                        self.addstr(y + lines, x, wrappedline, colour)
                    lines += 1
            else:
                lines += 1
        return lines

    def drawstr(self, y, x, width, s, colour=None, align="<", display=True):
        """Display a string.

        Align may be '<', '^' or '>', as for format specs.  If the
        string does not fit in the specified space, it will be clipped
        to that space and the method will return False; otherwise the
        method will return True.

        Should be called as if it does not clear the background
        (i.e. does not draw the whole width).
        """
        chop = min(0, width - len(s))
        if align == "<":
            if chop:
                s = s[: -chop]
            self.addstr(y, x, s, colour=colour)
        elif align == "^":
            if chop:
                lchop = chop // 2
                rchop = chop - lchop
                s = s[lchop : -rchop]
            self.addstr(y, x, s.center(width), colour=colour)
        else:
            if chop:
                s = s[chop:]
            self.addstr(y, x, s.rjust(width), colour=colour)

    def getyx(self):
        return self._win.getyx()

    def move(self, y, x):
        return self._win.move(y, x)

    def erase(self):
        return self._win.erase()

    def border(self, title=None, clear=None):
        self._win.border()
        if title:
            self.bordertext(title, "U<")
        if clear:
            self.bordertext(clear, "L>")

    def bordertext(self, text, location, colour=None):
        h, w = self.size()
        y = 0 if location[0] == "U" else (h - 1)
        if location[1] == "<":
            x = 1
        elif location[1] == "^":
            x = (w - len(text)) // 2
        else:
            x = w - 1 - len(text)
        self.addstr(y, x, text, colour=colour)

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

def _linux_unblank_screen():
    """Unblank the screen when running on Linux console
    """
    TIOCL_UNBLANKSCREEN = 4
    buf = array.array('b', [TIOCL_UNBLANKSCREEN])
    fcntl.ioctl(sys.stdin, termios.TIOCLINUX, buf)

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
    ui.rootwin = curses_root(w)
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
    if os.uname()[0] == 'Linux':
        if os.getenv('TERM') == 'linux':
            log.info("Running on Linux console: using _linux_unblank_screen")
            ui.unblank_screen = _linux_unblank_screen
        elif os.getenv('TERM') == 'xterm':
            os.putenv('TERM', 'linux')

    curses.wrapper(_init)
