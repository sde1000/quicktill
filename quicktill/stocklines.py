import logging
from . import keyboard, ui, td, printer, user, linekeys, modifiers
from . import stocktype
from . import tillconfig
from .models import Department, StockLine, KeyboardBinding
from .models import StockType, StockLineTypeLog
from sqlalchemy.sql import select
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
log = logging.getLogger(__name__)


def restock_list(stockline_list):
    # Print out list of things to fetch and put on display
    # Display prompt: have you fetched them all?
    # If yes, update records.  If no, don't.
    sl = []
    for i in stockline_list:
        td.s.add(i)
        r = i.calculate_restock()
        if len(r) > 0:
            sl.append((i, r))
    if sl == []:
        ui.infopopup(["There is no stock to be put on display."],
                     title="Stock movement")
        return
    if not tillconfig.receipt_printer:
        ui.infopopup(["This till does not have a receipt printer. "
                      "Use a till with a receipt printer to print out "
                      "the restock list."], title="Error")
        return
    printer.print_restock_list(tillconfig.receipt_printer, sl)
    user.log("Printed restock list")
    ui.infopopup(
        ["The list of stock to be put on display has been printed.", "",
         "Please choose one of the following options:", "",
         "1. I have finished moving the stock on the printed list.",
         "2. I have not moved any stock and I have thrown the list away."],
        title="Confirm stock movement",
        keymap={"1": (finish_restock, (sl,), True),
                "2": (abandon_restock, (sl,), True)},
        colour=ui.colour_confirm, dismiss=None)\
      .unsaved_data = "confirm stock movements"


def abandon_restock(sl):
    user.log("Abandoned restock")
    ui.infopopup(["The stock movements in the list HAVE NOT been recorded."],
                 title="Stock movement abandoned")


def finish_restock(rsl):
    for stockline, stockmovement in rsl:
        td.s.add(stockline)
        for sos, move, newdisplayqty, instock_after_move in stockmovement:
            td.s.add(sos)
            sos.displayqty = newdisplayqty
    user.log("Finished restock")
    td.s.flush()
    ui.infopopup(["The till has recorded all the stock movements "
                  "in the list."], title="Stock movement confirmed",
                 colour=ui.colour_info, dismiss=keyboard.K_CASH)


def restock_item(stockline):
    return restock_list([stockline])


@user.permission_required('restock', "Re-stock items on display stocklines")
def restock_location():
    """Display a menu of locations, and then invoke restock_list for
    all stocklines in the selected location.

    """
    selectlocation(restock_list, title="Re-stock location",
                   linetypes=["display"])


@user.permission_required('restock', "Re-stock items on display stocklines")
def restock_all():
    """Invoke restock_list for all stocklines, sorted by location.
    """
    restock_list(td.s.query(StockLine)
                 .filter(StockLine.linetype == "display")
                 .all())


class stockline_associations(user.permission_checked, ui.listpopup):
    """
    A window showing the list of stocklines and their associated stock
    types.  Pressing Cancel on a line deletes the association.

    """
    permission_required = ('manage-stockline-associations',
                           "View and delete stocktype <-> stockline links")

    def __init__(self, stocklines=None,
                 blurb="To create a new association, use the 'Use Stock' "
                 "button to assign stock to a line."):
        """
        If a list of stocklines is passed, restrict the editor to just
        those; otherwise list all of them.

        """
        stllist = td.s.query(StockLineTypeLog)\
                      .join(StockLineTypeLog.stockline)\
                      .join(StockLineTypeLog.stocktype)\
                      .order_by(StockLine.dept_id,
                                StockLine.name,
                                StockType.fullname)
        if stocklines:
            stllist = stllist.filter(StockLine.id.in_(stocklines))
        stllist = stllist.all()
        f = ui.tableformatter(' l l ')
        headerline = f("Stock line", "Stock type")
        lines = [f(stl.stockline.name, stl.stocktype.fullname, userdata=stl)
                 for stl in stllist]
        super().__init__(
            lines, title="Stockline / Stock type associations",
            header=["Press Cancel to delete an association.  " + blurb,
                    headerline])

    def keypress(self, k):
        if k == keyboard.K_CANCEL and self.s and self.s.cursor is not None:
            line = self.s.dl.pop(self.s.cursor)
            self.s.redraw()
            td.s.add(line.userdata)
            td.s.delete(line.userdata)
            td.s.flush()
        else:
            super().keypress(k)


@user.permission_required('return-stock',
                          "Return items on display stocklines to stock")
def return_stock(stockline):
    rsl = stockline.calculate_restock(target=0)
    if not rsl:
        ui.infopopup(["The till has no record of stock on display for "
                      "this line."], title="Remove stock")
        return
    restock = [(stockline, rsl)]
    if not tillconfig.receipt_printer:
        ui.infopopup(["This till has no receipt printer. Use a till "
                      "with a printer to print the list of stock to "
                      "be taken off display."], title="Error")
        return
    printer.print_restock_list(tillconfig.receipt_printer, restock)
    ui.infopopup(
        ["The list of stock to be taken off display has been printed.",
         "", "Press Cash/Enter to "
         "confirm that you've removed all the items on the list and "
         "allow the till to update its records.  Pressing Clear "
         "at this point will completely cancel the operation."],
        title="Confirm stock movement",
        keymap={keyboard.K_CASH: (finish_restock, (restock,), True)},
        colour=ui.colour_confirm)\
      .unsaved_data = "confirm removal of stock from sale"


def completelocation(m):
    """
    An editfield validator that completes based on stockline location.

    """
    result = td.s.execute(
        select([StockLine.location]).where(StockLine.location.ilike(m + '%'))
    )
    return [x[0] for x in result]


def validate_location(s, c):
    t = s[:c + 1]
    l = completelocation(t)
    if len(l) > 0:
        return l[0]
    # If a string one character shorter matches then we know we
    # filled it in last time, so we should return the string with
    # the rest chopped off rather than just returning the whole
    # thing unedited.
    if len(completelocation(t[:-1])) > 0:
        return t
    return s


@user.permission_required('create-stockline', "Create a new stock line")
def create(func, linetypes=["regular", "display", "continuous"]):
    menu = []
    if "regular" in linetypes:
        menu.append(("1", ui.lrline(
            "Regular.\n\nThese stock lines can have at most one stock item "
            "on sale at any one time.  Finishing that stock item and "
            "putting another item on sale are done explicitly using "
            "the 'Use Stock' button.  Typically used where it's obvious "
            "to the person serving when a stock item comes to an end: "
            "casks/kegs, bottles of spirits, snacks from cards or boxes, "
            "and so on.\n"), _create_stockline_popup, ('regular', func)))
    if "display" in linetypes:
        menu.append(("2", ui.lrline(
            "Display.\n\nThese can have several stock items, all of the "
            "same type, on sale at once.  The number of items 'on display' "
            "and 'in stock' are tracked separately; stock is only sold "
            "from the items on display.  The 'Use Stock' button is used "
            "to print a restocking list which shows how many items need "
            "to be moved from stock to fill up the display.  Typically "
            "used for bottles supplied in cases but displayed in "
            "fridges.  May also be used for snacks where the display "
            "space is small and the boxes the snacks are supplied in "
            "won't fit.  Can't be used where items are not sold in "
            "whole numbers.\n"), _create_stockline_popup, ('display', func)))
    if "continuous" in linetypes:
        menu.append(("3", ui.lrline(
            "Continuous.\n\nThese are used when selling variable sized "
            "measures where it's not obvious to the person serving where "
            "one stock item ends and another starts.  Typically used for "
            "wine from bottles and soft drinks from cartons: if a glass "
            "is filled from more than one bottle it won't be obvious "
            "whether the two bottles were originally in the same case."),
            _create_stockline_popup, ('continuous', func)))
    ui.keymenu(menu, blurb="Choose the type of stockline to create:",
               title="Create Stock Line", blank_line_between_items=True)


class _create_stockline_popup(user.permission_checked, ui.dismisspopup):
    """Create a new stockline."""
    permission_required = ('create-stockline', "Create a new stock line")

    def __init__(self, linetype, func):
        heights = {
            'regular': 8,
            'display': 10,
            'continuous': 9,
        }
        super().__init__(
            heights[linetype],
            52 if linetype == 'regular' else 75,
            title=f"Create {linetype} stock line",
            colour=ui.colour_input,
            dismiss=keyboard.K_CLEAR)
        self.linetype = linetype
        self.func = func
        self.win.drawstr(2, 2, 18, "Stock line name: ", align=">")
        self.namefield = ui.editfield(2, 20, 30, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.win.drawstr(3, 2, 18, "Location: ", align=">")
        self.locfield = ui.editfield(3, 20, 20, validate=validate_location)
        self.fields = [self.namefield, self.locfield]
        y = 4
        if linetype == "display":
            self.win.drawstr(y, 2, 18, "Display capacity: ", align=">")
            self.capacityfield = ui.editfield(
                y, 20, 5, validate=ui.validate_positive_nonzero_int)
            self.fields.append(self.capacityfield)
            y += 1
        if linetype == "display" or linetype == "continuous":
            self.win.drawstr(y, 2, 18, "Stock type: ", align=">")
            self.stocktypefield = ui.modelpopupfield(
                y, 20, 52, StockType, stocktype.choose_stocktype,
                lambda si: si.format())
            self.fields.append(self.stocktypefield)
            y += 1
        self.createfield = ui.buttonfield(
            y + 1, 21 if linetype == 'regular' else 33, 10, "Create",
            keymap={keyboard.K_CASH: (self.enter, (), False)})
        self.fields.append(self.createfield)
        ui.map_fieldlist(self.fields)
        self.namefield.focus()

    def enter(self):
        for f in self.fields:
            if not f.read():
                ui.infopopup(["You must fill in all the fields."],
                             title="Error")
                return
        sl = StockLine(name=self.namefield.f,
                       location=self.locfield.f,
                       linetype=self.linetype)
        if self.linetype == 'display':
            sl.capacity = int(self.capacityfield.f)
        if self.linetype == 'display' or self.linetype == 'continuous':
            sl.stocktype = self.stocktypefield.read()
        td.s.add(sl)
        try:
            td.s.flush()
            user.log(f"Created stockline '{sl.logref}'")
        except IntegrityError:
            td.s.rollback()
            ui.infopopup([f"Could not create stock line '{self.namefield.f}'; "
                          "there is a stock line with that name already."],
                         title="Error")
            return
        self.dismiss()
        self.func(sl)
        if sl.linetype == "regular":
            # If creating a regular stock line, prompt the user for the
            # initial stock item - if they don't want to specify one they
            # can just dismiss the popup
            ui.handle_keyboard_input(keyboard.K_USESTOCK)
        if sl.linetype == "display":
            from . import usestock
            usestock.add_display_line_stock(sl)


class modify(user.permission_checked, ui.dismisspopup):
    """Modify a stockline.

    Shows the name, location and other fields relevant to the type of
    stockline, and allows them to be edited.
    """
    permission_required = (
        'alter-stockline', 'Modify or delete an existing stock line')

    def __init__(self, stockline):
        mh, mw = ui.rootwin.size()
        if mw < 77:
            ui.infopopup(["Error: the register area of the display is too "
                          "narrow to display this dialog.  It must be at least "
                          "77 characters across."],
                         title="Screen width problem")
            return
        if mh < 21:
            ui.infopopup(["Error: the register area of the display is not "
                          "tall enough to display this dialog.  It must be "
                          "at least 21 characters tall."],
                         title="Screen height problem")
            return
        h = mh
        td.s.add(stockline)
        sanity_check_stock_on_sale(stockline)
        self.stockline = stockline
        self.sid = stockline.id
        super().__init__(
            h, 77,
            title=f"Modify {self.stockline.linetype} stock line",
            colour=ui.colour_input,
            dismiss=keyboard.K_CLEAR)
        self.win.drawstr(2, 2, 21, "Stock line name: ", align=">")
        self.namefield = ui.editfield(2, 23, 30, f=stockline.name, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.win.drawstr(3, 2, 21, "Location: ", align=">")
        self.locfield = ui.editfield(3, 23, 20, f=stockline.location,
                                     validate=validate_location)
        self.fields = [self.namefield, self.locfield]
        y = 4
        if stockline.linetype == 'regular':
            self.win.drawstr(y, 2, 21, "Pull-through amount: ", align=">")
            self.pullthrufield = ui.editfield(
                y, 23, 5, f=stockline.pullthru, validate=ui.validate_float)
            self.fields.append(self.pullthrufield)
            y += 1
            self.win.drawstr(y, 2, 21, "Department: ", align=">")
            self.deptfield = ui.modellistfield(
                y, 23, 20, Department,
                lambda q: q.order_by(Department.id),
                f=stockline.department,
                d=lambda x: x.description)
            self.fields.append(self.deptfield)
            y += 1
        if stockline.linetype == 'display':
            self.win.drawstr(y, 2, 21, "Display capacity: ", align=">")
            self.capacityfield = ui.editfield(
                y, 23, 5, f=stockline.capacity,
                validate=ui.validate_positive_nonzero_int)
            self.fields.append(self.capacityfield)
            y += 1
        self.win.drawstr(y, 2, 21, "Stock type: ", align=">")
        self.stocktypefield = ui.modelpopupfield(
            y, 23, 52, StockType, stocktype.choose_stocktype,
            lambda si: si.format(),
            f=stockline.stocktype)
        self.fields.append(self.stocktypefield)
        y += 1
        if stockline.linetype == 'regular':
            y += self.win.wrapstr(
                y, 2, 73,
                "Setting department or stock type will restrict "
                "the types of stock allowed to be put on sale on "
                "this stock line in the future.")
        if stockline.linetype == 'display':
            y += self.win.wrapstr(
                y, 2, 73,
                "Changing the stock type will remove all stock items "
                "currently on sale on this line and add all unallocated "
                "stock items of the new stock type.")
        y += 1
        self.fields.append(ui.buttonfield(y, 2, 8, "Save", keymap={
            keyboard.K_CASH: (self.save, None)}))
        self.fields.append(ui.buttonfield(y, 12, 10, "Delete", keymap={
            keyboard.K_CASH: (self.delete, None)}))
        # Stock control terminals won't have a dedicated "Use Stock"
        # button.  This button fakes that keypress.  It isn't relevant
        # for continuous stock lines.
        if stockline.linetype != "continuous":
            self.fields.append(ui.buttonfield(
                y, 25, 13, "Use Stock", keymap={
                    keyboard.K_CASH: (
                        lambda: ui.handle_keyboard_input(keyboard.K_USESTOCK),
                        None)}))
        self.fields.append(ui.buttonfield(
            y, 25 if stockline.linetype == "continuous" else 40, 16,
            "Associations", keymap={
                keyboard.K_CASH: (
                    lambda: stockline_associations(stocklines=[self.sid]),
                    None)}))
        y += 2
        y += self.win.wrapstr(
            y, 2, 73,
            "To add a keyboard binding, press a line key now.\n\n"
            "To edit or delete a keyboard binding, choose it "
            "below and press Enter or Cancel.")
        y += 1
        self.bindings_header_y = y
        y += 1
        self.kbs = ui.scrollable(y, 1, 56, h - y - 1, [], keymap={
            keyboard.K_CASH: (self.editbinding, None),
            keyboard.K_CANCEL: (self.deletebinding, None)})
        self.fields.append(self.kbs)
        ui.map_fieldlist(self.fields)
        self.reload_bindings()
        self.namefield.focus()

    def keypress(self, k):
        # Handle keypresses that the fields pass up to the main popup
        if k == keyboard.K_USESTOCK:
            from . import usestock
            usestock.line_chosen(self.stockline)
        elif hasattr(k, 'line'):
            linekeys.addbinding(self.stockline, k,
                                self.reload_bindings,
                                modifiers.defined_modifiers())

    def save(self):
        if self.namefield.f == '' or self.locfield.f == '':
            ui.infopopup(
                ["You may not make the name or location fields blank."],
                title="Error")
            return
        td.s.add(self.stockline)
        if self.stockline.linetype == "display":
            if self.capacityfield.f == '':
                ui.infopopup(["You may not make the capacity field blank.",
                              "",
                              "If you want to change this stock line to be "
                              "a different type, you should delete it and "
                              "create it again."],
                             title="Error")
                return
        if self.stockline.linetype == "display" \
           or self.stockline.linetype == "continuous":
            if self.stocktypefield.read() is None:
                ui.infopopup(["You may not make the stock type field blank."],
                             title="Error")
                return

        if self.stockline.linetype == "regular":
            self.stockline.pullthru = Decimal(self.pullthrufield.f) \
                if self.pullthrufield.f != '' else None
        additional = []
        if self.stockline.linetype == "display":
            newcap = int(self.capacityfield.f)
            if newcap != self.stockline.capacity:
                additional.append(
                    "The change in display capacity will take effect next "
                    "time the line is re-stocked.")
                self.stockline.capacity = newcap

        oldstocktype = self.stockline.stocktype
        self.stockline.stocktype = self.stocktypefield.read()
        if self.stockline.linetype == 'display':
            if self.stockline.stocktype != oldstocktype \
               and self.stockline.stockonsale:
                for si in list(self.stockline.stockonsale):
                    si.displayqty = None
                    si.stockline = None
                additional.append(
                    "The stock type has been changed.  All stock items "
                    "that were attached to the stock line have been "
                    "removed.")
                # XXX call auto-allocate to add new items

        try:
            self.stockline.name = self.namefield.f
            td.s.flush()
        except IntegrityError:
            ui.infopopup(
                [f"There is already another stock line called "
                 f"'{self.namefield.f}'. You can't give this stock line "
                 f"the same name."])
            td.s.rollback()
            return
        self.stockline.location = self.locfield.f
        if self.stockline.linetype == "regular":
            self.stockline.department = self.deptfield.read()
        try:
            td.s.flush()
        except Exception:
            ui.infopopup(
                [f"Could not update stock line '{self.stockline.name}'."],
                title="Error")
            return
        self.dismiss()
        user.log(f"Updated stock line '{self.stockline.logref}'")
        ui.infopopup([f"Updated stock line '{self.stockline.name}'.",
                      ""] + additional,
                     colour=ui.colour_info, dismiss=keyboard.K_CASH,
                     title="Confirmation")

    def delete(self):
        self.dismiss()
        td.s.add(self.stockline)
        if len(self.stockline.stockonsale) > 0:
            # Set displayqtys to none - if we don't do this explicitly here
            # then setting the stockline field to null will violate the
            # displayqty_null_if_no_stockline constraint
            for si in self.stockline.stockonsale:
                si.displayqty = None
            message = [
                "The stock line has been deleted.  Note that it still "
                "had stock attached to it; this stock is now available "
                "to be attached to another stock line.  The stock items "
                "affected are shown below.",
                ""
            ]
            message = message + [
                f"  {x.id} {x.stocktype}"
                for x in self.stockline.stockonsale]
        else:
            message = ["The stock line has been deleted."]
        user.log(f"Deleted stockline '{self.stockline.logref}'")
        td.s.delete(self.stockline)
        # Any StockItems that point to this stockline should have their
        # stocklineid set to null by the database.
        td.s.flush()
        ui.infopopup(message, title="Stock line deleted", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def editbinding(self):
        if self.kbs.cursor is None:
            return
        line = self.kbs.dl[self.kbs.cursor]
        linekeys.changebinding(line.userdata, self.reload_bindings,
                               modifiers.defined_modifiers())

    def deletebinding(self):
        # We should only be called when the scrollable has the focus
        if self.kbs.cursor is None:
            return
        line = self.kbs.dl.pop(self.kbs.cursor)
        self.kbs.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()

    def reload_bindings(self):
        td.s.add(self.stockline)
        f = ui.tableformatter(' l   c   l ')
        kbl = linekeys.keyboard_bindings_table(
            self.stockline.keyboard_bindings, f)
        self.win.addstr(self.bindings_header_y, 1, " " * 75)
        self.win.addstr(
            self.bindings_header_y, 1, f(
                "Line key", "Menu key", "Default modifier").
            display(75)[0])
        self.kbs.set(kbl)


class note(user.permission_checked, ui.dismisspopup):
    permission_required = (
        'stockline-note', 'Change the note on a stock line')

    def __init__(self, stockline):
        self.stocklineid = stockline.id
        super().__init__(7, 60, title=f"Set the note on {stockline.name}",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 6, "Note: ", align=">")
        self.notefield = ui.editfield(
            2, 8, 47, f=stockline.note, flen=200,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.b = ui.buttonfield(4, 26, 7, "Set", keymap={
            keyboard.K_CASH: (self.enter, None)})
        ui.map_fieldlist([self.notefield, self.b])
        self.notefield.focus()

    def enter(self):
        stockline = td.s.query(StockLine).get(self.stocklineid)
        if stockline:
            stockline.note = self.notefield.f
        self.dismiss()


class listunbound(user.permission_checked, ui.listpopup):
    """Pop up a list of stock lines with no key bindings on any keyboard."""
    permission_required = ('list-unbound-stocklines',
                           "List stock lines with no keyboard bindings")

    def __init__(self):
        l = td.s.query(StockLine)\
                .outerjoin(KeyboardBinding)\
                .filter(KeyboardBinding.stocklineid == None)\
                .all()
        if not l:
            ui.infopopup(
                ["There are no stock lines that lack key bindings.",
                 "", "Note that other tills may have key bindings to "
                 "a stock line even if this till doesn't."],
                title="Unbound stock lines", colour=ui.colour_info,
                dismiss=keyboard.K_CASH)
            return
        f = ui.tableformatter(' l l l l ')
        headerline = f("Name", "Location", "Department", "Stock")
        self.ll = [f(x.name, x.location,
                     x.department.description if x.department else "",
                     "Yes" if len(x.stockonsale) > 0 else "No",
                     userdata=x) for x in l]
        super().__init__(self.ll, title="Unbound stock lines",
                         colour=ui.colour_info, header=[headerline])

    def keypress(self, k):
        if k == keyboard.K_CASH:
            self.dismiss()
            modify(self.ll[self.s.cursor].userdata)
        else:
            super().keypress(k)


class selectline(ui.listpopup):
    """Pop-up menu of stocklines

    A pop-up menu of stocklines, sorted by location and name and
    filtered by stockline type.  Stocklines with key or barcode
    bindings can be selected through that binding if they match the
    filter.

    Calls func with the StockLine instance as the argument. The
    instance is guaranteed to be in the current ORM session.

    Optional arguments:
      blurb - text for the top of the window
      linetypes - list of permissible line types
      create_new - allow a new stockline to be created
      select_none - a string for a menu item which will result in a call
        to func(None)

    """
    def __init__(self, func, title="Stock Lines", blurb=None,
                 linetypes=["regular", "display", "continuous"],
                 keymap={}, create_new=False, select_none=None):
        self.func = func
        self.linetypes = tuple(linetypes)
        q = td.s.query(StockLine).order_by(StockLine.location,
                                           StockLine.name)
        q = q.filter(StockLine.linetype.in_(linetypes))
        stocklines = q.all()
        f = ui.tableformatter(' l l l l ')
        self.sl = [f(x.name, x.location,
                     x.department if x.department else "Any",
                     x.typeinfo,
                     userdata=x.id)
                   for x in stocklines]
        self.create_new = create_new
        if create_new:
            self.sl = [ui.line(" New stockline")] + self.sl
        elif select_none:
            self.sl = [ui.line(" %s" % select_none)] + self.sl
        hl = [f("Name", "Location", "Department", "Type")]
        if blurb:
            hl = [ui.lrline(blurb), ui.emptyline()] + hl
        super().__init__(self.sl, title=title, header=hl, keymap=keymap)

    def line_selected(self, kb):
        # kb is either a KeyboardBinding or a Barcode; both of these
        # have stockline attributes

        # kb is guaranteed to be in the current ORM session when we
        # are called.
        if kb.stockline.linetype in self.linetypes:
            self.dismiss()
            self.func(kb.stockline)

    def keypress(self, k):
        log.debug("selectline keypress %s", k)
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.line_selected)
        elif hasattr(k, 'code'):
            if k.binding and k.binding.stockline:
                self.line_selected(k.binding)
            else:
                ui.beep()
        elif k == keyboard.K_CASH and len(self.sl) > 0:
            self.dismiss()
            line = self.sl[self.s.cursor]
            if line.userdata:
                stockline = td.s.query(StockLine).get(line.userdata)
                if stockline:
                    self.func(stockline)
            else:
                if self.create_new:
                    create(self.func, linetypes=self.linetypes)
                else:
                    self.func(None)
        else:
            super().keypress(k)


def stocklinemenu():
    """Menu allowing stocklines to be created, modified and deleted.
    """
    selectline(
        modify, blurb="Choose a stock line to modify from the list below, "
        "or press a line key that is already bound to the "
        "stock line.", create_new=True)


def stocklinenotemenu():
    """Menu allowing notes to be set on stocklines
    """
    selectline(
        note, blurb="Choose a stock line from the list below, or press "
        "a line key that is bound to the stock line.",
        linetypes=["regular"], create_new=False)


def selectlocation(func, title="Stock Locations", blurb="Choose a location",
                   linetypes=None):
    """A pop-up menu of stock locations.

    Calls func with a list of stocklines for the selected location.
    """
    stocklines = td.s.query(StockLine)
    if linetypes:
        stocklines = stocklines.filter(
            StockLine.linetype.in_(linetypes))
    stocklines = stocklines.all()
    l = {}
    for sl in stocklines:
        if sl.location in l:
            l[sl.location].append(sl)
        else:
            l[sl.location] = [sl]
    ml = [(x, func, (l[x],)) for x in list(l.keys())]
    ui.menu(ml, title=title, blurb=blurb)


def sanity_check_stock_on_sale(stockline):
    """Remove any stock on sale of an inappropriate type."""
    if stockline.linetype != "display":
        return
    for s in list(stockline.stockonsale):
        if s.stocktype != stockline.stocktype:
            s.displayqty = None
            s.stockline = None
