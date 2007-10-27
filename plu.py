# -*- coding: iso-8859-1 -*-

"""Price lookup window.

"""

import td,ui,keyboard,curses,stock

class popup(ui.basicpopup):
    def __init__(self):
        w=78
        h=20
        ui.basicpopup.__init__(self,h,w,title="Price Check",
                               cleartext="Press Cash/Enter to continue",
                               colour=ui.colour_info)
        self.win=self.pan.window()
        self.info=stock.stockinfo(self.win,4,2)
        self.win.addstr(2,2,"Press a stock key.")
        self.win.move(4,2)
    def checkline(self,l):
        ln=l[0]
        qty=l[1]
        sn=td.stock_onsale(ln)
        self.info.set(sn)
    def keypress(self,k):
        if k in keyboard.lines:
            ui.linemenu(keyboard.lines[k],self.checkline)
        elif k==keyboard.K_CASH:
            self.dismiss()
        else:
            curses.beep()
