"""
Record waste against a stock item or stock line.

"""

from . import ui,td,keyboard,stock,stocklines,department
from .models import StockItem,StockType,RemoveCode,StockOut
from decimal import Decimal

# There are two types of thing against which waste can be recorded:
# 
# 1. A stock item
# 
# 2. A stock line - this can be either a "regular" stockline or a
# "display" stockline.  If it's regular, we record waste against the
# stock item on it (if there is one), as in (1).  If it's display, we
# record waste against the stock on display.

def popup():
    stocklines.selectline(
        stockline_chosen,blurb="Choose a stock line to record waste against "
        "from the list below, or press a line key.",
        select_none="Choose a stock item instead")

def stockline_chosen(stockline):
    if stockline is None:
        record_item_waste()
    else:
        td.s.add(stockline)
        if stockline.capacity:
            record_line_waste(stockline)
        else:
            if len(stockline.stockonsale)>0:
                record_item_waste(stockline.stockonsale[0])
            else:
                ui.infopopup(["There is nothing on sale on %s."%stockline.name],
                             title="Error")

class record_item_waste(ui.dismisspopup):
    """
    This popup talks the user through the process of recording waste
    against a stock item.  If the stock item is on sale on a "display"
    type stockline, waste is recorded against the amount still in
    stock in that particular item; otherwise it is recorded against
    the item as a whole.  A series of prompts are issued; the Clear
    key will kill the whole window and will not allow backtracking.

    """
    def __init__(self,stockitem=None):
        ui.dismisspopup.__init__(self,10,70,title="Record Waste",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Press stock line key or enter stock number.")
        self.addstr(3,2,"       Stock item:")
        stockfield_km={keyboard.K_CLEAR: (self.dismiss,None),
                       keyboard.K_CASH: (self.stock_enter_key,None)}
        self.stockfield=ui.editfield(3,21,30,validate=ui.validate_int)
        if stockitem: self.stockfield.set(stockitem.id)
        self.stockfield.focus()
    def stock_line(self,kb):
        td.s.add(kb)
        line=kb.stockline
        if line.capacity is None:
            if len(line.stockonsale)==0:
                ui.infopopup(["There is nothing on sale on %s."%line.name],
                             title="Error")
            else:
                self.stockfield.set(str(line.stockonsale[0].id))
                self.stock_enter_key()
            return
        self.isline=True
        self.stocklineid=line.id
        self.name=line.name
        self.ondisplay=line.ondisplay
        if self.ondisplay<1:
            self.dismiss()
            ui.infopopup(
                ["There is no stock on display for '%s'.  If you want to "
                 "record waste against items still in storage, you have "
                 "to enter the stock number instead of pressing the line "
                 "key."%line.name],title="No stock on display")
            return
        self.stockfield.set(line.name)
        self.addstr(4,21,"%d items on display"%self.ondisplay)
        self.create_extra_fields()
    def stock_dept_selected(self,dept):
        sinfo=td.s.query(StockItem).join(StockItem.stocktype).\
            filter(StockItem.finished==None).\
            filter(StockType.dept_id==dept).\
            order_by(StockItem.id).\
            all()
        f=ui.tableformatter(' r l ')
        sl=[(ui.tableline(f,(x.id,x.stocktype.format())),
             self.stock_item_selected,(x.id,)) for x in sinfo]
        ui.menu(sl,title="Select Item",blurb="Select a stock item and press "
                "Cash/Enter.")
    def stock_item_selected(self,stockid):
        self.stockfield.set(str(stockid))
        self.stock_enter_key()
    def stock_enter_key(self):
        if self.stockfield.f=='':
            department.menu(self.stock_dept_selected,"Select Department")
            return
        sn=int(self.stockfield.f)
        sd=td.s.query(StockItem).get(sn)
        if sd is None:
            ui.infopopup(["Stock number %d does not exist."%sn],
                         title="Error")
            return
        if not sd.delivery.checked:
            ui.infopopup(["Stock number %d is part of a delivery that has "
                          "not yet been confirmed.  You can't record waste "
                          "against it until the whole delivery is confirmed."%(
                        sn)],
                         title="Error")
            return
        self.isline=False
        self.sd=sd
        self.addstr(4,21,sd.stocktype.format(maxw=40))
        self.create_extra_fields()
    def create_extra_fields(self):
        self.addstr(5,2,"Waste description:")
        self.addstr(6,2,"    Amount wasted:")
        # XXX all of this needs to be re-done.  We should call a hook
        # from the till config to obtain a suitable list of RemoveCode
        # models.
        #if self.isline:
        #    wastelist=['missing','taste','damaged','ood','freebie']
        #else:
        #    wastelist=['cellar','pullthru','taster','taste','damaged',
        #               'ood','freebie','missing','driptray']
        #wastedict={'pullthru':'Pulled through',
        #           'cellar':'Cellar work',
        #           'taster':'Free taster',
        #           'taste':'Bad taste',
        #           'damaged':'Damaged',
        #           'ood':'Out of date',
        #           'freebie':'Free drink',
        #           'missing':'Gone missing',
        #           'driptray':'Drip tray'}
        wastelist=td.s.query(RemoveCode).filter(RemoveCode.id!='sold').all()
        self.wastedescfield=ui.listfield(
            5,21,30,wastelist,lambda rc:rc.reason,
            keymap={keyboard.K_CLEAR:(self.dismiss,None)})
        self.amountfield=ui.editfield(
            6,21,4,validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish,None)})
        ui.map_fieldlist([self.wastedescfield,self.amountfield])
        if self.isline:
            self.addstr(6,26,'items')
        else:
            self.addstr(6,26,self.sd.stocktype.unit.name+'s')
        self.wastedescfield.set(wastelist[0])
        self.wastedescfield.focus()
    def finish(self):
        waste=self.wastedescfield.read()
        if waste is None or waste=="":
            ui.infopopup(["You must enter a waste description!"],title="Error")
            return
        if self.amountfield.f=="":
            ui.infopopup(["You must enter an amount!"],title="Error")
            return
        amount=Decimal(self.amountfield.f)
        if amount==Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        if self.isline:
            amount=int(amount)
            if amount>self.ondisplay:
                ui.infopopup(["You asked to record waste of %d items, but "
                              "there are only %d on display."%(
                    amount,self.ondisplay)],
                             title="Error")
                return
            sell,unallocated,remaining=stocklines.calculate_sale(
                self.stocklineid,amount)
            for item,qty in sell:
                td.s.add(StockOut(stockitem=item,qty=qty,removecode=waste))
            td.s.flush()
            self.dismiss()
            ui.infopopup(["Recorded %d items against stock line %s."%(
                amount,self.name)],title="Waste Recorded",
                         dismiss=keyboard.K_CASH,colour=ui.colour_info)
        else:
            td.s.add(self.sd)
            td.s.add(StockOut(stockitem=self.sd,qty=amount,removecode=waste))
            # If this is an item on display, we increase displayqty by
            # the amount wasted
            if self.sd.stockline and self.sd.stockline.capacity:
                self.sd.displayqty=self.sd.displayqty_or_zero+int(amount)
            td.s.flush()
            self.dismiss()
            ui.infopopup(["Recorded %0.1f %ss against stock item %d (%s)."%(
                amount,self.sd.stocktype.unit.name,self.sd.id,
                self.sd.stocktype.format())],
                         title="Waste Recorded",dismiss=keyboard.K_CASH,
                         colour=ui.colour_info)

class record_line_waste(ui.dismisspopup):
    """
    This popup talks the user through the process of recording waste
    against a "display" stock line.  Waste is recorded against the
    amount on display on the line.  A series of prompts are issued;
    the Clear key will kill the whole window and will not allow
    backtracking.

    """
    def __init__(self,stockline):
        pass
