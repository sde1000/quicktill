# -*- coding: iso-8859-1 -*-

"""Price lookup window.

"""

import td,ui,keyboard,stock,stocklines,tillconfig

class popup(ui.basicpopup):
    def __init__(self):
        w=78
        h=20
        ui.basicpopup.__init__(self,h,w,title="Price Check",
                               cleartext="Press Cash/Enter to continue",
                               colour=ui.colour_info)
        self.win=self.pan.window()
        self.h=h
        self.w=w
        self.noitem()
    def noitem(self):
        for i in range(2,self.h-1):
            self.win.addstr(i,1,' '*(self.w-2))
        self.win.addstr(2,2,"Press a line key.")
    def singleitem(self,stockid):
        self.noitem()
        lines=stock.stockinfo_linelist(stockid)
        y=4
        for i in lines:
            self.win.addstr(y,2,i)
            y=y+1
            if y==self.h: break
    def multiitem(self,sn):
        self.noitem()
        sinfo=td.stock_info([x[0] for x in sn])
        for a,b in zip(sn,sinfo):
            if a[1] is None: b['displayqty']=0.0
            else: b['displayqty']=a[1]
        lines=ui.table([("%d"%x['stockid'],
                         stock.format_stock(x,maxw=50),
                         "%d"%max(x['displayqty']-x['used'],0),
                         "%d"%(x['size']-max(x['displayqty'],x['used'])),
                         tillconfig.fc(x['saleprice']))
                        for x in sinfo]).format(' r l  r+l r ')
        y=4
        for i in lines:
            self.win.addstr(y,2,i)
            y=y+1
            if y==self.h: break
    def checkline(self,l):
        name,qty,dept,pullthru,menukey,stocklineid,loc,cap=l
        # Fetch list of all stockitems on sale on this line, as (stockid,qty)
        sn=td.stock_onsale(stocklineid)
        if len(sn)==1:
            self.singleitem(sn[0][0])
        elif len(sn)>1:
            self.multiitem(sn)
        else:
            self.noitem()
    def keypress(self,k):
        if k in keyboard.lines:
            stocklines.linemenu(k,self.checkline)
        elif k==keyboard.K_CASH:
            self.dismiss()
        else:
            ui.beep()
