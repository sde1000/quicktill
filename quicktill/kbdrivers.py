import sys
import string
import curses
import hashlib
import logging
from . import keyboard, event, ui, td, user
log = logging.getLogger(__name__)

class curseskeyboard(object):
    # curses codes and their till keycode equivalents
    kbcodes = {
        curses.KEY_LEFT: keyboard.K_LEFT,
        curses.KEY_RIGHT: keyboard.K_RIGHT,
        curses.KEY_UP: keyboard.K_UP,
        curses.KEY_DOWN: keyboard.K_DOWN,
        curses.KEY_ENTER: keyboard.K_CASH,
        curses.KEY_BACKSPACE: keyboard.K_BACKSPACE,
        curses.KEY_DC: keyboard.K_DEL,
        curses.KEY_HOME: keyboard.K_HOME,
        curses.KEY_END: keyboard.K_END,
        curses.KEY_EOL: keyboard.K_EOL,
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
    def __init__(self):
        self.stdwin = None
    def curses_init(self, stdwin):
        event.rdlist.append(self)
        self.stdwin = stdwin
    def fileno(self):
        return sys.stdin.fileno()
    def _curses_to_internal(self, i):
        if i in self.kbcodes:
            return self.kbcodes[i]
        elif curses.ascii.isprint(i):
            return chr(i)
    def doread(self):
        i = self.stdwin.getch()
        if i == -1:
            return
        self.handle_input(self._curses_to_internal(i))
    def handle_input(self, k):
        with td.orm_session():
            ui.handle_keyboard_input(k)

class magstripecode(object):
    """
    A keycode used to indicate the start or end of a magstripe card track.

    """
    def __init__(self, code):
        self.magstripe = code

class prehkeyboard(curseskeyboard):
    def __init__(self, kblayout, magstripe=None):
        curseskeyboard.__init__(self)
        self.ibuf = [] # Sequence of characters received after a '['
        self.decode = False # Are we reading into ibuf at the moment?
        self.inputs = {}
        for loc, code in kblayout:
            self.inputs[loc.upper()] = code
        if magstripe:
            for start, end in magstripe:
                self.inputs[start] = magstripecode(start)
                self.inputs[end] = magstripecode(end)
            self.finishmagstripe = end
        self.magstripe = None # Magstripe read in progress if not-None
    def _pass_on_buffer(self):
        self._handle_decoded_input('[')
        for i in self.ibuf:
            self._handle_decoded_input(i)
        self.decode = False
        self.ibuf = []
    def handle_input(self, k):
        # We get a string or internal keycode.  We interpret these
        # further, then pass them to the parent class's handle_input
        # method.
        if self.decode:
            if k == ']':
                s = ''.join(self.ibuf)
                if s.upper() in self.inputs:
                    self.decode=False
                    self.ibuf=[]
                    self._handle_decoded_input(self.inputs[s.upper()])
                else:
                    self._pass_on_buffer()
                    self._handle_decoded_input(']')
            elif isinstance(k, str):
                self.ibuf.append(k)
            else:
                self._pass_on_buffer()
                self._handle_decoded_input(k)
            if len(self.ibuf) > 3:
                self._pass_on_buffer()
        elif k == '[':
            self.decode=True
        else:
            self._handle_decoded_input(k)
    def _handle_decoded_input(self, k):
        if hasattr(k, 'magstripe'):
            # It was one of the magstripe codes.
            if self.magstripe is None:
                self.magstripe = []
            if k.magstripe == self.finishmagstripe:
                log.debug("Magstripe '%s'", self.magstripe)
                if "BadRead" in self.magstripe:
                    self.magstripe = None
                    return
                k = user.token(
                    "magstripe:" + hashlib.sha1(
                        ''.join(self.magstripe)).hexdigest()[:16])
                self.magstripe = None
        if self.magstripe is not None and isinstance(k, str):
            self.magstripe.append(k)
        else:
            super(prehkeyboard, self).handle_input(k)
