"""Create and modify stocktypes."""

import logging
log = logging.getLogger(__name__)
from . import ui, td, keyboard, tillconfig, user
from .models import Department, UnitType, StockType, StockItem, Delivery, penny
from .plugins import ClassPluginMount
from decimal import Decimal
import datetime

class choose_stocktype(ui.dismisspopup):
    """Select/modify a stock type.  Has two modes:

    1) Select a stock type. Auto-completes fields as they are typed
       at, hopefully to find a match with an existing stock type.
       (After selecting manufacturer/name, other fields are filled in
       if possible, but can still be edited.)  If, when form is
       completed, there is no match with an existing stock type, a new
       stock type will be created, provided "allownew" is set.  (This
       is the only way to create stock types.)

    2) Modify a stock type.  Allows all details of an existing stock
       type to be changed.  Has major warnings - should only be used
       for correcting minor typos!
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
            blurb1 = "Enter stock details and then press"
            blurb2 = "Cash/Enter on the [Select] button."
        elif mode == 2:
            prompt = "Save Changes"
            title = "Edit Stock Type"
            blurb1 = "NOTE: make minor corrections only; changes"
            blurb2 = "affect all stock items of this type!"
        else:
            raise Exception("Bad mode")
        self.st = default.id if default else None
        ui.dismisspopup.__init__(self, 15, 48, title=title,
                                 colour=ui.colour_input)
        self.addstr(2, 2, blurb1)
        self.addstr(3, 2, blurb2)
        self.addstr(5, 2, "Manufacturer:")
        self.addstr(6, 2, "        Name:")
        self.addstr(7, 2, "  Short name:")
        self.addstr(8, 2, "  Department:")
        self.addstr(8, 38, "ABV:")
        self.addstr(9, 2, "        Unit:")
        self.addstr(13, 2, "'Short Name' may be printed on receipts.")
        self.manufield = ui.editfield(
            5, 16, 30,
            validate=self.autocomplete_manufacturer if mode == 1 else None,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.namefield = ui.editfield(
            6, 16, 30,
            validate=self.autocomplete_name if mode == 1 else None)
        self.snamefield = ui.editfield(7, 16, 25)
        self.deptfield = ui.modellistfield(
            8, 16, 20, Department,
            lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
            readonly=(mode == 2))
        self.abvfield = ui.editfield(8, 42, 4, validate=ui.validate_float)
        self.unitfield = ui.modellistfield(
            9, 16, 30, UnitType,
            lambda q: q.order_by(UnitType.id),
            d=lambda x: x.name,
            readonly=(mode == 2))
        self.confirmbutton = ui.buttonfield(11, 15, 20, prompt, keymap={
            keyboard.K_CASH: (self.finish_select if mode == 1
                              else self.finish_update, None)})
        ui.map_fieldlist(
            [self.manufield, self.namefield, self.snamefield, self.deptfield,
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
        self.snamefield.set(st.shortname)
        self.deptfield.set(st.department)
        self.abvfield.set(st.abv)
        self.unitfield.set(st.unit)

    def validate_fields(self):
        "Returns True or None."
        if not self.deptfield.read():
            return None
        if not self.unitfield.read():
            return None
        if len(self.snamefield.f) == 0:
            return None
        if len(self.manufield.f) == 0:
            return None
        if len(self.namefield.f) == 0:
            return None
        return True

    def get_abv(self):
        try:
            return float(self.abvfield.f)
        except:
            return None

    def update_model(self, model):
        model.manufacturer = self.manufield.f.strip()
        model.name = self.namefield.f.strip()
        model.shortname = self.snamefield.f.strip()
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

        l = td.s.query(StockType).\
            filter(StockType.manufacturer.ilike(
                '%{}%'.format(self.manufield.f.strip()))).\
            filter(StockType.name.ilike(
                '%{}%'.format(self.namefield.f.strip()))).\
            order_by(StockType.manufacturer, StockType.name,
                     StockType.dept_id).\
            all()
        if len(l) == 1:
            self.existing_stocktype_chosen(l[0].id)
            return
        if len(l) == 0:
            proposed_short_name = "{} {}".format(
                self.manufield.f.strip(), self.namefield.f.strip())
            if len(proposed_short_name) <= 25:
                self.snamefield.set(proposed_short_name)
            self.snamefield.focus()
            return
        f = ui.tableformatter(' l l l l l l ')
        header = f("Manufacturer", "Name", "Short name", "ABV", "Unit",
                   "Department")
        lines = [(f(st.manufacturer, st.name, st.shortname, st.abv,
                    st.unit.name, st.department.description),
                  self.existing_stocktype_chosen, (st.id,)) for st in l]

        ui.menu(lines, blurb=header, title="Choose existing stock type")

    def existing_stocktype_chosen(self, stocktype):
        st = td.s.query(StockType).get(stocktype)
        self.fill_fields(st)
        self.confirmbutton.focus()

    def finish_save(self):
        self.dismiss()
        st = StockType()
        self.update_model(st)
        td.s.add(st)
        td.s.flush() # ensures the model has an identity
        self.func(st)

    def finish_select(self):
        # If there's an exact match then return the existing stock
        # type.  Otherwise pop up a confirmation box asking whether we
        # can create a new one.
        if self.validate_fields() is None:
            ui.infopopup(["You must fill in all the fields (except ABV, "
                          "which should be left blank for non-alcoholic "
                          "stock types)."], title="Error")
            return
        st = td.s.query(StockType).\
            filter_by(manufacturer=self.manufield.f).\
            filter_by(name=self.namefield.f).\
            filter_by(shortname=self.snamefield.f).\
            filter_by(abv=self.get_abv()).\
            filter_by(unit=self.unitfield.read()).\
            filter_by(department=self.deptfield.read()).\
            first()
        # Confirmation box time...
        if st is None:
            if self.allownew:
                ui.infopopup(["There's no existing stock type that matches the "
                              "details you've entered.  Press Cash/Enter to "
                              "create a new stock type, or Clear to go back."],
                             title="New Stock Type?", keymap={
                        keyboard.K_CASH: (self.finish_save, None, True)})
            else:
                ui.infopopup(["There is no stock type that matches the "
                              "details you have entered."],
                              title="No Match")
                return
        else:
            self.dismiss()
            self.func(st)

    def finish_update(self):
        if self.validate_fields() is None:
            ui.infopopup(["You are not allowed to leave any field other "
                          "than ABV blank."], title="Error")
        else:
            self.dismiss()
            st = td.s.query(StockType).get(self.st)
            self.update_model(st)

class reprice_stocktype(user.permission_checked,ui.dismisspopup):
    """Allow the sale price to be changed on a particular StockType.

    Shows a list of items that are currently in stock and their
    suggested sale prices, worked out from their cost prices.
    """
    permission_required = ('reprice-stock', 'Change the sale price of stock')
    # The code in register.py mentions this permission explicitly.

    def __init__(self, st):
        """We are passed a StockType that may not be in the current session."""
        mh, mw = ui.rootwin.size()
        self.st = st
        td.s.add(st)
        name = st.format()
        sl = td.s.query(StockItem)\
                 .filter(StockItem.stocktype==st)\
                 .join(Delivery)\
                 .filter(Delivery.checked==True)\
                 .filter(StockItem.finished==None)\
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
                x.stockunit.size, x.remaining,
                PriceGuessHook.guess_price(
                    x.stocktype, x.stockunit, x.costprice))
              for x in sl]
        w = min(max(f.idealwidth() + 2, len(name) + 4, 30), mw)
        ui.dismisspopup.__init__(self, h, w, title="Re-price {}".format(name),
                                 colour=ui.colour_input)
        self.addstr(2, 2, "Sale price: {}".format(tillconfig.currency))
        self.salefield = ui.editfield(
            2, 14 + len(tillconfig.currency), 6, validate=ui.validate_float,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.salefield.set(st.saleprice)
        self.addstr(2, 21 + len(tillconfig.currency), "per")
        self.unitsfield = ui.editfield(2, 25 + len(tillconfig.currency), 6,
                                       validate=ui.validate_float)
        self.unitsfield.set(st.saleprice_units)
        self.addstr(2, 32 + len(tillconfig.currency), "{}s".format(
            st.unit.name))
        self.addstr(4, 1, headerline.display(w - 2)[0])
        s = ui.scrollable(5, 1, w - 2, h - 6, dl=ll, show_cursor=False)
        self.unitsfield.keymap[keyboard.K_CASH] = (self.reprice, None)
        ui.map_fieldlist([self.salefield, self.unitsfield, s])
        self.salefield.focus()

    def reprice(self):
        if len(self.salefield.f) == 0:
            ui.infopopup(["You must specify a sale price."],
                         title="Error")
            return
        if len(self.unitsfield.f) == 0:
            ui.infopopup(["You must specify the number of units sold "
                          "for the sale price."],
                         title="Error")
            return
        newunits = Decimal(self.unitsfield.f)
        if newunits < 1:
            ui.infopopup(["You must sell at least one unit of stock "
                          "for the sale price."],
                         title="Error")
            return
        self.dismiss()
        td.s.add(self.st)
        oldprice = self.st.saleprice
        oldunits = self.st.saleprice_units
        self.st.saleprice = Decimal(self.salefield.f).quantize(penny)
        self.st.saleprice_units = newunits
        if self.st.saleprice != oldprice \
           or self.st.saleprice_units != oldunits:
            self.st.pricechanged = datetime.datetime.now()
            td.s.flush()
            ui.infopopup(["Price of {} changed to {}{}.".format(
                self.st.format(), tillconfig.currency, self.st.pricestr)],
                         title="Price changed",
                         colour=ui.colour_info,
                         dismiss=keyboard.K_CASH)

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
