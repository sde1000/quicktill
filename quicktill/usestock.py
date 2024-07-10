"""Deals with connecting stock items to stock lines."""

from . import ui, td, keyboard, stock, stocklines, user, linekeys
from . import stocktype
from . import config
from .plugins import InstancePluginMount
from .models import StockLine, FinishCode, StockItem, Delivery
from .models import StockAnnotation
import datetime

import logging
log = logging.getLogger(__name__)

clear_stockline_note_on_new_stock = config.BooleanConfigItem(
    'core:clear_stockline_note_on_new_stock', False,
    display_name="Clear stock line note when changing stock",
    description="Should the note on a stock line be cleared automatically "
    "when a new stock item is put on sale on that stock line?")


# The "Use Stock" popup has several different functions:

# For regular stocklines it enables the stock item on sale on the line
# to be changed.

# For display stocklines it enables stock items to be added to the
# line, the display to be re-stocked, stock to be removed, etc.

# For continuous stocklines it allows the stock type to be changed.

class popup(user.permission_checked, ui.keymenu):
    permission_required = ("use-stock", "Allocate stock to lines")

    def __init__(self):
        log.info("Use Stock popup")
        super().__init__(
            [("1", "Re-fill all stock lines", stocklines.restock_all, ()),
             ("2", "Re-fill stock lines in a particular location",
              stocklines.restock_location, ()),
             ("3", "Automatically allocate stock to lines", auto_allocate, ()),
             ],
            blurb=["To select stock for a line, press the appropriate "
                   "line key.", "", "Alternatively, choose one of these "
                   "options:"],
            title="Use Stock")

    def line_chosen(self, kb):
        self.dismiss()
        line_chosen(kb.stockline)

    def keypress(self, k):
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.line_chosen)
        else:
            super().keypress(k)


def line_chosen(line):
    sl = line.stockonsale
    if line.linetype == "regular":
        # We sell directly from a single stock item
        if len(sl) == 0:
            pick_new_stock(
                line, blurb="Select a new stock item to put "
                f"on sale as '{line.name}', or press Clear to leave it "
                "unused.")
        else:
            item = line.stockonsale[0]
            if item.stocktype.stocktake:
                ui.infopopup(
                    [f"You can't remove {item.stocktype.fullname} from sale, "
                     "because it is currently in scope for stock take "
                     f"{item.stocktype.stocktake.contact}.  "
                     "You will be able to remove the item from sale once "
                     "the stock take is complete, or if the stock take "
                     "is abandoned."],
                    title="Can't finish stock",
                    colour=ui.colour_error)
                return
            blurb = [
                f"'{line.name}' is still associated with stock number "
                f"{item.id} ({item.stocktype.fullname}, {item.remaining_units} "
                f"remaining)."]
            fl = [("Stock still ok, will use again later",
                   finish_disconnect, (line, item.id))]
            if item.used / item.size < 0.2:
                blurb += [
                    "", "This item is less than 20% used.  To avoid "
                    "mistakes, you can't tell the till this item "
                    "is finished at this point; you can only take "
                    "it off the stock line and leave it in stock.  "
                    "If it really is finished, you can tell the "
                    "till using the 'Finish stock not currently "
                    "on sale' option on the stock management menu.", ""]
            else:
                sfl = td.s.query(FinishCode).all()
                fl += [(x.description, finish_reason, (line, item.id, x.id))
                       for x in sfl]
                blurb += ["", "Please indicate why you're replacing it:", ""]
            ui.menu(fl, blurb=blurb, title="Finish Stock")
    elif line.linetype == "display":
        stocklines.sanity_check_stock_on_sale(line)
        # Several stock items are listed; stock can be taken from any
        # of them.
        # XXX maybe remove the stocktype from this table, it will be the
        # same for all stock items
        f = ui.tableformatter(' r l r+l ')
        sl = [(f(x.id, x.stocktype.format(), x.ondisplay, x.instock),
               select_display_line_stockitem, (line, x)) for x in sl]
        blurb = ["Press 1 to re-stock this stock line now.", "",
                 "Press 2 to add new stock items to this line.", "",
                 "Alternatively, select a stock item from the list to "
                 "remove it from this line."]
        ui.menu(
            sl, title="{} ({}) - display capacity {}".format(
                line.name, line.location, line.capacity),
            blurb=blurb,
            keymap={
                "1": (stocklines.restock_item, (line.id,), True),
                "2": (add_display_line_stock, (line.id, ), True)})
    elif line.linetype == "continuous":
        change_continuous_stockline(line.id)
    else:
        ui.infopopup(["Confused now"])


def finish_disconnect(line, sn):
    td.s.add(line)
    log.info("Use Stock: disconnected item %d from %s", sn, line.name)
    if clear_stockline_note_on_new_stock() and line.linetype == "regular":
        line.note = ''
    item = td.s.query(StockItem).get(sn)
    td.s.add(StockAnnotation(stockitem=item, atype="stop",
                             text=f"{line.name} (Use Stock disconnect)",
                             user=user.current_dbuser()))
    item.displayqty = None
    item.stockline = None
    td.s.flush()
    pick_new_stock(
        line, f"Stock item {sn} disconnected from {line.name}.  Now select "
        f"a new stock item to put on sale, or press Clear to "
        f"leave the line unused.")


def finish_reason(line, sn, reason):
    td.s.add(line)
    if clear_stockline_note_on_new_stock() and line.linetype == "regular":
        line.note = ''
    stockitem = td.s.query(StockItem).get(sn)
    td.s.add(StockAnnotation(
        stockitem=stockitem, atype="stop",
        text=f"{line.name} (Use Stock reason {reason})",
        user=user.current_dbuser()))
    stockitem.finished = datetime.datetime.now()
    stockitem.finishcode_id = reason
    stockitem.displayqty = None
    stockitem.stockline = None
    td.s.flush()
    log.info("Use Stock: finished item %d reason %s", sn, reason)
    pick_new_stock(line, f"Stock item {sn} is finished.  Now select "
                   f"a new stock item to put on sale on {line.name}, or press "
                   "Clear to leave the line unused.")


def pick_new_stock(line, blurb=""):
    """Pick new stock for a regular stockline.

    This function allows a stock item not currently allocated to any
    stockline to be chosen and added to the specified line.  The blurb
    is displayed before the list of stock items.
    """
    td.s.add(line)
    if line.linetype != "regular":
        log.debug("pick_new_stock called on stockline %d of type %s",
                  line.id, line.linetype)
        return
    # We want to filter by dept, unfinished stock only, exclude stock on sale,
    # and order based on the stocktype/stockline log
    sf = stock.stockfilter(
        department=line.department,
        stocktype_id=line.stocktype_id,
        allow_on_sale=False,
        allow_finished=False,
        stockline_affinity=line,
        sort_descending_stockid=False)
    stock.stockpicker(lambda x: put_on_sale(line, x),
                      title=f"Select Stock Item for {line.name}",
                      filter=sf, check_checkdigits=line.linetype == "regular")


def put_on_sale(line, si):
    # This is used for regular and display stocklines.
    td.s.add(line)
    td.s.add(si)
    log.debug("Use Stock put_on_sale: about to put %s on sale on line %s",
              si, line)
    si.onsale = datetime.datetime.now()
    si.stockline = line
    if line.linetype == "display":
        si.displayqty = si.used
    if clear_stockline_note_on_new_stock() and line.linetype == "regular":
        line.note = ''
    td.s.add(StockAnnotation(stockitem=si, atype='start', text=line.name,
                             user=user.current_dbuser()))
    td.s.flush()
    log.info("Use Stock: item %d (%s) put on sale as %s",
             si.id, si.stocktype.format(), line.name)
    ui.infopopup(["Stock item {} ({}) has been put on sale "
                  "as '{}'.".format(si.id, si.stocktype, line.name)],
                 title="Confirmation",
                 dismiss=keyboard.K_CASH, colour=ui.colour_info)
    if line.linetype == "regular":
        for i in UseStockHook.instances:
            with ui.exception_guard("running the regular_usestock hook"):
                i.regular_usestock(si, line)


def add_display_line_stock(stocklineid):
    """Add stock to a display stock line.

    Given a stock line, find stock to put on it.  (See also
    auto_allocate which finds a stock line to put stock on when given
    stock.)

    Entered from the Use Stock popup for the line or the Modify Stock
    Line popup for the line.
    """
    line = td.s.query(StockLine).get(stocklineid)
    if not line:
        return
    if line.linetype != "display":
        return
    if line.stocktype.stocktake:
        ui.infopopup(["You can't add stock to this stock line at the moment "
                      f"because {line.stocktype} is currently in scope for "
                      f"stock take [{line.stocktype.stocktake.contact}].  "
                      "You will be able to add stock to the stock line "
                      "once the stock take is completed or abandoned."],
                     title="Can't add stock", colour=ui.colour_error)
        return
    new_stock = td.s.query(StockItem)\
                    .join(Delivery)\
                    .filter(Delivery.checked == True)\
                    .filter(StockItem.stockline == None)\
                    .filter(StockItem.stocktype == line.stocktype)\
                    .filter(StockItem.finished == None)\
                    .all()
    other_lines = line.other_lines_same_stocktype()
    if other_lines:
        # There's more than one display stock line with the same stock
        # type.  The user will have to choose stock items
        # individually.
        menu = [(f"{s.id}", put_on_sale, (line, s)) for s in new_stock]
        ui.menu(
            menu, blurb=f"There are multiple display stock lines that "
            f"use {line.stocktype}.  (Other lines: "
            f"{', '.join([l.name for l in other_lines])}.)  Please pick the "
            f"stock item that you want to add to display stock line "
            f"{line.name}.")
    else:
        # This is the only display stock line with this stock type.
        # Pick up all the unallocated stock of this type.
        for s in new_stock:
            s.stockline = line
            s.displayqty = s.used
            td.s.add(StockAnnotation(stockitem=s, atype='start', text=line.name,
                                     user=user.current_dbuser()))
            td.s.flush()
        if new_stock:
            ui.infopopup(
                ["The following stock items were added to {}: {}".format(
                    line.name, ', '.join(str(s.id) for s in new_stock))],
                title=f"Stock added to {line.name}",
                colour=ui.colour_confirm,
                dismiss=keyboard.K_CASH)
        else:
            ui.infopopup(
                [f"There was no stock available to be added to {line.name}."],
                title=f"No stock added to {line.name}",
                colour=ui.colour_confirm,
                dismiss=keyboard.K_CASH)


def select_display_line_stockitem(line, item):
    """Options for an item on a display stockline.

    Present options to the user:
    Enter: Remove stock item from line
    uh, that's it for now; can't think of anything else
    """
    td.s.add(line)
    td.s.add(item)
    ui.infopopup([f"To remove stock item {item.id} ('{item.stocktype}') "
                  f"from {line.name}, press Cash/Enter."],
                 title="Remove stock from line",
                 colour=ui.colour_input,
                 keymap={keyboard.K_CASH: (remove_display_line_stockitem,
                                           (line, item), True)})


def remove_display_line_stockitem(line, item):
    """Remove a stock item from a display stockline.

    If any of it was on display, warn
    the user that the items need to be removed from display.
    """
    td.s.add(line)
    td.s.add(item)
    if item.ondisplay > 0:
        displaynote = \
            f"  Note: The till believes that {item.ondisplay} items need " \
            "to be returned to stock.  Please check carefully!  "
    else:
        displaynote = ""
    item.displayqty = None
    item.stockline = None
    td.s.flush()
    ui.infopopup(
        ["Stock item {} ({}) has been removed from line {}.{}".format(
            item.id, item.stocktype, line.name, displaynote)],
        title="Stock removed from line",
        colour=ui.colour_info, dismiss=keyboard.K_CASH)


class change_continuous_stockline(ui.dismisspopup):
    def __init__(self, stocklineid):
        stockline = td.s.query(StockLine).get(stocklineid)
        if stockline.linetype != "continuous":
            log.error("change_continuous_stockline called on non-continous "
                      "stockline id %s", stocklineid)
            return
        self._stocklineid = stocklineid
        super().__init__(
            9, 75, title=f"Change stock on sale on {stockline.name}",
            colour=ui.colour_input)
        self.win.drawstr(2, 2, 72, f"Current stock type: {stockline.stocktype}")
        self.win.drawstr(4, 2, 16, "New stock type: ", align=">")
        self.stocktypefield = stocktype.stocktypefield(
            4, 18, 54, keymap={keyboard.K_CLEAR: (self.dismiss, ())})
        confirmfield = ui.buttonfield(
            6, 28, 21, "Change stock type",
            keymap={keyboard.K_CASH: (self.confirm, None)})
        ui.map_fieldlist([self.stocktypefield, confirmfield])
        self.stocktypefield.focus()

    def confirm(self):
        new_stocktype = self.stocktypefield.read()
        if not new_stocktype:
            ui.infopopup(["You can't set the stock type to be blank. Choose "
                          "a stock type, even if we don't currently have "
                          "any of it in stock."], title="Error")
            return
        stockline = td.s.query(StockLine).get(self._stocklineid)
        stockline.stocktype = new_stocktype
        self.dismiss()
        ui.infopopup(
            [f"{new_stocktype} is now on sale on the {stockline.name} "
             "stock line."],
            title="Stock type changed", colour=ui.colour_info,
            dismiss=keyboard.K_CASH)


def auto_allocate_internal(deliveryid=None, message_on_no_work=True):
    """Automatically allocate stock to display stock lines.

    Where the same type of stock is being claimed by more than one
    stock line, prompt the user to allocate stock to those lines
    manually.
    """
    log.debug("Start auto_allocate")
    # Find candidate stock
    q = td.s.query(StockItem)\
            .join(Delivery)\
            .filter(StockItem.finished == None)\
            .filter(Delivery.checked == True)\
            .filter(StockItem.stockline == None)
    if deliveryid:
        q = q.filter(Delivery.id == deliveryid)
    stock = q.all()
    # Find candidate stock lines
    stocklines = td.s.query(StockLine)\
                     .filter(StockLine.linetype == "display")\
                     .all()
    # Build dictionary of stocktypes
    st = {}
    for sl in stocklines:
        if sl.stocktype in st:
            st[sl.stocktype].append(sl)
        else:
            st[sl.stocktype] = [sl]
    done = []
    manual = []
    dbu = user.current_dbuser()
    for item in stock:
        if item.stocktype in st:
            if len(st[item.stocktype]) == 1:
                line = st[item.stocktype][0]
                item.stockline = line
                item.displayqty = item.used
                item.onsale = datetime.datetime.now()
                td.s.add(StockAnnotation(
                    stockitem=item, atype="start",
                    text=f"{line.name} (auto-allocate)",
                    user=dbu))
                done.append(item)
            else:
                manual.append(item)
    td.s.flush()
    msg = []
    if done or manual:
        if done:
            msg = msg \
                + ["The following stock items have been allocated to "
                   "display lines:", ""]
            msg = msg + [
                "{} {} -> {}".format(
                    item.id, item.stocktype, item.stockline.name)
                for item in done]
        if done and manual:
            msg = msg + [""]
        if manual:
            msg = msg \
                + ["The following stock items can be allocated to "
                   "display lines, but you must choose which lines "
                   "they go on manually because there is more than "
                   "one possible choice:", ""]
            msg = msg + [
                "{} {} -> {}".format(
                    item.id, item.stocktype,
                    " or ".join(line.name for line in st[item.stocktype]))
                for item in manual]
        ui.infopopup(msg, title="Auto-allocate confirmation",
                     colour=ui.colour_confirm, dismiss=keyboard.K_CASH)
    else:
        if message_on_no_work:
            ui.infopopup(["There was nothing available for automatic "
                          "allocation."],
                         title="Auto-allocate confirmation",
                         colour=ui.colour_confirm, dismiss=keyboard.K_CASH)


auto_allocate = user.permission_required(
    'auto-allocate', 'Automatically allocate stock to lines')(
        auto_allocate_internal)


class UseStockHook(metaclass=InstancePluginMount):
    """Subclass this to be notified of stock being put on sale

    All subclass instances will be called in turn.
    """
    def regular_usestock(self, stockitem, stockline):
        """An item has been put on sale on a regular stockline"""
        pass
