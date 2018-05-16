"""Record waste against a stock item or stock line."""

from . import ui, td, keyboard, stock, stocklines, user
from .models import StockItem, StockType, RemoveCode, StockOut, StockLine
from .models import max_quantity
from decimal import Decimal

# There are two types of thing against which waste can be recorded:
# 
# 1. A stock item
# 
# 2. A stock line - this can be either a "regular" stockline, or a
# "display" or "continuous" stockline.  If it's regular, we record
# waste against the stock item on it (if there is one), as in (1).  If
# it's display or continuous, we record waste against the stock on
# display.

@user.permission_required('record-waste', "Record waste")
def popup():
    stocklines.selectline(
        stockline_chosen, blurb="Choose a stock line to record waste against "
        "from the list below, or press a line key.",
        select_none="Choose a stock item instead")

def stockline_chosen(stockline):
    if stockline is None:
        record_item_waste()
    else:
        td.s.add(stockline)
        if stockline.linetype == "display" \
           or stockline.linetype == "continuous":
            record_line_waste(stockline)
        elif stockline.linetype == "regular":
            if len(stockline.stockonsale) > 0:
                record_item_waste(stockline.stockonsale[0])
            else:
                ui.infopopup(["There is nothing on sale on {}.".format(
                            stockline.name)], title="Error")

class record_item_waste(ui.dismisspopup):
    """Record waste against a single stock item.
    
    The stock item may already be in use by a stock line of any type.
    """
    def __init__(self, stockitem=None):
        ui.dismisspopup.__init__(self, 10, 70, title="Record Waste",
                                 colour=ui.colour_input)
        self.addstr(2, 2, "Press stock line key or enter stock number.")
        self.addstr(4, 2, "       Stock item:")
        self.addstr(5, 2, "Waste description:")
        self.addstr(6, 2, "    Amount wasted:")
        self.stockfield = stock.stockfield(4, 21, 47,keymap={
            keyboard.K_CLEAR: (self.dismiss, None),},
                                           check_checkdigits=True)
        self.stockfield.sethook = self.stockfield_updated
        self.wastedescfield = ui.modellistfield(
            5, 21, 30, RemoveCode,
            lambda q: q.filter(RemoveCode.id != 'sold').order_by(RemoveCode.id),
            lambda rc: rc.reason)
        self.amountfield = ui.editfield(
            6, 21, len(str(max_quantity)) + 1, validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.stockfield, self.wastedescfield,
                          self.amountfield])
        if stockitem:
            self.stockfield.set(stockitem)
            self.wastedescfield.focus()
        else:
            self.stockfield.focus()

    def stockfield_updated(self):
        self.addstr(6, 23 + len(str(max_quantity)), " " * 18)
        s = self.stockfield.read()
        if s:
            self.addstr(6, 23 + len(str(max_quantity)),
                        "{}s".format(s.stocktype.unit.name))

    def finish(self):
        item = self.stockfield.read()
        if item is None:
            ui.infopopup(["You must choose a stock item."], title="Error")
            return
        waste = self.wastedescfield.read()
        if waste is None or waste=="":
            ui.infopopup(["You must enter a waste description!"], title="Error")
            return
        if self.amountfield.f == "":
            ui.infopopup(["You must enter an amount!"], title="Error")
            return
        try:
            amount = Decimal(self.amountfield.f)
        except:
            amount = Decimal(0)
        if amount == Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        if abs(amount) > max_quantity:
            ui.infopopup(
                ["The amount can't be more than {}.".format(max_quantity)],
                title='Error')
            self.amountfield.set("")
            return
        td.s.add(item)
        td.s.add(StockOut(stockitem=item, qty=amount, removecode=waste))
        # If this is an item on display, we increase displayqty by
        # the amount wasted
        if item.stockline and item.stockline.linetype == "display":
            item.displayqty = item.displayqty_or_zero + amount
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded {:0.1f} {}s against stock item {} ({})."
                      .format(amount, item.stocktype.unit.name, item.id,
                              item.stocktype.format())],
                     title="Waste Recorded",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info)

class record_line_waste(ui.dismisspopup):
    """Record waste against a stock line.

    This popup talks the user through the process of recording waste
    against a "display" or "continuous" stock line.  In the case of a
    display stock line, waste is recorded against the amount on
    display on the line.
    """
    def __init__(self, stockline):
        self.stocklineid = stockline.id
        ui.dismisspopup.__init__(self, 9, 70, title="Record Waste",
                                 colour=ui.colour_input)
        self.addstr(2, 2, "       Stock line: {}".format(stockline.name))
        if stockline.linetype == "display":
            self.addstr(3, 2, "Amount on display: {} {}s".format(
                stockline.ondisplay, stockline.stocktype.unit.name))
        else:
            self.addstr(3, 2, "  Amount in stock: {} {}s".format(
                stockline.remaining, stockline.stocktype.unit.name))
        self.addstr(5, 2, "Waste description:")
        self.addstr(6, 2, "    Amount wasted: {} {}s".format(
            ' ' * len(str(max_quantity)),
            stockline.stocktype.unit.name))
        self.wastedescfield = ui.modellistfield(
            5, 21, 30, RemoveCode,
            lambda q: q.filter(RemoveCode.id != 'sold').order_by(RemoveCode.id),
            lambda rc: rc.reason, keymap={
                keyboard.K_CLEAR: (self.dismiss, None),})
        self.amountfield = ui.editfield(
            6, 21, len(str(max_quantity)), validate=ui.validate_positive_float,
            keymap={keyboard.K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.wastedescfield, self.amountfield])
        self.wastedescfield.focus()

    def finish(self):
        stockline = td.s.query(StockLine).get(self.stocklineid)
        waste = self.wastedescfield.read()
        if not waste:
            ui.infopopup(["You must enter a waste description!"], title="Error")
            return
        if self.amountfield.f == "":
            ui.infopopup(["You must enter an amount!"], title="Error")
            return
        try:
            amount = Decimal(self.amountfield.f)
        except:
            amount = Decimal(0)
        if amount == Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        sell, unallocated, remaining = stockline.calculate_sale(amount)
        if unallocated > 0:
            # XXX the grammar in this message isn't ideal...
            ui.infopopup(["There is less than {} {}s on display.".format(
                amount, stockline.sale_stocktype.unit.name)], title="Error")
            self.amountfield.set("")
            return
        if not sell:
            ui.infopopup(["Couldn't record this amount."],
                         title="Error")
            self.amountfield.set("")
            return
        for item, qty in sell:
            if abs(qty) > max_quantity:
                ui.infopopup(["The amount is too large."],
                             title="Error")
                self.amountfield.set("")
                return
        for item, qty in sell:
            td.s.add(StockOut(stockitem=item, removecode=waste, qty=qty))
        td.s.flush()
        self.dismiss()
        ui.infopopup(["Recorded {} {}s against stock line {}.".format(
            amount, stockline.sale_stocktype.unit.name, stockline.name)],
                     title="Waste Recorded",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info)
