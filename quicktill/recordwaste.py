"""Record waste against a stock item or stock line."""

from . import ui, td, keyboard, stock, stocklines, user
from . import linekeys
from .models import StockType, RemoveCode, StockOut, StockLine
from .models import max_quantity
from decimal import Decimal


# There are three types of thing against which waste can be recorded:
#
# 1. A stock item
#
# 2. A stock line - this can be either a "regular" stockline, or a
# "display" or "continuous" stockline.  If it's regular, we record
# waste against the stock item on it (if there is one), as in (1).  If
# it's display or continuous, we record waste against the stock on
# display.
#
# 3. A stock type

def _stockline_menu():
    stocklines.selectline(
        stockline_chosen, blurb="Choose a stock line to record waste against "
        "from the list below.")


class popup(user.permission_checked, ui.keymenu):
    permission_required = ('record-waste', "Record waste")

    def __init__(self):
        super().__init__(
            [("1", "Pick a stock item", record_item_waste, ()),
             ("2", "Select a stock line from a list", _stockline_menu, ()),
             ],
            blurb=["", "Press a line key, scan a barcode, or choose:"],
            title="Record Waste")

    def line_selected(self, kb):
        self.dismiss()
        stockline_chosen(kb.stockline)

    def keypress(self, k):
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.line_selected)
        elif hasattr(k, 'code'):
            if k.binding and k.binding.stockline:
                self.dismiss()
                stockline_chosen(k.binding.stockline)
            elif k.binding and k.binding.stocktype:
                self.dismiss()
                record_stocktype_waste(k.binding.stocktype)
            else:
                ui.beep()
        else:
            super().keypress(k)


def stockline_chosen(stockline):
    if stockline.linetype == "display" \
       or stockline.linetype == "continuous":
        record_line_waste(stockline)
    elif stockline.linetype == "regular":
        if len(stockline.stockonsale) > 0:
            record_item_waste(stockline.stockonsale[0])
        else:
            ui.infopopup(
                [f"There is nothing on sale on {stockline.name}."],
                title="Error")


class record_item_waste(ui.dismisspopup):
    """Record waste against a single stock item.

    The stock item may already be in use by a stock line of any type.
    """
    def __init__(self, stockitem=None):
        super().__init__(10, 70, title="Record Waste",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 66,
                         "Press stock line key or enter stock number.")
        self.win.drawstr(4, 2, 19, "Stock item: ", align=">")
        self.win.drawstr(5, 2, 19, "Waste description: ", align=">")
        self.win.drawstr(6, 2, 19, "Amount wasted: ", align=">")
        self.stockfield = stock.stockfield(
            4, 21, 47, keymap={
                keyboard.K_CLEAR: (self.dismiss, None),
            },
            check_checkdigits=True)
        self.stockfield.sethook = self.stockfield_updated
        self.wastedescfield = ui.modellistfield(
            5, 21, 30, RemoveCode,
            lambda q: q.filter(RemoveCode.id != 'sold').order_by(RemoveCode.id),
            lambda rc: rc.reason)
        self.amountfield = ui.editfield(
            6, 21, len(str(max_quantity)) + 1, validate=ui.validate_float,
            keymap={keyboard.K_CASH: (self.finish, None)})
        self.unitlabel = ui.label(6, 23 + len(str(max_quantity)),
                                  68 - 23 - len(str(max_quantity)))
        ui.map_fieldlist([self.stockfield, self.wastedescfield,
                          self.amountfield])
        if stockitem:
            self.stockfield.set(stockitem)
            self.wastedescfield.focus()
        else:
            self.stockfield.focus()

    def stockfield_updated(self):
        s = self.stockfield.read()
        if s:
            self.unitlabel.set(f"{s.stocktype.unit.name}s")
        else:
            self.unitlabel.set("")

    def finish(self):
        item = self.stockfield.read()
        if item is None:
            ui.infopopup(["You must choose a stock item."], title="Error")
            return
        waste = self.wastedescfield.read()
        if waste is None or waste == "":
            ui.infopopup(["You must enter a waste description!"],
                         title="Error")
            return
        if self.amountfield.f == "":
            ui.infopopup(["You must enter an amount!"], title="Error")
            return
        try:
            amount = Decimal(self.amountfield.f)
        except Exception:
            amount = Decimal(0)
        if amount == Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        if abs(amount) > max_quantity:
            ui.infopopup(
                [f"The amount can't be more than {max_quantity}."],
                title='Error')
            self.amountfield.set("")
            return
        td.s.add(item)
        td.s.add(StockOut(stockitem=item, qty=amount, removecode=waste))
        # If this is an item on display, we increase displayqty by
        # the amount wasted
        if item.stockline and item.stockline.linetype == "display":
            item.displayqty = item.displayqty_or_zero + amount
        user.log(f"Recorded {item.stocktype.unit.format_sale_qty(amount)} "
                 f"{waste} against stock item {item.logref}.")
        td.s.flush()
        self.dismiss()
        ui.infopopup(
            [f"Recorded {item.stocktype.unit.format_sale_qty(amount)} "
             f"against stock item {item.id} ({item.stocktype})."],
            title="Waste Recorded", dismiss=keyboard.K_CASH,
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
        super().__init__(9, 70, title="Record Waste", colour=ui.colour_input)
        self.win.drawstr(2, 2, 19, "Stock line: ", align=">")
        self.win.drawstr(2, 21, 47, stockline.name)
        if stockline.linetype == "display":
            self.win.drawstr(3, 2, 19, "Amount on display: ", align=">")
            self.win.drawstr(3, 21, 47, f"{stockline.ondisplay} "
                             f"{stockline.stocktype.unit.name}s")
        else:
            self.win.drawstr(3, 2, 19, "Amount in stock: ", align=">")
            self.win.drawstr(3, 21, 47, stockline.remaining_str)
        self.win.drawstr(5, 2, 19, "Waste description: ", align=">")
        self.win.drawstr(6, 2, 19, "Amount wasted: ", align=">")
        self.win.drawstr(6, 22 + len(str(max_quantity)),
                         68 - 22 - len(str(max_quantity)),
                         f"{stockline.stocktype.unit.name}s")
        self.wastedescfield = ui.modellistfield(
            5, 21, 30, RemoveCode,
            lambda q: q.filter(RemoveCode.id != 'sold').order_by(RemoveCode.id),
            lambda rc: rc.reason, keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
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
        except Exception:
            amount = Decimal(0)
        if amount == Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        sell, unallocated, remaining = stockline.calculate_sale(amount)
        if unallocated > 0:
            ui.infopopup(
                [f"There is less than "
                 f"{stockline.sale_stocktype.unit.format_sale_qty(amount)} "
                 f"on display."],
                title="Error")
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
        user.log(
            f"Recorded {stockline.sale_stocktype.unit.format_sale_qty(amount)} "
            f"{waste} against stock line {stockline.logref}.")
        td.s.flush()
        self.dismiss()
        ui.infopopup(
            [f"Recorded "
             f"{stockline.sale_stocktype.unit.format_sale_qty(amount)} "
             f"against stock line {stockline.name}."],
            title="Waste Recorded", dismiss=keyboard.K_CASH,
            colour=ui.colour_info)


class record_stocktype_waste(ui.dismisspopup):
    """Record waste against a stock type.
    """
    def __init__(self, stocktype):
        self.stocktypeid = stocktype.id
        super().__init__(9, 70, title="Record Waste", colour=ui.colour_input)
        self.win.drawstr(2, 2, 19, "Stock type: ", align=">")
        self.win.drawstr(2, 21, 47, format(stocktype))
        self.win.drawstr(3, 2, 19, "Amount in stock: ", align=">")
        self.win.drawstr(3, 21, 47, stocktype.remaining_str)
        self.win.drawstr(5, 2, 19, "Waste description: ", align=">")
        self.win.drawstr(6, 2, 19, "Amount wasted: ", align=">")
        self.win.drawstr(6, 22 + len(str(max_quantity)),
                         68 - 22 - len(str(max_quantity)),
                         f"{stocktype.unit.name}s")
        self.wastedescfield = ui.modellistfield(
            5, 21, 30, RemoveCode,
            lambda q: q.filter(RemoveCode.id != 'sold').order_by(RemoveCode.id),
            lambda rc: rc.reason, keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.amountfield = ui.editfield(
            6, 21, len(str(max_quantity)), validate=ui.validate_positive_float,
            keymap={keyboard.K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.wastedescfield, self.amountfield])
        self.wastedescfield.focus()

    def finish(self):
        stocktype = td.s.query(StockType).get(self.stocktypeid)
        waste = self.wastedescfield.read()
        if not waste:
            ui.infopopup(["You must enter a waste description!"], title="Error")
            return
        if self.amountfield.f == "":
            ui.infopopup(["You must enter an amount!"], title="Error")
            return
        try:
            amount = Decimal(self.amountfield.f)
        except Exception:
            amount = Decimal(0)
        if amount == Decimal(0):
            ui.infopopup(["You must enter an amount other than zero!"],
                         title='Error')
            self.amountfield.set("")
            return
        sell, unallocated, remaining = stocktype.calculate_sale(amount)
        if unallocated > 0:
            ui.infopopup(
                [f"There is less than {amount} {stocktype.unit.name}s "
                 "in stock."], title="Error")
            self.amountfield.set("")
            return
        if not sell:
            ui.infopopup(["Couldn't record this amount."], title="Error")
            self.amountfield.set("")
            return
        for item, qty in sell:
            if abs(qty) > max_quantity:
                ui.infopopup(["The amount is too large."], title="Error")
                self.amountfield.set("")
                return
        for item, qty in sell:
            td.s.add(StockOut(stockitem=item, removecode=waste, qty=qty))
        user.log(f"Recorded {amount} {stocktype.unit.name}s {waste} against "
                 f"{stocktype.logref}.")
        td.s.flush()
        self.dismiss()
        ui.infopopup(
            [f"Recorded {amount} {stocktype.unit.name}s against {stocktype}."],
            title="Waste Recorded", dismiss=keyboard.K_CASH,
            colour=ui.colour_info)
