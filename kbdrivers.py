# A keyboard driver is a class that invokes a callback function every
# time a keypress is detected.  It passes either a keycode defined in
# the keyboard module, a keycode not defined in the keyboard module
# (eg. a curses keycode), or a magstripe object.  For every value it
# passes to the callback function it must be willing to return a
# keycap string through the getKeycap function.

# Some keyboard drivers need information to be supplied at UI
# initialisation time (eg. stdwin for the curses keyboard driver).
# This is supplied using the initUI method.

import curses,keyboard,magcard,event,sys,string

class curseskeyboard:
    # curses codes and their till keycode equivalents
    kbcodes={
        curses.KEY_LEFT: keyboard.K_LEFT,
        curses.KEY_RIGHT: keyboard.K_RIGHT,
        curses.KEY_UP: keyboard.K_UP,
        curses.KEY_DOWN: keyboard.K_DOWN,
        ord('1'): keyboard.K_ONE,
        ord('2'): keyboard.K_TWO,
        ord('3'): keyboard.K_THREE,
        ord('4'): keyboard.K_FOUR,
        ord('5'): keyboard.K_FIVE,
        ord('6'): keyboard.K_SIX,
        ord('7'): keyboard.K_SEVEN,
        ord('8'): keyboard.K_EIGHT,
        ord('9'): keyboard.K_NINE,
        ord('0'): keyboard.K_ZERO,
        ord('.'): keyboard.K_POINT,
        curses.KEY_ENTER: keyboard.K_CASH,
        10: keyboard.K_CASH,
        15: keyboard.K_QUANTITY,
        16: keyboard.K_PRINT,
        25: keyboard.K_CANCEL,
        24: keyboard.K_CLEAR,
        }
    # The values returned by curses.keyname() aren't always suitable for
    # display.  We have some overrides here for keys that we actually use.
    keycaps={
        keyboard.K_CASH: 'Cash/Enter',
        keyboard.K_CLEAR: 'Clear',
        keyboard.K_CANCEL: 'Cancel',
        keyboard.K_PRINT: 'Print',
        keyboard.K_UP: 'Up',
        keyboard.K_DOWN: 'Down',
        keyboard.K_LEFT: 'Left',
        keyboard.K_RIGHT: 'Right',
        keyboard.K_ZERO: '0',
        keyboard.K_ONE: '1',
        keyboard.K_TWO: '2',
        keyboard.K_THREE: '3',
        keyboard.K_FOUR: '4',
        keyboard.K_FIVE: '5',
        keyboard.K_SIX: '6',
        keyboard.K_SEVEN: '7',
        keyboard.K_EIGHT: '8',
        keyboard.K_NINE: '9',
        keyboard.K_POINT: '.',
        curses.KEY_PPAGE: 'Page Up',
        curses.KEY_NPAGE: 'Page Down',
        curses.KEY_DC: 'Del',
        curses.KEY_BACKSPACE: 'Backspace',
        curses.KEY_F1: 'F1',
        curses.KEY_F2: 'F2',
        curses.KEY_F3: 'F3',
        curses.KEY_F4: 'F4',
        curses.KEY_F5: 'F5',
        curses.KEY_F6: 'F6',
        curses.KEY_F7: 'F7',
        curses.KEY_F8: 'F8',
        curses.KEY_F9: 'F9',
        curses.KEY_F10: 'F10',
        curses.KEY_F11: 'F11',
        curses.KEY_F12: 'F12',
        curses.KEY_IC: 'Insert',
        9: 'Tab',
        }
    def __init__(self):
        self.stdwin=None
        self.callback=None
    def initUI(self,callback,stdwin):
        event.rdlist.append(self)
        self.callback=callback
        self.stdwin=stdwin
    def fileno(self):
        return sys.stdin.fileno()
    def doread(self):
        i=self.stdwin.getch()
        if i==-1: return
        if i in self.kbcodes: i=self.kbcodes[i]
        self.callback(i)
    def keycap(self,k):
        if k in self.keycaps: return self.keycaps[k]
        return curses.keyname(k)

class prehkeyboard(curseskeyboard):
    def __init__(self,kblayout):
        curseskeyboard.__init__(self)
        self.ibuf=[]
        self.decode=False
        self.card=None
        self.inputs={}
        self.codes={}
        for loc,cap,code in kblayout:
            x=[loc,cap,code]
            self.inputs[loc]=x
            self.codes[code]=x
    def setkeycap(self,code,cap):
        """Tries to update the keycap for the specified key.  Returns
        True if successful, or False if the key does not exist.

        """
        try:
            self.codes[code][1]=cap
            return True
        except:
            return False
    def keycap(self,k):
        if isinstance(k,magcard.magstripe): return str(k)
        if k in self.codes: return self.codes[k][1]
        return curseskeyboard.keycap(self,k)
    def doread(self):
        def pass_on_buffer():
            self.handle_input(ord('['))
            for i in self.ibuf:
                self.handle_input(i)
            self.decode=False
            self.ibuf=[]
        i=self.stdwin.getch()
        if i==-1: return
        if self.decode:
            if i==ord(']'):
                s=string.join([chr(x) for x in self.ibuf],'')
                if s in self.inputs:
                    self.handle_input(self.inputs[s][2])
                    self.decode=False
                    self.ibuf=[]
                else:
                    pass_on_buffer()
                    self.handle_input(ord(']'))
            else:
                self.ibuf.append(i)
                if len(self.ibuf)>3:
                    pass_on_buffer()
        elif i==ord('['):
            self.decode=True
        else:
            self.handle_input(i)
    def handle_input(self,k):
        if k==keyboard.K_M1H:
            self.card=magcard.magstripe()
            self.card.start_track(1)
            return
        if self.card:
            if k==keyboard.K_M1T:
                self.card.end_track(1)
            elif k==keyboard.K_M2H:
                self.card.start_track(2)
            elif k==keyboard.K_M2T:
                self.card.end_track(2)
            elif k==keyboard.K_M3H:
                self.card.start_track(3)
            elif k==keyboard.K_M3T:
                self.card.end_track(3)
                self.callback(self.card)
                self.card=None
            else:
                self.card.handle_input(k)
            return
        if k in self.kbcodes: k=self.kbcodes[k]
        self.callback(k)

