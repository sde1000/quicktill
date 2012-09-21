import time
import ui,event,td,stock,keyboard,usestock,stocklines

class page(ui.basicpage):
    def __init__(self,panel,hotkeys,locations=None):
        ui.basicpage.__init__(self,panel)
        self.display=0
        self.alarm()
        self.redraw()
        self.hotkeys=hotkeys
        self.locations=locations
        event.eventlist.append(self)
    def pagename(self):
        return "Stock Control"
    def drawlines(self):
        sl=td.stockline_summary()
        y=1
        self.addstr(0,0,"Line")
        self.addstr(0,10,"StockID")
        self.addstr(0,18,"Stock")
        self.addstr(0,64,"Used")
        self.addstr(0,70,"Remaining")
        for name,dept,location,stockid in sl:
            if self.locations is None:
                if dept>3: continue # Old behaviour - no location list
            else:
                if location not in self.locations: continue
            self.addstr(y,0,name)
            if stockid is not None:
                sd=td.stock_info([stockid])[0]
                self.addstr(y,10,"%d"%stockid)
                self.addstr(y,18,stock.format_stock(sd,maxw=45))
                self.addstr(y,64,"%0.1f"%sd['used'])
                self.addstr(y,73,"%0.1f"%sd['remaining'])
            y=y+1
            if y>=(self.h-3): break
    def drawstillage(self):
        sl=td.stillage_summary()
        y=1
        self.addstr(0,0,"Loc")
        self.addstr(0,5,"StockID")
        self.addstr(0,13,"Name")
        self.addstr(0,70,"Line")
        for loc,stockid,time,name,line in sl:
            self.addstr(y,0,loc[:5])
            self.addstr(y,5,"%d"%stockid)
            self.addstr(y,13,name)
            if line: self.addstr(y,70,line[:9])
            y=y+1
            if y>=(self.h-3): break
    def redraw(self):
        win=self.win
        win.erase()
        self.addstr(self.h-1,0,"Ctrl+X = Clear; Ctrl+Y = Cancel")
        self.addstr(self.h-2,0,"Press S for stock management.  "
                   "Press U to use stock.  Press R to record waste.")
        self.addstr(self.h-3,0,"Press Enter to refresh display.  "
                   "Press A to add a stock annotation.")
        if self.display==0:
            self.drawlines()
        elif self.display==1:
            self.drawstillage()
    def alarm(self):
        self.nexttime=time.time()+60.0
        self.display=self.display+1
        if self.display>1: self.display=0
        self.redraw()
    def keypress(self,k):
        if k in self.hotkeys: return self.hotkeys[k]()
        elif k==keyboard.K_CASH:
            self.alarm()
        elif k==ord('u') or k==ord('U'):
            stocklines.selectline(usestock.line_chosen,
                                  title="Use Stock",
                                  blurb="Select a stock line",exccap=True)
        else:
            ui.beep()
