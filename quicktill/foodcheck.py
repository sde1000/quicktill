#!/usr/bin/env python

import ui,foodorder,keyboard,event,sys

class page(ui.basicpage):
    def __init__(self,panel,hotkeys):
        ui.basicpage.__init__(self,panel)
        self.display=0
        self.redraw()
        self.hotkeys=hotkeys
    def pagename(self):
        return "Menu Check"
    def redraw(self):
        self.win.erase()
        self.addstr(self.h-1,0,"Ctrl+X = Clear; Ctrl+Y = Cancel")
        self.addstr(self.h-2,0,"Press O to check the menu.  Press C to "
                    "commit the menu.  Press Q to quit.")
    def reporttotal(self,total):
        self.addstr(2,0,(self.w-1)*' ')
        self.addstr(2,0,"Total of order was %0.2f"%total)
    def ordernumber(self):
        return 1234
    def keypress(self,k):
        if k in self.hotkeys: return self.hotkeys[k]()
        elif k==ord('c') or k==ord('C'): event.shutdowncode=0
        elif k==ord('q') or k==ord('Q'): event.shutdowncode=1
        elif k==ord('o') or k==ord('O') or k==keyboard.K_CASH:
            foodorder.popup(self.reporttotal,self.ordernumber)
        else:
            ui.beep()
