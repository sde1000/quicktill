# A keyboard driver is a class that invokes a callback function every
# time a keypress is detected.  It passes either a keycode defined in
# the keyboard module, a keycode not defined in the keyboard module
# (eg. a curses keycode), or a magstripe object.  For every value it
# passes to the callback function it must be willing to return a
# keycap string through the getKeycap function.

# Some keyboard drivers need information to be supplied at UI
# initialisation time (eg. stdwin for the curses keyboard driver).
# This is supplied using the initUI method.

import sys,string,curses
from . import keyboard,magcard,event,ui

class curseskeyboard(object):
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
        20: keyboard.K_MANAGETRANS,
        25: keyboard.K_CANCEL,
        24: keyboard.K_CLEAR,
        }
    def __init__(self):
        self.stdwin=None
        self.callback=None
    def curses_init(self,stdwin):
        event.rdlist.append(self)
        self.stdwin=stdwin
    def fileno(self):
        return sys.stdin.fileno()
    def doread(self):
        i=self.stdwin.getch()
        if i==-1: return
        if i in self.kbcodes: i=self.kbcodes[i]
        ui.handle_keyboard_input(i)

class prehkeyboard(curseskeyboard):
    def __init__(self,kblayout,magstripe={}):
        curseskeyboard.__init__(self)
        self.ibuf=[]
        self.decode=False
        self.card=None
        self.inputs={}
        for loc,code in kblayout:
            self.inputs[loc]=code
        for track in magstripe:
            start,end=magstripe[track]
            # XXX Should be calls to magstripe input handler
            self.inputs[start]=None
            self.inputs[end]=None
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
                    self.handle_input(self.inputs[s])
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
        elif i in self.kbcodes:
            self.handle_input(self.kbcodes[i])
        else:
            self.handle_input(i)
    def handle_input(self,k):
        if k is None:
            # XXX temp ignore magstripe
            return
#        if k==keyboard.K_M1H:
#            self.card=magcard.magstripe()
#            self.card.start_track(1)
#            return
#        if self.card:
#            if k==keyboard.K_M1T:
#                self.card.end_track(1)
#            elif k==keyboard.K_M2H:
#                self.card.start_track(2)
#            elif k==keyboard.K_M2T:
#                self.card.end_track(2)
#            elif k==keyboard.K_M3H:
#                self.card.start_track(3)
#            elif k==keyboard.K_M3T:
#                self.card.end_track(3)
#                ui.handle_keyboard_input(self.card)
#                self.card=None
#            else:
#                self.card.handle_input(k)
#            return
        ui.handle_keyboard_input(k)
