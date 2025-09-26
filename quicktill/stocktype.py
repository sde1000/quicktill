"""Create and modify stocktypes."""

import logging
from . import ui, td, keyboard, tillconfig, user
from .models import Department, Unit, StockType, StockItem, Delivery, penny
from .plugins import ClassPluginMount
from decimal import Decimal
log = logging.getLogger(__name__)


class TempStockUnit:
    """StockUnit-compatible class that is not persisted to the database

    This is used when passing a StockUnit that potentially does not
    exist in the database to the PriceGuess hook.
    """
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class choose_stocktype(ui.dismisspopup):
    """Select/modify a stock type.  Has two modes:

    1) Select a stock type. Auto-completes fields as they are typed
       at, hopefully to find a match with an existing stock type.
       (After selecting manufacturer/name, other fields are filled in
       if possible, but can still be edited.)  If, when form is
       completed, there is no match with an existing stock type, a new
       stock type will be created, provided "allownew" is set.  (This
       is the only way to create stock types through the till
       client. It is also possible to create stock types through the
       web interface.)

    2) Modify a stock type.  Allows all details of an existing stock
       type to be changed.  Has major warnings - should only be used
       for correcting minor typos!

    If an archived stock type is matched, the stock type note will be
    displayed and the stock type will not be returned.
    """
    def __init__(self, func, default=None, mode=1, allownew=True):
        """default, if present, is a models.StockType object.
        """
        self.func = func
        self.mode = mode
        self.allownew = allownew
        if mode == 1:
            prompt = "Select"
            title = "Select Stock Type"
            blurb = "Enter stock details and then press " \
                    "Cash/Enter on the [Select] button."
        elif mode == 2:
            prompt = "Save Changes"
            title = "Edit Stock Type"
            blurb = "NOTE: make corrections only; changes " \
                    "affect all stock items of this type!"
        else:
            raise Exception("Bad mode")
        self.st = default.id if default else None
        super().__init__(13, 48, title=title, colour=ui.colour_input)
        self.win.wrapstr(2, 2, 44, blurb)
        self.win.drawstr(5, 2, 14, "Manufacturer: ", align=">")
        self.win.drawstr(6, 2, 14, "Name: ", align=">")
        self.win.drawstr(7, 2, 14, "Department: ", align=">")
        self.win.drawstr(7, 37, 5, "ABV: ", align=">")
        self.win.drawstr(8, 2, 14, "Unit: ", align=">")
        self.manufield = ui.editfield(
            5, 16, 30,
            validate=self.autocomplete_manufacturer if mode == 1 else None,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.namefield = ui.editfield(
            6, 16, 30,
            validate=self.autocomplete_name if mode == 1 else None)
        self.deptfield = ui.modellistfield(
            7, 16, 20, Department,
            lambda q: q.order_by(Department.id),
            d=lambda x: x.description)
        self.abvfield = ui.editfield(7, 42, 4, validate=ui.validate_float)
        self.unitfield = ui.modellistfield(
            8, 16, 30, Unit,
            lambda q: q.order_by(Unit.description),
            d=lambda x: x.description,
            readonly=(mode == 2))
        self.confirmbutton = ui.buttonfield(10, 15, 20, prompt, keymap={
            keyboard.K_CASH: (self.finish_select if mode == 1
                              else self.finish_update, None)})
        ui.map_fieldlist(
            [self.manufield, self.namefield, self.deptfield,
             self.abvfield, self.unitfield, self.confirmbutton])
        if default:
            self.fill_fields(default)
        if mode == 1:
            self.manufield.keymap[keyboard.K_CASH] = (self.manuf_enter, None)
            self.namefield.keymap[keyboard.K_CASH] = (self.name_enter, None)
        self.manufield.focus()

    def fill_fields(self, st):
        "Fill all fields from the specified stock type"
        self.manufield.set(st.manufacturer)
        self.namefield.set(st.name)
        self.deptfield.set(st.department)
        self.abvfield.set(st.abv)
        self.unitfield.set(st.unit)

    def validate_fields(self, ignore_abv_problems=False):
        """Returns a string describing the problem, or None if all valid
        """
        if len(self.manufield.f) == 0:
            return "You must specify a manufacturer"
        if len(self.namefield.f) == 0:
            return "You must specify a name"
        dept = self.deptfield.read()
        if not dept:
            return "You must specify a department"
        if not self.unitfield.read():
            return "You must specify a unit"
        if ignore_abv_problems:
            return
        abv = self.get_abv()
        if dept.minabv is not None:
            if abv is None or abv < dept.minabv:
                return f"You must specify an ABV of at least {dept.minabv}%"
        if dept.maxabv is not None and abv is not None and abv > dept.maxabv:
            return f"You may specify an ABV of at most {dept.maxabv}%"

    def get_abv(self):
        try:
            return Decimal(self.abvfield.f)
        except Exception:
            return None

    def update_model(self, model):
        model.manufacturer = self.manufield.f.strip()
        model.name = self.namefield.f.strip()
        model.abv = self.get_abv()
        model.department = self.deptfield.read()
        model.unit = self.unitfield.read()

    def autocomplete_manufacturer(self, s, c):
        t = s[:c + 1]
        l = td.stocktype_completemanufacturer(t)
        if len(l) > 0:
            return l[0]
        # If a string one character shorter matches then we know we
        # filled it in last time, so we should return the string with
        # the rest chopped off rather than just returning the whole
        # thing unedited.
        if len(td.stocktype_completemanufacturer(t[:-1])) > 0:
            return t
        return s

    def autocomplete_name(self, s, c):
        t = s[:c + 1]
        l = td.stocktype_completename(self.manufield.f, t)
        if len(l) > 0:
            return l[0]
        if len(td.stocktype_completename(self.manufield.f, t[:-1])) > 0:
            return t
        return s

    def manuf_enter(self):
        # Called when Enter is pressed on the manufacturer field.
        # Look up possible names for this manufacturer, and if there
        # is exactly one then pre-fill the name field.
        l = td.stocktype_completename(self.manufield.f, "")
        if len(l) == 1:
            self.namefield.set(l[0])
        self.namefield.focus()

    def name_enter(self):
        # Called when Enter is pressed on the Name field.  Finds
        # possible existing StockTypes based on a fuzzy match with the
        # manufacturer and the name.

        l = td.s.query(StockType)\
                .filter(StockType.manufacturer.ilike(
                    f'%{self.manufield.f.strip()}%'))\
                .filter(StockType.name.ilike(
                    f'%{self.namefield.f.strip()}%'))\
                .filter(StockType.archived == False)\
                .order_by(StockType.manufacturer, StockType.name,
                          StockType.dept_id)\
                .all()
        if len(l) == 1:
            self.existing_stocktype_chosen(l[0].id)
            return
        if len(l) == 0:
            self.deptfield.focus()
            return
        f = ui.tableformatter(' l l l l l ')
        header = f("Manufacturer", "Name", "ABV", "Unit", "Department")
        lines = [(f(st.manufacturer, st.name, st.abv,
                    st.unit.description, st.department.description),
                  self.existing_stocktype_chosen, (st.id,)) for st in l]

        ui.menu(lines, blurb=header, title="Choose existing stock type")

    def existing_stocktype_chosen(self, stocktype):
        st = td.s.get(StockType, stocktype)
        self.fill_fields(st)
        self.confirmbutton.focus()

    def finish_save(self):
        self.dismiss()
        st = StockType()
        self.update_model(st)
        td.s.add(st)
        td.s.flush()  # ensures the model has an identity
        user.log(f"Created stock type {st.logref}")
        self.func(st)

    def finish_select(self):
        # If there's an exact match then return the existing stock
        # type.  Otherwise pop up a confirmation box asking whether we
        # can create a new one.

        # Existing stock types may not pass ABV validation. We still
        # need to be able to select them.
        problem = self.validate_fields(ignore_abv_problems=True)
        if problem:
            ui.infopopup([problem], title="Error")
            return

        st = td.s.query(StockType).\
            filter_by(manufacturer=self.manufield.f).\
            filter_by(name=self.namefield.f).\
            filter_by(abv=self.get_abv()).\
            filter_by(unit=self.unitfield.read()).\
            filter_by(department=self.deptfield.read()).\
            first()
        # Confirmation box time...
        if st is None:
            if self.allownew:
                # Re-check, including checking the ABV this time
                problem = self.validate_fields()
                if problem:
                    ui.infopopup([problem], title="Error")
                    return
                ui.infopopup(
                    ["There's no existing stock type that matches the "
                     "details you've entered.  Press Cash/Enter to "
                     "create a new stock type, or Clear to go back."],
                    title="New Stock Type?", keymap={
                        keyboard.K_CASH: (self.finish_save, None, True)})
            else:
                ui.infopopup(
                    ["There is no stock type that matches the "
                     "details you have entered."],
                    title="No Match")
                return
        elif st.archived:
            ui.infopopup(
                [f"{st} has been archived, and "
                 f"is not available for use. The reason recorded for this is:",
                 "",
                 st.note or "(blank)",
                 "",
                 "If you need to restore this stock type, you can do so "
                 "through the web interface."],
                title="Stock type archived")
            return
        else:
            self.dismiss()
            self.func(st)

    def finish_update(self):
        problem = self.validate_fields()
        if problem:
            ui.infopopup([problem], title="Error")
        else:
            self.dismiss()
            st = td.s.get(StockType, self.st)
            self.update_model(st)
            user.log(f"Updated stock type {st.logref}")


class reprice_stocktype(user.permission_checked, ui.dismisspopup):
    """Allow the sale price to be changed on a particular StockType.

    Shows a list of items that are currently in stock and their
    suggested sale prices, worked out from their cost prices.
    """
    permission_required = ('reprice-stock', 'Change the sale price of stock')
    # The code in register.py mentions this permission explicitly.

    def __init__(self, st):
        """We are passed a StockType that may not be in the current session."""
        mh, mw = ui.rootwin.size()
        td.s.add(st)
        self.st_id = st.id
        name = st.format()
        sl = td.s.query(StockItem)\
                 .filter(StockItem.stocktype == st)\
                 .join(Delivery)\
                 .filter(Delivery.checked == True)\
                 .filter(StockItem.finished == None)\
                 .order_by(StockItem.id)\
                 .all()

        # The height includes 2 lines for top and bottom borders, 3
        # lines for entry field for price, one line for the scrollable
        # list header and the remainder for the scrollable list of
        # guide prices.
        h = min(6 + len(sl), mh - 1)
        f = ui.tableformatter(' r c c c c c ')
        headerline = f("StockID", "Delivered", "Cost", "Size", "Remaining",
                       "Guide price")
        ll = [f(x.id, x.delivery.date, tillconfig.fc(x.costprice),
                x.size, x.remaining,
                tillconfig.fc(PriceGuessHook.guess_price(
                    x.stocktype,
                    TempStockUnit(name=x.description,
                                  unit_id=x.stocktype.unit_id,
                                  size=x.size,
                                  unit=x.stocktype.unit),
                    x.costprice)))
              for x in sl]
        w = min(max(f.idealwidth() + 2, len(name) + 4, 30), mw)
        super().__init__(h, w, title=f"Re-price {name}",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 12, "Sale price: ", align=">")
        self.win.addstr(2, 14, tillconfig.currency())
        self.salefield = ui.editfield(
            2, 14 + len(tillconfig.currency()), 6, validate=ui.validate_float,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.salefield.set(st.saleprice)
        self.win.drawstr(2, 21 + len(tillconfig.currency()),
                         w - 22 - len(tillconfig.currency()),
                         f"per {st.unit.sale_unit_name}")
        self.win.addstr(4, 1, headerline.display(w - 2)[0])
        s = ui.scrollable(5, 1, w - 2, h - 6, dl=ll, show_cursor=False)
        self.salefield.keymap[keyboard.K_CASH] = (self.reprice, None)
        ui.map_fieldlist([self.salefield, s])
        self.salefield.focus()

    def reprice(self):
        if len(self.salefield.f) == 0:
            ui.infopopup(["You must specify a sale price."],
                         title="Error")
            return
        self.dismiss()
        st = td.s.get(StockType, self.st_id)
        oldprice = st.saleprice
        st.saleprice = Decimal(self.salefield.f).quantize(penny)
        if st.saleprice != oldprice:
            user.log(
                f"Changed sale price of {st.logref} from "
                f"{tillconfig.fc(oldprice)} to {tillconfig.fc(st.saleprice)}")
            td.s.flush()
            ui.infopopup([f"Price of {st} changed to "
                          f"{tillconfig.currency}{st.pricestr}."],
                         title="Price changed",
                         colour=ui.colour_info,
                         dismiss=keyboard.K_CASH)


class stocktypefield(ui.modelpopupfield):
    def __init__(self, y, x, w, f=None, keymap={}, readonly=False):
        super().__init__(y, x, w, StockType, choose_stocktype,
                         format, f=f, keymap=keymap, readonly=readonly)

    def keypress(self, k):
        if hasattr(k, 'code'):
            if k.binding and k.binding.stocktype:
                self.setf(k.binding.stocktype)
            else:
                k.feedback(False)
                ui.beep()
        else:
            super().keypress(k)


class PriceGuessHook(metaclass=ClassPluginMount):
    """Subclass this to add a price guessing routine.
    """
    @staticmethod
    def guess_price(stocktype, stockunit, cost):
        for p in PriceGuessHook.plugins:
            g = None
            with ui.exception_guard("running guess_price hook"):
                g = p.guess_price(stocktype, stockunit, cost)
            if g:
                return g
