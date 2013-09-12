"""Implements the "use stock" menu"""

from . import ui,td,keyboard,stock,stocklines,tillconfig
from .models import StockLine,FinishCode

import logging
log=logging.getLogger()

# The "Use Stock" popup has several different functions:

# For stocklines with no capacity (i.e. sold directly from a stock item) it
# enables the stock item on sale on the line to be changed.

# For stocklines with capacity it enables stock items to be added to
# the line, the display to be re-stocked, stock to be removed, etc.

# There are also menu options to do the following:
# 1) Automatically add stock items to lines (based on stocktype)
# 2) Print a re-stock slip for all stock lines
# 3) Print a re-stock slip for all lines in a particular location

class popup(ui.infopopup):
    def __init__(self):
        log.info("Use Stock popup")
        ui.infopopup.__init__(
            self,["To select stock for a line, press the appropriate "
                  "line key.","","Alternatively, choose one of these options:",
                  "1. Re-fill all stock lines",
                  "2. Re-fill some stock lines",
                  "3. Automatically allocate stock to lines"],
            title="Use Stock",colour=ui.colour_input,
            keymap={keyboard.K_ONE:(stocklines.restock_all,None,True),
                    keyboard.K_TWO:(stocklines.restock_location,None,True),
                    keyboard.K_THREE:(stocklines.auto_allocate,None,True)})
    def line_chosen(self,line):
        self.dismiss()
        line_chosen(line)
    def keypress(self,k):
        if k in keyboard.lines:
            stocklines.linemenu(k,self.line_chosen)
        else:
            ui.infopopup.keypress(self,k)

def line_chosen(line):
    # We get all sorts of strange stuff if we're called from the popup,
    # but XXX let's deal with that later.  Assume for now we're being passed
    # a StockLine.
    sl=line.stockonsale
    if line.capacity is None:
        # We sell directly from a single stock item
        if len(sl)==0:
            pick_new_stock(line,blurb="Select a new stock item to put "
                           "on sale as '%s', or press Clear to leave it "
                           "unused."%(line.name,))
        else:
            finish_stock(line)
    else:
        # Several stock items are listed; stock can be taken from any of them.
        # We need a window with a list of the current stock items, and
        # a blurb that says:
        lines=ui.table([("%d"%x.stockid,
                         x.stockitem.stocktype.format(maxw=39).ljust(40),
                         "%d"%(x.displayqty-x.stockitem.used,),
                         "%d"%(x.stockitem.stockunit.size-x.displayqty))
                        for x in sl]).format(' r l r+l ')
        sl=[(x,select_stockitem,(line,y))
            for x,y in zip(lines,sl)]
        newstockblurb="Pick a stock item to add to %s."%name
        ui.menu(sl,title="%s (%s) - display capacity %d"%
                (name,location,capacity),
                blurb="Press 1 to re-stock this stock line now.  "
                "Press 2 to add a new stock item to this line.  "
                "Alternatively, select a stock item from the list for "
                "options related to that item.",
                keymap={
                keyboard.K_ONE:(stocklines.restock_item,(stocklineid,),True),
                keyboard.K_TWO:(pick_new_stock,(line,newstockblurb),True)})

def finish_stock(line):
    # The line should have exactly one item of stock on sale.  Finish
    # this one.
    onsale=line.stockonsale[0]
    item=onsale.stockitem
    blurb=("'%s' is still associated with stock number %d "
           "(%s, %0.1f %ss remaining).  "%
           (line.name,item.id,item.stocktype.fullname,
            item.remaining,item.stockunit.unit.name))
    fl=[("Stock still ok, will use again later",finish_disconnect,(line,onsale.stockid))]
    if item.used/item.stockunit.size<0.2:
        blurb=(blurb+"This item is less than 20% used.  To avoid mistakes, "
               "you can't tell the till this item is finished at this "
               "point; you can only take it off the stock line and leave "
               "it in stock.  If it really is finished, you can tell the "
               "till using the 'Finish stock not currently on sale' option "
               "on the stock management menu.")
    else:
        sfl=td.s.query(FinishCode).all()
        fl=fl+[(x.description,finish_reason,(line,item.id,x.id)) for x in sfl]
        blurb=blurb+"Please indicate why you're replacing it:"
    ui.menu(fl,blurb=blurb,title="Finish Stock",w=60)

def finish_disconnect(line,sn):
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    log.info("Use Stock: disconnected item %d from %s"%(sn,name))
    td.stock_disconnect(sn)
    pick_new_stock(line,"Stock item %d disconnected from %s.  Now select "
                   "a new stock item to put on sale, or press Clear to "
                   "leave the line unused."%
                   (sn,name))

def finish_reason(line,sn,reason):
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    td.stock_finish(sn,reason)
    log.info("Use Stock: finished item %d reason %s"%(sn,reason))
    pick_new_stock(line,"Stock item %d is finished.  Now select "
                   "a new stock item to put on sale on %s, or press "
                   "Clear to leave the line unused."%(sn,name))

def pick_new_stock(line,blurb=""):
    """This function allows a stock item not currently allocated to any
    stockline to be chosen and added to the specified line.  The blurb
    is displayed before the list of stock items.

    """
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    sl=td.stock_search(dept=dept,stockline=stocklineid)
    sinfo=td.stock_info(sl)
    lines=ui.table([("%d"%x['stockid'],stock.format_stock(x),
                     "%.0f %ss"%(x['remaining'],x['unitname']),
                     ui.formatdate(x['bestbefore']))
                    for x in sinfo]).format(' r l l l ')
    nextfunc=(
        check_checkdigits if tillconfig.checkdigit_on_usestock
        and capacity is None
        else put_on_sale)
    sl=[(x,nextfunc,(line,y['stockid'])) for x,y in zip(lines,sinfo)]
    ui.menu(sl,title="Select Stock Item",blurb=blurb)

class check_checkdigits(ui.dismisspopup):
    def __init__(self,line,sn):
        self.line=line
        self.sn=sn
        ui.dismisspopup.__init__(self,7,40,title="Check stock",
                                 colour=ui.colour_input)
        self.addstr(2,2,'Please enter the check digits from')
        self.addstr(3,2,'the label on stock item %d.'%sn)
        self.addstr(5,2,'Check digits:')
        self.cdfield=ui.editfield(5,16,3,validate=ui.validate_int,keymap={
                keyboard.K_CASH:(self.check,None)})
        self.cdfield.focus()
    def check(self):
        if self.cdfield.f==stock.checkdigits(self.sn):
            self.dismiss()
            put_on_sale(self.line,self.sn)
        else:
            self.cdfield.set('')
            ui.infopopup(["The digits you entered are incorrect.  If the "
                          "item of stock you are trying to put on sale "
                          "does not have a label, you must consult your "
                          "manager before continuing.  Do not sell from "
                          "any item that has no label."],title="Error")

def put_on_sale(line,sn):
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    ok=td.stock_putonsale(sn,stocklineid)
    sdd=td.stock_info([sn])[0]
    sd=stock.format_stock(sdd)
    if ok:
        log.info("Use Stock: item %d (%s) put on sale as %s"%(sn,sd,line))
        ui.infopopup(["Stock item %d (%s) has been put on sale "
                      "as '%s'."%(sn,sd,name)],title="Confirmation",
                     dismiss=keyboard.K_CASH,colour=ui.colour_info)
        # If no location is recorded for the stock item, and the
        # department is number 1 (real ale) then pop up a window
        # asking for the location.  The window will pop up _on top_ of
        # the confirmation box.
        if dept==1 and td.s.query(StockAnnotation).\
                filter(StockAnnotation.stockid==sn).\
                filter(StockAnnotation.atype=='location').count()==0:
            stock.annotate_location(sn)
        tillconfig.usestock_hook(sdd)
    else:
        log.warning("Use Stock: problem putting item %d on line %s"%(sn,name))
        ui.infopopup(["There was an error putting stock item %d (%s) "
                      "on sale as '%s'.  Perhaps you already allocated "
                      "a stock item to this line on another page?"%
                      (sn,sd,line)],title="Error")

def select_stockitem(line,sd):
    """Present options to the user:
    Enter: Remove stock item from line
    uh, that's it for now; can't think of anything else

    """
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    ui.infopopup(["To remove stock item %d ('%s') from %s, press "
                  "Cash/Enter."%(sd['stockid'],stock.format_stock(sd),name)],
                 title="Remove stock from line",
                 colour=ui.colour_input,
                 keymap={keyboard.K_CASH:(remove_stockitem,(line,sd),True)})

def remove_stockitem(line,sd):
    """Remove a stock item from a line.  If any of it was on display, warn
    the user that the items need to be removed from display.

    """
    (name,qty,dept,pullthru,menukey,stocklineid,location,capacity)=line
    td.stock_disconnect(sd['stockid'])
    if (sd['displayqty']-sd['used'])>0:
        displaynote=(
            "  Note: The till believes that %d items need to be "
            "returned to stock.  Please check carefully!  "%(
            max(sd['displayqty']-sd['used'],0)))
    else:
        displaynote=""
    ui.infopopup(["Stock item %d (%s) has been removed from line %s.%s"%(
        sd['stockid'],stock.format_stock(sd),name,displaynote)],
                 title="Stock removed from line",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)
