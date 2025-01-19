"""Useful routines for dealing with stock.

"""

import logging
from . import ui, td, keyboard, tillconfig, linekeys, user
from . import printer
from .models import Department, StockType, StockItem, StockAnnotation
from .models import AnnotationType, desc, StockLineTypeLog
from . import config
from sqlalchemy.orm import joinedload, undefer
log = logging.getLogger(__name__)

# Do we ask the user to input check digits when using stock?
checkdigit_on_usestock = config.BooleanConfigItem(
    'core:checkdigit_on_usestock', False, display_name="Require check digits?",
    description="Should check digits be enforced when putting stock on sale?")


def _reprint_label(label_printer, stockid):
    item = td.s.get(StockItem, stockid)
    user.log(f"Re-printed stock label for {item.logref}")
    with label_printer as f:
        printer.stock_label(f, item)


@user.permission_required(
    'reprint-stocklabel', 'Re-print a single stock label')
def reprint_stocklabel_choose_printer(stockid):
    menu = [(f"Print label on {x}",
             _reprint_label, (x, stockid))
            for x in tillconfig.label_printers]
    ui.automenu(menu, title="Choose where to print label",
                colour=ui.colour_confirm)


def stockinfo_linelist(sn):
    s = td.s.get(StockItem, sn)
    l = []
    l.append(ui.lrline(f"{s.stocktype} - {s.id} - {s.description}"))
    l.append("Sells for {}{}.  "
             "{} used; {} remaining.".format(
                 tillconfig.currency(), s.stocktype.pricestr,
                 s.stocktype.unit.format_stock_qty(s.used),
                 s.stocktype.unit.format_stock_qty(s.remaining)))
    l.append("")
    l.append(f"Delivered {s.delivery.date} by {s.delivery.supplier.name}")
    if s.bestbefore:
        l.append(f"Best Before {s.bestbefore}")
    if s.onsale:
        l.append(f"Put on sale {s.onsale:%c}")
    if s.firstsale:
        l.append(f"First sale: {s.firstsale:%c} Last sale: {s.lastsale:%c}")
    if s.finished:
        l.append(f"Finished {s.finished:%c} {s.finishcode.description}")
    l.append("")
    for code, qty in s.removed:
        l.append(f"{code.reason}: {s.stocktype.unit.format_stock_qty(qty)}")
    if len(s.annotations) > 0:
        l.append("Annotations:")
    for a in s.annotations:
        l.append(ui.lrline(f"{a.time:%c}{a.type.description}: {a.text}"))
    return l


def stockinfo_popup(sn):
    km = {}
    ll = stockinfo_linelist(sn)
    if tillconfig.label_printers:
        km[keyboard.K_PRINT] = (reprint_stocklabel_choose_printer, (sn,))
        ll.append(f"Press {keyboard.K_PRINT.keycap} to re-print the "
                  f"stock label")
    ui.listpopup(ll,
                 title=f"Stock Item {sn}",
                 dismiss=keyboard.K_CASH,
                 show_cursor=False,
                 colour=ui.colour_info,
                 keymap=km)


class annotate(user.permission_checked, ui.dismisspopup):
    """This class permits annotations to be made to stock items.
    """
    permission_required = ("annotate", "Add an annotation to a stock item")

    @staticmethod
    def _annotation_type_query(q):
        return q.filter(~AnnotationType.id.in_(['start', 'stop']))\
                .order_by(AnnotationType.id)

    def __init__(self):
        super().__init__(9, 70, "Annotate Stock", colour=ui.colour_input)
        self.win.drawstr(2, 2, 66,
                         "Press stock line key or enter stock number.")
        self.win.drawstr(3, 2, 19, "Stock item: ", align=">")
        self.stockfield = stockfield(
            3, 21, 47, keymap={keyboard.K_CLEAR: (self.dismiss, None)},
            filter=stockfilter(
                allow_finished=True, sort_descending_stockid=True),
            title="Choose stock item to annotate",
            check_checkdigits=False)
        self.win.drawstr(4, 2, 19, "Annotation type: ", align=">")
        self.anntypefield = ui.modellistfield(
            4, 21, 30, AnnotationType, self._annotation_type_query,
            d=lambda x: x.description)
        self.win.drawstr(5, 2, 19, "Annotation: ", align=">")
        self.annfield = ui.editfield(6, 2, 60, flen=120, keymap={
            keyboard.K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.stockfield, self.anntypefield, self.annfield])
        self.stockfield.focus()
        ui.handle_keyboard_input(keyboard.K_CASH)  # Pop up picker

    def finish(self):
        item = self.stockfield.read()
        if item is None:
            ui.infopopup(["You must choose a stock item."], title="Error")
            return
        anntype = self.anntypefield.read()
        if anntype is None:
            ui.infopopup(["You must choose an annotation type!"],
                         title="Error")
            return
        if not self.annfield.f:
            ui.infopopup(["You can't add a blank annotation!"], title="Error")
            return
        annotation = self.annfield.f or ""
        cu = ui.current_user()
        user = cu.dbuser if cu and hasattr(cu, "dbuser") else None
        td.s.add(StockAnnotation(stockitem=item, type=anntype, text=annotation,
                                 user=user))
        td.s.flush()
        self.dismiss()
        ui.infopopup(
            [f"Recorded annotation against stock item {item.id} "
             f"({item.stocktype})."],
            title="Annotation Recorded", dismiss=keyboard.K_CASH,
            colour=ui.colour_info)


class stockfilter:
    """Filter and sort available stock items.

    Filter and sort available stock items according to various
    criteria.  Stock items that are in unchecked deliveries can never
    be returned.
    """
    def __init__(self,
                 department=None,
                 stocktype_id=None,
                 allow_on_sale=True,
                 allow_finished=False,
                 allow_has_bestbefore=True,
                 allow_in_stocktake=False,
                 stockline_affinity=None,
                 sort_descending_stockid=False,
                 require_finished=False):
        self.department_id = department.id if department else None
        self.stocktype_id = stocktype_id
        self.allow_on_sale = allow_on_sale
        self.allow_finished = allow_finished
        self.allow_has_bestbefore = allow_has_bestbefore
        self.allow_in_stocktake = allow_in_stocktake
        self.stockline_affinity_id = stockline_affinity.id \
            if stockline_affinity else None
        self.sort_descending_stockid = sort_descending_stockid
        self.require_finished = require_finished
        if self.require_finished:
            self.allow_finished = True

    @property
    def is_single_department(self):
        return self.department_id is not None or self.stocktype_id is not None

    def query_items(self, department_id=None):
        """Return a query that lists matching items.

        If a department is passed, this overrides the department
        restriction in the object.
        """
        if not department_id:
            department_id = self.department_id
        q = td.s.query(StockItem)
        q = q.filter(StockItem.checked == True)

        # Unfinished items are sorted to the top
        q = q.order_by(StockItem.finished != None)
        # StockType is accessed if we're checking department or stocktake scope
        if department_id or not self.allow_in_stocktake:
            q = q.join(StockType)
        if department_id:
            q = q.filter(StockType.dept_id == department_id)
        if self.stocktype_id:
            q = q.filter(StockItem.stocktype_id == self.stocktype_id)
        if not self.allow_on_sale:
            q = q.filter(StockItem.stocklineid == None)
        if not self.allow_finished:
            q = q.filter(StockItem.finished == None)
        if not self.allow_in_stocktake:
            q = q.filter(StockType.stocktake == None)
        if self.require_finished:
            q = q.filter(StockItem.finished != None)
        if not self.allow_has_bestbefore:
            q = q.filter(StockItem.bestbefore == None)
        if self.stockline_affinity_id:
            q = q.order_by(desc(StockItem.stocktype_id.in_(
                td.select([StockLineTypeLog.stocktype_id],
                          whereclause=(
                              StockLineTypeLog.stocklineid
                              == self.stockline_affinity_id),
                          correlate=True))))
        if self.sort_descending_stockid:
            q = q.order_by(desc(StockItem.id))
        else:
            q = q.order_by(StockItem.id)
        return q

    def item_problem(self, item):
        """Why doesn't the item pass the filter?

        If the passed item matches the criteria, returns None.
        Otherwise returns a string describing at least one problem
        with the item.  The item is expected to be attached to an ORM
        session.
        """
        if item.delivery and not item.delivery.checked:
            return "delivery not checked"
        if item.stocktake and not item.stocktake.commit_time:
            return "stock take not finished"
        if self.department_id:
            if item.stocktype.dept_id != self.department_id:
                return "wrong department"
        if self.stocktype_id:
            if item.stocktype_id != self.stocktype_id:
                return "wrong type of stock"
        if item.stocklineid is not None and not self.allow_on_sale:
            return f"already on sale on {item.stockline.name}"
        if item.finished is not None and not self.allow_finished:
            return f"finished at {ui.formattime(item.finished)}"
        if item.finished is None and self.require_finished:
            return "not finished"
        if item.bestbefore is not None and not self.allow_has_bestbefore:
            return f"already has a best-before date: " \
                f"{ui.formatdate(item.bestbefore)}"
        if item.stocktype.stocktake and not self.allow_in_stocktake:
            return f"in scope for stock-take {item.stocktype.stocktake}"


class stockpicker(ui.dismisspopup):
    """Popup to choose a stock item.

    A popup window that allows a stock item to be chosen.  Contains
    one field for the stock number, and optionally another field for
    the check digits.  Pressing Enter on a blank stock number field
    will yield a popup list of departments (if no department
    constraint is specified) leading to a popup list of stock items.

    If a StockLine is specified for stockline_affinity then items of
    stock that have previously been on sale on that StockLine will be
    sorted to the top of the list.

    When the StockItem has been chosen, func is called with it as an
    argument.
    """
    def __init__(self, func, default=None, title="Choose stock item",
                 filter=stockfilter(), check_checkdigits=True):
        self.title = title
        self.func = func
        self.filter = filter
        self.check = check_checkdigits and checkdigit_on_usestock()
        h = 9 if self.check else 7
        super().__init__(h, 62, title, colour=ui.colour_input)
        self.win.drawstr(2, 2, 13, "Stock ID: ", align=">")
        self.numfield = ui.editfield(
            2, 15, 8, validate=ui.validate_positive_nonzero_int,
            f=default.id if default else None,
            keymap={keyboard.K_CASH: (self.numfield_enter, None),
                    keyboard.K_DOWN: (self.numfield_enter, None)})
        self.numfield.sethook = self.numfield_set
        self.stocktype_label = ui.label(3, 15, 45)
        self.problem_label = ui.label(4, 15, 45)
        if self.check:
            self.win.drawstr(6, 2, 13, "Checkdigits: ", align=">")
            self.checkfield = ui.editfield(
                6, 15, 3,
                keymap={keyboard.K_CASH: (self.checkfield_enter, None),
                        keyboard.K_CLEAR: (self.numfield.focus, None),
                        keyboard.K_UP: (self.numfield.focus, None)})
            self.checkfield.sethook = self.checkfield_set
            self.checkfield_status = ui.label(6, 19, 7)
        self.numfield.focus()

    def numfield_set(self):
        self.stocktype_label.set("")
        self.problem_label.set("")
        if self.numfield.f:
            stockid = int(self.numfield.f)
            item = td.s.get(StockItem, stockid,
                            options=[joinedload(StockItem.stocktype)])
            if item:
                self.stocktype_label.set(f"{item.stocktype}")
                not_ok = self.filter.item_problem(item)
                if not_ok:
                    self.problem_label.set(f"({not_ok})")

    def checkfield_set(self):
        self.checkfield_status.set("")
        if len(self.checkfield.f) != 3:
            return
        stockid = int(self.numfield.f)
        item = td.s.get(StockItem, stockid)
        self.checkfield_status.set(
            "(OK)" if item and item.checkdigits == self.checkfield.f
            else "(wrong)")

    def numfield_enter(self):
        if self.numfield.f:
            # Only advance if there's a valid stock item there
            stockid = int(self.numfield.f)
            item = self.filter.query_items()\
                              .filter(StockItem.id == stockid).first()
            if item:
                if self.check:
                    self.checkfield.focus()
                else:
                    self.dismiss()
                    self.func(item)
        else:
            if self.filter.is_single_department:
                self.popup_menu(None)
            else:
                depts = td.s.query(Department).order_by(Department.id).all()
                f = ui.tableformatter(' r l ')
                lines = [(f(d.id, d.description),
                          self.popup_menu, (d.id,)) for d in depts]
                ui.menu(lines, blurb="Choose the department the stock item "
                        "belongs to and press Cash/Enter:")

    def popup_menu(self, department_id):
        items = self.filter.query_items(department_id)\
                           .options(joinedload(StockItem.stocktype))\
                           .options(undefer(StockItem.remaining))[:100]
        f = ui.tableformatter(' r l c ')
        sl = [(f(s.id, s.stocktype.format(),
                 s.stocktype.unit.format_stock_qty(s.remaining)),
               self.item_chosen, (s.id,)) for s in items]
        ui.menu(sl, title=self.title)

    def item_chosen(self, stockid):
        # An item has been chosen from the popup menu
        self.numfield.set(str(stockid))
        if self.check:
            self.checkfield.set("")
        self.numfield_enter()

    def checkfield_enter(self):
        stockid = int(self.numfield.f)
        item = td.s.get(StockItem, stockid)
        if self.checkfield.f == item.checkdigits:
            self.dismiss()
            self.func(item)

    def linekey(self, kb):
        line = kb.stockline
        if len(line.stockonsale) == 0:
            return
        if len(line.stockonsale) == 1:
            item = line.stockonsale[0]
            problem = self.filter.item_problem(item)
            if problem:
                ui.infopopup(
                    [f"You can't choose {item.stocktype}: {problem}"],
                    title="Error")
                return
            self.item_chosen(item.id)
        else:
            ui.infopopup(
                [f"There's more than one stock item on sale on {line.name}"],
                title="Error")

    def keypress(self, k):
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.linekey)
        else:
            super().keypress(k)


class stockfield(ui.modelpopupfield):
    """Field that allows a stock item to be chosen.

    A field that allows a stock item to be chosen.  If
    check_checkdigits is True then manual entry of stock numbers will
    result in a checkdigits check; choosing stock items on sale on a
    stock line will skip the check.
    """
    def __init__(self, y, x, w, f=None, keymap={}, readonly=False,
                 filter=stockfilter(), check_checkdigits=True,
                 title="Choose stock item"):
        ui.modelpopupfield.__init__(
            self, y, x, w, StockItem, popupfunc=stockpicker,  # Pass on args?
            valuefunc=lambda x: f"{x.id}: {x.stocktype:.{w - 2 - len(str(x.id))}}",  # noqa: E501
            f=f, readonly=readonly, keymap=keymap)
        self.filter = filter
        self.check_checkdigits = check_checkdigits
        self.title = title

    def popup(self):
        # If we're popping up the stockpicker, it's because we want to
        # pick a different stock item!  Setting the current one as
        # default doesn't make sense - the user would just have to
        # press 'Clear' to get rid of it.
        if not self.readonly:
            stockpicker(self.setf, filter=self.filter,
                        check_checkdigits=self.check_checkdigits,
                        title=self.title)

    def linekey(self, kb):
        td.s.add(kb)
        line = kb.stockline
        if len(line.stockonsale) == 0:
            return
        if len(line.stockonsale) == 1:
            item = line.stockonsale[0]
            problem = self.filter.item_problem(item)
            if problem:
                ui.infopopup([f"You can't choose {item.stocktype}: {problem}"],
                             title="Error")
                return
            self.setf(item)
        else:
            ui.infopopup(
                [f"There's more than one stock item on sale on {line.name}"],
                title="Error")

    def keypress(self, k):
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.linekey)
        else:
            super().keypress(k)
