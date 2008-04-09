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
        elif k==ord('o') or k==ord('O') or k==keyboard.K_CASH:
            foodorder.popup(self.reporttotal,self.ordernumber)
        else:
            ui.beep()

def commit():
    event.shutdowncode=0

def quit():
    event.shutdowncode=1

if __name__=='__main__':
    import sys,kbdrivers,tillconfig,logging,till,curses,printer
    from pdrivers import pdf,nullprinter

    if len(sys.argv)!=2:
        print "Usage: foodcheck.py menuurl"
        sys.exit(1)

    foodorder.menuurl=sys.argv[1]

    kbdrv=kbdrivers.curseskeyboard()
    tillconfig.kbtype=0

    foodorder.kitchenprinter=nullprinter()
    printer.driver=pdf("xpdf")

    log=logging.getLogger()
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler=logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.ERROR)
    log.addHandler(handler)

    hotkeys={
        ord('c'): commit,
        ord('C'): commit,
        ord('q'): quit,
        ord('Q'): quit,
        }

    pages=[(page,keyboard.K_ALICE,(hotkeys,))]

    try:
        curses.wrapper(till.start,kbdrv,pages)
    except:
        log.exception("Exception caught at top level")
    sys.exit(event.shutdowncode)
