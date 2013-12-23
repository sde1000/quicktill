"""
Record waste against a stock item or stock line.

"""

from . import ui,td,keyboard,stock,stocklines,department,user
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

@user.permission_required('record-waste',"Record waste")
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
    This popup enables the user to record waste against a single stock
    item.
    
    """
    def __init__(self,stockitem=None):
        ui.dismisspopup.__init__(self,10,70,title="Record Waste",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Press stock line key or enter stock number.")
        self.addstr(4,2,"       Stock item:")
        self.addstr(5,2,"Waste description:")
        self.addstr(6,2,"    Amount wasted:")
        self.stockfield=stock.stockfield(4,21,47,keymap={
                keyboard.K_CLEAR: (self.dismiss,None),},
                                         check_checkdigits=True)
        self.stockfield.sethook=self.stockfield_updated
        wastelist=td.s.query(RemoveCode).filter(RemoveCode.id!='sold').all()
        self.wastedescfield=ui.listfield(
            5,21,30,wastelist,lambda rc:rc.reason)
        self.amountfield=ui.editfield(
            6,21,4,validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish,None)})
        ui.map_fieldlist([self.stockfield,self.wastedescfield,self.amountfield])
        if stockitem:
            self.stockfield.set(stockitem)
            self.wastedescfield.focus()
        else:
            self.stockfield.focus()
    def stockfield_updated(self):
        self.addstr(6,26," "*20)
        s=self.stockfield.read()
        if s: self.addstr(6,26,u"%ss"%s.stocktype.unit.name)
    def finish(self):
        item=self.stockfield.read()
        if item is None:
            ui.infopopup(["You must choose a stock item."],title="Error")
            return
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
        td.s.add(item)
        td.s.add(StockOut(stockitem=item,qty=amount,removecode=waste))
        # If this is an item on display, we increase displayqty by
        # the amount wasted
        if item.stockline and item.stockline.capacity:
            item.displayqty=item.displayqty_or_zero+int(amount)
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded %0.1f %ss against stock item %d (%s)."%(
                    amount,item.stocktype.unit.name,item.id,
                    item.stocktype.format())],
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
