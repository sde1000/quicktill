import logging
from . import keyboard, ui, td, tillconfig, printer, user, linekeys, modifiers
from . import stocktype
from .models import Department, StockLine, KeyboardBinding
from .models import StockType, StockLineTypeLog
from sqlalchemy.sql import select
from decimal import Decimal
log = logging.getLogger(__name__)

def restock_list(stockline_list):
    # Print out list of things to fetch and put on display
    # Display prompt: have you fetched them all?
    # If yes, update records.  If no, don't.
    sl=[]
    for i in stockline_list:
        td.s.add(i)
        r=i.calculate_restock()
        if len(r)>0: sl.append((i,r))
    if sl==[]:
        ui.infopopup(["There is no stock to be put on display."],
                     title="Stock movement")
        return
    printer.print_restock_list(sl)
    ui.infopopup([
            "The list of stock to be put on display has been printed.","",
            "Please choose one of the following options:","",
            "1. I have finished moving the stock on the printed list.",
            "2. I have not moved any stock and I have thrown the list away."],
                 title="Confirm stock movement",
                 keymap={"1": (finish_restock, (sl,), True),
                         "2": (abandon_restock, (sl,), True)},
                 colour=ui.colour_confirm,dismiss=None).\
        unsaved_data="confirm stock movements"

def abandon_restock(sl):
    ui.infopopup(["The stock movements in the list HAVE NOT been recorded."],
                 title="Stock movement abandoned")

def finish_restock(rsl):
    for stockline,stockmovement in rsl:
        td.s.add(stockline)
        for sos,move,newdisplayqty,instock_after_move in stockmovement:
            td.s.add(sos)
            sos.displayqty=newdisplayqty
    td.s.flush()
    ui.infopopup(["The till has recorded all the stock movements "
                  "in the list."],title="Stock movement confirmed",
                 colour=ui.colour_info,dismiss=keyboard.K_CASH)

def restock_item(stockline):
    return restock_list([stockline])

@user.permission_required('restock',"Re-stock items on display stocklines")
def restock_location():
    """Display a menu of locations, and then invoke restock_list for
    all stocklines in the selected location.

    """
    selectlocation(restock_list,title="Re-stock location",caponly=True)

@user.permission_required('restock',"Re-stock items on display stocklines")
def restock_all():
    """Invoke restock_list for all stocklines, sorted by location.

    """
    restock_list(td.s.query(StockLine).filter(StockLine.capacity!=None).all())

class stockline_associations(user.permission_checked,ui.listpopup):
    """
    A window showing the list of stocklines and their associated stock
    types.  Pressing Cancel on a line deletes the association.

    """
    permission_required=('manage-stockline-associations',
                         "View and delete stocktype <-> stockline links")
    def __init__(self, stocklines=None,
                 blurb="To create a new association, use the 'Use Stock' "
                 "button to assign stock to a line."):
        """
        If a list of stocklines is passed, restrict the editor to just
        those; otherwise list all of them.

        """
        stllist=td.s.query(StockLineTypeLog).\
            join(StockLineTypeLog.stockline).\
            join(StockLineTypeLog.stocktype).\
            order_by(StockLine.dept_id,StockLine.name,StockType.fullname)
        if stocklines:
            stllist=stllist.filter(StockLine.id.in_(stocklines))
        stllist=stllist.all()
        f=ui.tableformatter(' l l ')
        headerline=f("Stock line","Stock type")
        lines=[f(stl.stockline.name,stl.stocktype.fullname,userdata=stl)
               for stl in stllist]
        ui.listpopup.__init__(
            self,lines,title="Stockline / Stock type associations",
            header=["Press Cancel to delete an association.  "+blurb,
                    headerline])
    def keypress(self,k):
        if k==keyboard.K_CANCEL and self.s:
            line=self.s.dl.pop(self.s.cursor)
            self.s.redraw()
            td.s.add(line.userdata)
            td.s.delete(line.userdata)
            td.s.flush()
        else:
            ui.listpopup.keypress(self,k)

def return_stock(stockline):
    td.s.add(stockline)
    rsl=stockline.calculate_restock(target=0)
    if not rsl:
        ui.infopopup(["The till has no record of stock on display for "
                      "this line."],title="Remove stock")
        return
    restock=[(stockline,rsl)]
    printer.print_restock_list(restock)
    ui.infopopup([
        "The list of stock to be taken off display has been printed.",
        "","Press Cash/Enter to "
        "confirm that you've removed all the items on the list and "
        "allow the till to update its records.  Pressing Clear "
        "at this point will completely cancel the operation."],
                 title="Confirm stock movement",
                 keymap={keyboard.K_CASH:(finish_restock,(restock,),True)},
                 colour=ui.colour_confirm).\
        unsaved_data="confirm removal of stock from sale"

def completelocation(m):
    """
    An editfield validator that completes based on stockline location.

    """
    result=td.s.execute(
        select([StockLine.location]).\
            where(StockLine.location.ilike(m+'%'))
        )
    return [x[0] for x in result]

def validate_location(s,c):
    t=s[:c+1]
    l=completelocation(t)
    if len(l)>0: return l[0]
    # If a string one character shorter matches then we know we
    # filled it in last time, so we should return the string with
    # the rest chopped off rather than just returning the whole
    # thing unedited.
    if len(completelocation(t[:-1]))>0:
        return t
    return s

@user.permission_required('create-stockline', "Create a new stock line")
def create(func):
    menu = [
        ("1", ui.lrline(
            "Regular.\n\nThese stock lines can have at most one stock item "
            "on sale at any one time.  Finishing that stock item and "
            "putting another item on sale are done explicitly using "
            "the 'Use Stock' button.  Typically used where it's obvious "
            "to the person serving when a stock item comes to an end: "
            "casks/kegs, bottles of spirits, snacks from cards or boxes, "
            "and so on.\n"), _create_stockline_popup, ('regular', func)),
        ("2", ui.lrline(
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
            "whole numbers.\n"), _create_stockline_popup, ('display', func)),
        ("3", ui.lrline(
            "Continuous.\n\nThese are used when selling variable sized "
            "measures where it's not obvious to the person serving where "
            "one stock item ends and another starts.  Typically used for "
            "wine from bottles and soft drinks from cartons: if a glass "
            "is filled from more than one bottle it won't be obvious "
            "whether the two bottles were originally in the same case."),
            _create_stockline_popup, ('continuous', func)),
        ]
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
        ui.dismisspopup.__init__(
            self, heights[linetype],
            52 if linetype == 'regular' else 75,
            title="Create {} stock line".format(linetype),
            colour=ui.colour_input,
            dismiss=keyboard.K_CLEAR)
        self.linetype = linetype
        self.func = func
        self.addstr(2,2," Stock line name:")
        self.namefield = ui.editfield(2, 20, 30, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.addstr(3,2,"        Location:")
        self.locfield = ui.editfield(3, 20, 20, validate=validate_location)
        self.fields = [self.namefield, self.locfield]
        y = 4
        if linetype == "display":
            self.addstr(y,2,"Display capacity:")
            self.capacityfield = ui.editfield(y, 20, 5, validate=ui.validate_int)
            self.fields.append(self.capacityfield)
            y += 1
        if linetype == "display" or linetype == "continuous":
            self.addstr(y,2,"      Stock type:")
            self.stocktypefield = ui.popupfield(
                y, 20, 52, stocktype.choose_stocktype, lambda si: si.format())
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
            if not f.f:
                ui.infopopup(["You must fill in all the fields."], title="Error")
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
        except td.IntegrityError:
            td.s.rollback()
            ui.infopopup(["Could not create stock line '{}'; there is "
                          "a stock line with that name already.".format(
                              self.namefield.f,)],
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

    def keypress(self, k):
        # If the user starts typing into the stocktype field, be nice
        # to them and pop up the stock type entry dialog.  Then
        # synthesise the keypress again to enter it into the
        # manufacturer field.
        if self.linetype != 'regular' \
           and self.stocktypefield.focused \
           and self.stocktypefield.f is None \
           and isinstance(k, str) \
           and k:
            self.stocktypefield.popup() # Grabs the focus
            ui.handle_keyboard_input(k)
        else:
            super(_create_stockline_popup, self).keypress(k)

class modify(user.permission_checked,ui.dismisspopup):
    """Modify a stockline.

    Shows the name, location and other fields relevant to the type of
    stockline, and allows them to be edited.
    """
    permission_required = (
        'alter-stockline', 'Modify or delete an existing stock line')

    def __init__(self, stockline):
        h = 24
        td.s.add(stockline)
        sanity_check_stock_on_sale(stockline)
        self.stockline = stockline
        self.sid = stockline.id
        ui.dismisspopup.__init__(
            self, h, 77,
            title="Modify {} stock line".format(self.stockline.linetype),
            colour=ui.colour_input,
            dismiss=keyboard.K_CLEAR)
        self.addstr(2, 2, "    Stock line name:")
        self.namefield = ui.editfield(2, 23, 30, f=stockline.name, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.addstr(3, 2, "           Location:")
        self.locfield=ui.editfield(3, 23, 20, f=stockline.location,
                                   validate=validate_location)
        self.fields = [self.namefield, self.locfield]
        y = 4
        if stockline.linetype == 'regular':
            self.addstr(y, 2, "Pull-through amount:")
            self.pullthrufield = ui.editfield(
                y, 23, 5, f=stockline.pullthru, validate=ui.validate_float)
            self.fields.append(self.pullthrufield)
            y += 1
            self.addstr(y, 2, "         Department:")
            depts = td.s.query(Department).order_by(Department.id).all()
            self.deptfield = ui.listfield(
                y, 23, 20, depts, f=stockline.department,
                d=lambda x: x.description)
            self.fields.append(self.deptfield)
            y += 1
        if stockline.linetype == 'display':
            self.addstr(y, 2, "   Display capacity:")
            self.capacityfield = ui.editfield(
                y, 23, 5, f=stockline.capacity, validate=ui.validate_int)
            self.fields.append(self.capacityfield)
            y += 1
        self.addstr(y, 2, "         Stock type:")
        self.stocktypefield = ui.popupfield(
            y, 23, 52, stocktype.choose_stocktype, lambda si: si.format(),
            f=stockline.stocktype)
        self.fields.append(self.stocktypefield)
        y += 1
        if stockline.linetype == 'regular':
            y += self.wrapstr(
                y, 2, 73,
                "Setting department or stock type will restrict "
                "the types of stock allowed to be put on sale on "
                "this stock line in the future.")
        if stockline.linetype == 'display':
            y += self.wrapstr(
                y, 2, 73,
                "Changing the stock type will remove all stock items "
                "currently on sale on this line and add all unallocated "
                "stock items of the new stock type.")
        y += 1
        self.fields.append(ui.buttonfield(y, 2, 8,"Save", keymap={
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
        y += self.wrapstr(
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

    def keypress(self,k):
        # Handle keypresses that the fields pass up to the main popup
        if self.stocktypefield.focused \
           and self.stocktypefield.f is None \
           and isinstance(k, str) \
           and k:
            self.stocktypefield.popup() # Grabs the focus
            ui.handle_keyboard_input(k)
        elif k == keyboard.K_USESTOCK:
            from . import usestock
            usestock.line_chosen(self.stockline)
        elif hasattr(k, 'line'):
            linekeys.addbinding(self.stockline, k,
                                self.reload_bindings,
                                modifiers.defined_modifiers())

    def save(self):
        if self.namefield.f == '' or self.locfield.f == '':
            ui.infopopup(["You may not make the name or location fields blank."],
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

        self.stockline.name = self.namefield.f
        self.stockline.location = self.locfield.f
        if self.stockline.linetype == "regular":
            self.stockline.department = self.deptfield.read()
        try:
            td.s.flush()
        except:
            ui.infopopup(["Could not update stock line '{}'.".format(
                self.stockline.name)], title="Error")
            return
        self.dismiss()
        ui.infopopup(["Updated stock line '{}'.".format(self.stockline.name),
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
            message = ["The stock line has been deleted.  Note that it still "
                       "had stock attached to it; this stock is now available "
                       "to be attached to another stock line.  The stock items "
                       "affected are shown below.",""]
            message = message + [
                "  {} {}".format(x.id, x.stocktype.format())
                for x in self.stockline.stockonsale]
        else:
            message = ["The stock line has been deleted."]
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
        self.addstr(self.bindings_header_y, 1, " " * 75)
        self.addstr(self.bindings_header_y, 1, f(
            "Line key","Menu key","Default modifier").
                    display(75)[0])
        self.kbs.set(kbl)

class listunbound(ui.listpopup):
    """Pop up a list of stock lines with no key bindings on any keyboard."""
    def __init__(self):
        l=td.s.query(StockLine).outerjoin(KeyboardBinding).\
            filter(KeyboardBinding.stocklineid==None).\
            all()
        if len(l)==0:
            ui.infopopup(
                ["There are no stock lines that lack key bindings.",
                 "","Note that other tills may have key bindings to "
                 "a stock line even if this till doesn't."],
                title="Unbound stock lines",colour=ui.colour_info,
                dismiss=keyboard.K_CASH)
            return
        f=ui.tableformatter(' l l l l ')
        headerline=f("Name","Location","Department","Stock")
        self.ll=[f(x.name,x.location,x.department.description,
                   "Yes" if len(x.stockonsale)>0 else "No",
                   userdata=x) for x in l]
        ui.listpopup.__init__(self,self.ll,title="Unbound stock lines",
                              colour=ui.colour_info,header=[headerline])

    def keypress(self,k):
        if k==keyboard.K_CASH:
            self.dismiss()
            modify(self.ll[self.s.cursor].userdata)
        else:
            ui.listpopup.keypress(self,k)

class selectline(ui.listpopup):
    """
    A pop-up menu of stocklines, sorted by department, location and
    name.  Optionally can remove stocklines that have no capacities.
    Stocklines with key bindings can be selected through that binding.

    Optional arguments:
      blurb - text for the top of the window
      caponly - only list "display" stocklines
      exccap - don't list "display" stocklines
      create_new - allow a new stockline to be created
      select_none - a string for a menu item which will result in a call
        to func(None)

    """
    # XXX caponly and exccap should be renamed and changed to use the linetype
    def __init__(self,func,title="Stock Lines",blurb=None,caponly=False,
                 exccap=False,keymap={},create_new=False,select_none=None):
        self.func=func
        q=td.s.query(StockLine).order_by(StockLine.dept_id,StockLine.location,
                                         StockLine.name)
        if caponly: q=q.filter(StockLine.capacity!=None)
        if exccap: q=q.filter(StockLine.capacity==None)
        stocklines=q.all()
        f=ui.tableformatter(' l l l r r ')
        self.sl=[f(x.name,x.location,x.department,
                   x.capacity or "",x.pullthru or "",
                   userdata=x)
                 for x in stocklines]
        self.create_new=create_new
        if create_new:
            self.sl=[ui.line(" New stockline")]+self.sl
        elif select_none:
            self.sl=[ui.line(" %s"%select_none)]+self.sl
        hl=[f("Name","Location","Department","DC","PT")]
        if blurb:
            hl=[ui.lrline(blurb),ui.emptyline()]+hl
        ui.listpopup.__init__(self,self.sl,title=title,header=hl,keymap=keymap)
    def line_selected(self,kb):
        self.dismiss()
        td.s.add(kb)
        self.func(kb.stockline)
    def keypress(self,k):
        log.debug("selectline keypress %s",k)
        if hasattr(k,'line'):
            linekeys.linemenu(k,self.line_selected)
        elif k==keyboard.K_CASH and len(self.sl)>0:
            self.dismiss()
            line=self.sl[self.s.cursor]
            if line.userdata: self.func(line.userdata)
            else:
                if self.create_new: create(self.func)
                else: self.func(None)
        else:
            ui.listpopup.keypress(self,k)

def stocklinemenu():
    """
    Menu allowing stocklines to be created, modified and deleted.

    """
    selectline(
        modify,blurb="Choose a stock line to modify from the list below, "
        "or press a line key that is already bound to the "
        "stock line.",create_new=True)

def selectlocation(func,title="Stock Locations",blurb="Choose a location",
                   caponly=False):
    """A pop-up menu of stock locations.  Calls func with a list of
    stocklines for the selected location.

    """
    stocklines=td.s.query(StockLine)
    if caponly: stocklines=stocklines.filter(StockLine.capacity!=None)
    stocklines=stocklines.all()
    l={}
    for sl in stocklines:
        if sl.location in l: l[sl.location].append(sl)
        else: l[sl.location]=[sl]
    ml=[(x,func,(l[x],)) for x in list(l.keys())]
    ui.menu(ml,title=title,blurb=blurb)

def sanity_check_stock_on_sale(stockline):
    """Remove any stock on sale of an inappropriate type."""
    if stockline.linetype != "display":
        return
    for s in list(stockline.stockonsale):
        if s.stocktype != stockline.stocktype:
            s.displayqty = None
            s.stockline = None
