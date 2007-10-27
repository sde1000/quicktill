# -*- coding: iso-8859-1 -*-

"""Price lookup window.  Code from this is also useful for drawing
stock information windows.."""

import td,ui,keyboard,curses

# What do we want to show about a stock item?
# Number
# Manufacturer, name, abv
# Short name
# How much it cost
# How much it sells for
# Delivery information (supplier, date, docid)
# Date first sold
# Date most recently sold
# Date taken off
# Quantity remaining/unaccounted
# Waste, by type
# Finish reason

class stockinfo(ui.basicwin):
    def __init__(self,win,y,x,sn=None):
        self.y=y
        self.x=x
        ui.basicwin.__init__(self,takefocus=False)
        self.win=win
        self.set(sn)
    def set(self,sn,qty=1):
        # Erase the display first...
        y=self.y
        x=self.x
        for i in range(y,y+15):
            self.win.addstr(i,self.x,' '*70)
        if sn is None: return
        sd=td.stock_info(sn)
        sd['stockid']=sn
        sx=td.stock_extrainfo(sn)
        sd.update(sx)
        if sd['abv']: sd['abvstr']=' (%(abv)0.1f%% ABV)'%sd
        else: sd['abvstr']=""
        if qty==1:
            sd['saleunit']=sd['unitname']
        elif qty==0.5:
            sd['saleunit']="half %(unitname)s"%sd
        else: sd['saleunit']="%f %s"%(qty,sd['unitname'])
        sd['deliverydate']=ui.formatdate(sd['deliverydate'])
        sd['bestbefore']=ui.formatdate(sd['bestbefore'])
        sd['firstsale']=ui.formattime(sd['firstsale'])
        sd['lastsale']=ui.formattime(sd['lastsale'])
        self.win.addstr(y+0,x,"%(manufacturer)s %(name)s%(abvstr)s"%sd)
        self.win.addstr(y+1,x,"Sells for £%(saleprice)0.2f/%(unitname)s.  "
                        "%(used)0.1f %(unitname)ss used; "
                        "%(remaining)0.1f %(unitname)ss remaining."%sd)
        self.win.addstr(y+3,x,"Delivered %(deliverydate)s by %(suppliername)s"%sd)
        self.win.addstr(y+4,x,"First sale: %(firstsale)s  Last sale: %(lastsale)s"%sd)
        self.win.addstr(y+5,x,"Best Before %(bestbefore)s"%sd)
        # We need a wastage breakdown here, and finishcode
        y=y+7
        for i in sd['stockout']:
            self.win.addstr(y,x,"%s: %0.1f"%(i[1],i[2]))
            y=y+1

class popup(ui.basicpopup):
    def __init__(self):
        w=78
        h=20
        ui.basicpopup.__init__(self,h,w,title="Price Check",
                               cleartext="Press Cash/Enter to continue",
                               colour=ui.colour_info)
        self.win=self.pan.window()
        self.info=stockinfo(self.win,4,2)
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
