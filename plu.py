# -*- coding: iso-8859-1 -*-

"""Price lookup window.

"""

import td,ui,keyboard,curses,stock,stocklines

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
        name,qty,dept,pullthru,menukey,stocklineid,loc,cap=l
        # Fetch list of all stockitems on sale on this line, as (stockid,qty)
        sn=td.stock_onsale(stocklineid)
        if len(sn)>0:
            self.info.set(sn[0][0])
        else:
            self.info.set(None)
    def keypress(self,k):
        if k in keyboard.lines:
            stocklines.linemenu(k,self.checkline)
        elif k==keyboard.K_CASH:
            self.dismiss()
        else:
            curses.beep()
