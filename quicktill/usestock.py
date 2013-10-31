"""Implements the "use stock" menu"""

from . import ui,td,keyboard,stock,stocklines,tillconfig
from .models import StockLine,FinishCode,StockItem
from .models import StockType,StockAnnotation
import datetime

import logging
log=logging.getLogger(__name__)

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
    def line_chosen(self,kb):
        self.dismiss()
        td.s.add(kb)
        line_chosen(kb.stockline)
    def keypress(self,k):
        if hasattr(k,'line'):
            stocklines.linemenu(k,self.line_chosen)
        else:
            ui.infopopup.keypress(self,k)

def line_chosen(line):
    td.s.add(line)
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
        f=ui.tableformatter(' r l r+l ')
        sl=[(ui.tableline(
                    f,(x.id,x.stocktype.format(),x.ondisplay,x.instock)),
             select_stockitem,(line,x)) for x in sl]
        newstockblurb="Pick a stock item to add to %s."%line.name
        ui.menu(sl,title="%s (%s) - display capacity %d"%
                (line.name,line.location,line.capacity),
                blurb="Press 1 to re-stock this stock line now.  "
                "Press 2 to add a new stock item to this line.  "
                "Alternatively, select a stock item from the list for "
                "options related to that item.",
                keymap={
                keyboard.K_ONE:(stocklines.restock_item,(line,),True),
                keyboard.K_TWO:(pick_new_stock,(line,newstockblurb),True)})

def finish_stock(line):
    # The line should have exactly one item of stock on sale.  Finish
    # this one.
    item=line.stockonsale[0]
    blurb=("'%s' is still associated with stock number %d "
           "(%s, %0.1f %ss remaining).  "%
           (line.name,item.id,item.stocktype.fullname,
            item.remaining,item.stockunit.unit.name))
    fl=[("Stock still ok, will use again later",finish_disconnect,(line,item.id))]
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
    ui.menu(fl,blurb=blurb,title="Finish Stock")

def finish_disconnect(line,sn):
    td.s.add(line)
    log.info("Use Stock: disconnected item %d from %s"%(sn,line.name))
    item=td.s.query(StockItem).get(sn)
    item.displayqty=None
    item.stocklineid=None
    td.s.flush()
    pick_new_stock(line,"Stock item %d disconnected from %s.  Now select "
                   "a new stock item to put on sale, or press Clear to "
                   "leave the line unused."%
                   (sn,line.name))

def finish_reason(line,sn,reason):
    td.s.add(line)
    stockitem=td.s.query(StockItem).get(sn)
    stockitem.finished=datetime.datetime.now()
    stockitem.finishcode_id=reason
    stockitem.displayqty=None
    stockitem.stocklineid=None
    td.s.flush()
    log.info("Use Stock: finished item %d reason %s"%(sn,reason))
    pick_new_stock(line,"Stock item %d is finished.  Now select "
                   "a new stock item to put on sale on %s, or press "
                   "Clear to leave the line unused."%(sn,line.name))

def pick_new_stock(line,blurb=""):
    """This function allows a stock item not currently allocated to any
    stockline to be chosen and added to the specified line.  The blurb
    is displayed before the list of stock items.

    """
    td.s.add(line)
    # We want to filter by dept, unfinished stock only, exclude stock on sale,
    # and order based on the stocktype/stockline log
    sinfo=td.s.query(StockItem).join(StockType).\
        filter(StockItem.finished==None).\
        filter(StockItem.stockline==None).\
        filter(StockType.department==line.department).\
        order_by(StockItem.id).\
        all()
    # The relevant part of the original code for ordering by stocktype/line log
    # is:
    #    order="(s.stocktype IN (SELECT stocktype FROM stockline_stocktype_log stl WHERE stl.stocklineid=%d)) DESC,s.stockid"%stockline

    nextfunc=(
        check_checkdigits if tillconfig.checkdigit_on_usestock
        and line.capacity is None
        else put_on_sale)
    f=ui.tableformatter(' r l l l ')
    sl=[(ui.tableline(f,(x.id,x.stocktype.format(),x.remaining_units,
                         ui.formatdate(x.bestbefore))),
         nextfunc,(line,x.id)) for x in sinfo]
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
        s=td.s.query(StockItem).get(self.sn)
        if self.cdfield.f==s.checkdigits:
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
    td.s.add(line)
    si=td.s.query(StockItem).get(sn)
    si.onsale=datetime.datetime.now()
    si.stockline=line
    td.s.add(StockAnnotation(stockitem=si,atype='start',text=line.name))
    td.s.flush()
    log.info("Use Stock: item %d (%s) put on sale as %s"%(
            si.id,si.stocktype.format(),line.name))
    ui.infopopup(["Stock item %d (%s) has been put on sale "
                  "as '%s'."%(si.id,si.stocktype.format(),line.name)],
                 title="Confirmation",
                 dismiss=keyboard.K_CASH,colour=ui.colour_info)
    # If no location is recorded for the stock item, and the
    # department is number 1 (real ale) then pop up a window
    # asking for the location.  The window will pop up _on top_ of
    # the confirmation box.
    # XXX this is IPL-specific code and should be removed!
    if line.dept_id==1 and td.s.query(StockAnnotation).\
            filter(StockAnnotation.stockid==sn).\
            filter(StockAnnotation.atype=='location').count()==0:
        stock.annotate_location(sn)
    if line.capacity is None:
        tillconfig.usestock_hook(si,line) # calling convention changed!

def select_stockitem(line,item):
    """Present options to the user:
    Enter: Remove stock item from line
    uh, that's it for now; can't think of anything else

    """
    td.s.add(line)
    td.s.add(item)
    ui.infopopup(["To remove stock item %d ('%s') from %s, press "
                  "Cash/Enter."%(item.id,item.stocktype.format(),line.name)],
                 title="Remove stock from line",
                 colour=ui.colour_input,
                 keymap={keyboard.K_CASH:(remove_stockitem,(line,item),True)})

def remove_stockitem(line,item):
    """Remove a stock item from a line.  If any of it was on display, warn
    the user that the items need to be removed from display.

    """
    td.s.add(line)
    td.s.add(item)
    if item.ondisplay>0:
        displaynote=(
            "  Note: The till believes that %d items need to be "
            "returned to stock.  Please check carefully!  "%item.ondisplay)
    else:
        displaynote=""
    item.displayqty=None
    item.stocklineid=None
    td.s.flush()
    ui.infopopup(["Stock item %d (%s) has been removed from line %s.%s"%(
        item.id,item.stocktype.format(),line.name,displaynote)],
                 title="Stock removed from line",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)
