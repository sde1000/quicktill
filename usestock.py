"""Implements the "use stock" menu"""

import ui,td,keyboard,stock

import logging
log=logging.getLogger()

# The "Use Stock" popup is for a quick change in the middle of a
# session.  It asks the necessary questions, and then gets out of the
# way.

# 1) Which line are we dealing with?
# 2) (If necessary) What do you want to do with the stock currently on the line?
# 3) Which stock do you want to put on the line?

class pickline(ui.infopopup):
    def __init__(self,func):
        ui.infopopup.__init__(
            self,["Press the line key that you want to connect "
                  "to a stock item..."],title="Use Stock",
            colour=ui.colour_input)
        self.func=func
    def line_chosen(self,line):
        self.dismiss()
        self.func(line)
    def keypress(self,k):
        if k in keyboard.lines:
            ui.linemenu(keyboard.lines[k],self.line_chosen)
        else:
            ui.infopopup.keypress(self,k)

def line_chosen(l):
    sn=td.stock_onsale(l[0])
    if sn is None:
        pick_new_stock(l)
    else:
        finish_stock(l,sn)

def finish_stock(l,sn):
    sd=td.stock_info(sn)
    fl=[("Stock still ok, will use again later",finish_disconnect,(l,sn))]
    fl=fl+[(x[1],finish_reason,(l,sn,x[0])) for x in td.stockfinish_list()]
    ui.menu(fl,blurb="'%s' is still associated with stock number %d "
            "(%s %s, %0.1f %ss remaining).  "
            "Please indicate why you're replacing it:"%
            (l[0],sn,sd['manufacturer'],sd['name'],sd['remaining'],sd['unitname']),
            title="Finish Stock",w=60)

def finish_disconnect(l,sn):
    log.info("Use Stock: disconnected item %d"%sn)
    td.stock_disconnect(sn)
    pick_new_stock(l,"Stock item %d disconnected from %s.  "%
                   (sn,l[0]))

def finish_reason(l,sn,reason):
    td.stock_finish(sn,reason)
    log.info("Use Stock: finished item %d reason %s"%(sn,reason))
    pick_new_stock(l,"Stock item %d is finished.  "%(sn))

def pick_new_stock(line,blurb=""):
    def fs(sn):
        sd=td.stock_info(sn)
        return "%7d %s"%(sn,stock.stock_description(sn))
    sl=td.stock_search(line[2])
    sl=[(fs(x),put_on_sale,(line[0],x)) for x in sl]
    ui.menu(sl,title="Select Stock Item",
            blurb=blurb+"Select a new stock item to put on sale as '%s', "
            "or press Clear to leave it unused."%line[0])

def put_on_sale(line,sn):
    ok=td.stock_putonsale(sn,line)
    sd=stock.stock_description(sn)
    if ok:
        log.info("Use Stock: item %d (%s) put on sale as %s"%(sn,sd,line))
        ui.infopopup(["Stock item %d (%s) has been put on sale "
                      "as '%s'."%(sn,sd,line)],title="Confirmation",
                     dismiss=keyboard.K_CASH,colour=ui.colour_info)
    else:
        log.error("Use Stock: error putting item %d on line %s"%(sn,line))
        ui.infopopup(["There was an error putting stock item %d (%s) "
                      "on sale as '%s'.  Perhaps you already allocated "
                      "a stock item to this line on another page?"%
                      (sn,sd,line)],title="Error")

def popup():
    log.info("Use Stock popup")
    pickline(line_chosen)
