from . import ui, td, keyboard, user, tillconfig, linekeys, modifiers
from .models import PriceLookup, Department, KeyboardBinding
from sqlalchemy.exc import IntegrityError
from decimal import Decimal
import logging
log = logging.getLogger(__name__)


def _decimal_or_none(x):
    return Decimal(x) if x else None


class create(user.permission_checked, ui.dismisspopup):
    """Create a new price lookup.
    """
    permission_required = ('create-plu', 'Create a new price lookup')

    def __init__(self, func):
        super().__init__(12, 57, title="Create PLU",
                         colour=ui.colour_input,
                         dismiss=keyboard.K_CLEAR)
        self.func = func
        self.win.drawstr(2, 2, 13, "Description: ", align=">")
        self.win.drawstr(3, 2, 13, "Note: ", align=">")
        self.win.drawstr(4, 2, 13, "Department: ", align=">")
        self.win.wrapstr(6, 2, 53,
                         "The Note field may be looked at by modifier "
                         "keys; they may do different things depending on its "
                         "value.")
        self.descfield = ui.editfield(2, 15, 40, flen=160, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.notefield = ui.editfield(3, 15, 40, flen=160)
        self.deptfield = ui.modellistfield(
            4, 15, 20, Department, lambda q: q.order_by(Department.id),
            d=lambda x: x.description)
        self.createfield = ui.buttonfield(9, 23, 10, "Create", keymap={
            keyboard.K_CASH: (self.enter, None)})
        ui.map_fieldlist([self.descfield, self.notefield, self.deptfield,
                          self.createfield])
        self.descfield.focus()

    def enter(self):
        if self.descfield.f == '' or self.deptfield.read() is None:
            ui.infopopup(["You must enter values for Description and "
                          "Department."], title="Error")
            return
        p = PriceLookup(description=self.descfield.f,
                        note=self.notefield.f or "",
                        department=self.deptfield.read())
        td.s.add(p)
        try:
            td.s.flush()
            user.log(f"Created PLU {p.logref}")
        except IntegrityError:
            td.s.rollback()
            ui.infopopup(["There is already a PLU with this description."],
                         title="Error")
            return
        self.dismiss()
        if self.func == modify:
            self.func(p, focus_on_price=True)
        else:
            self.func(p)


class modify(user.permission_checked, ui.dismisspopup):
    permission_required = ('alter-plu',
                           'Modify or delete an existing price lookup')

    def __init__(self, p, focus_on_price=False):
        td.s.add(p)
        self.plu = p
        super().__init__(24, 58, title="Price Lookup",
                         colour=ui.colour_input,
                         dismiss=keyboard.K_CLEAR)
        self.win.drawstr(2, 2, 13, "Description: ", align=">")
        self.win.drawstr(3, 2, 13, "Note: ", align=">")
        self.win.drawstr(4, 2, 13, "Department: ", align=">")
        self.win.drawstr(5, 2, 13, "Price: ", align=">")
        self.win.addstr(5, 15, tillconfig.currency())
        self.win.drawstr(6, 2, 54, "Alternative prices:")
        self.win.addstr(7, 2, "       1: {c}         2: {c}         3: {c}"
                        .format(c=tillconfig.currency))
        self.descfield = ui.editfield(
            2, 15, 30, flen=160, f=self.plu.description,
            keymap={keyboard.K_CLEAR: (self.dismiss, None)})
        self.notefield = ui.editfield(
            3, 15, 30, flen=160, f=self.plu.note)
        self.deptfield = ui.modellistfield(
            4, 15, 20, Department, lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
            f=self.plu.department)
        self.pricefield = ui.editfield(
            5, 15 + len(tillconfig.currency()), 8,
            f=self.plu.price, validate=ui.validate_float)
        self.altprice1 = ui.editfield(
            7, 12 + len(tillconfig.currency()), 8,
            f=self.plu.altprice1, validate=ui.validate_float)
        self.altprice2 = ui.editfield(
            7, 24 + len(tillconfig.currency()) * 2, 8,
            f=self.plu.altprice2, validate=ui.validate_float)
        self.altprice3 = ui.editfield(
            7, 36 + len(tillconfig.currency()) * 3, 8,
            f=self.plu.altprice3, validate=ui.validate_float)
        self.savebutton = ui.buttonfield(9, 2, 8, "Save", keymap={
            keyboard.K_CASH: (self.save, None)})
        self.deletebutton = ui.buttonfield(9, 14, 10, "Delete", keymap={
            keyboard.K_CASH: (self.delete, None)})
        self.win.wrapstr(11, 2, 54, "The Note field and alternative prices "
                         "1-3 can be accessed by modifier keys.")
        self.win.drawstr(14, 2, 54, "To add a keyboard binding, press a "
                         "line key now.")
        self.win.wrapstr(15, 2, 54, "To edit or delete a keyboard binding, "
                         "choose it below and press Enter or Cancel.")
        self.kbs = ui.scrollable(19, 1, 56, 4, [], keymap={
            keyboard.K_CASH: (self.editbinding, None),
            keyboard.K_CANCEL: (self.deletebinding, None)})
        ui.map_fieldlist([self.descfield, self.notefield, self.deptfield,
                          self.pricefield, self.altprice1,
                          self.altprice2, self.altprice3,
                          self.savebutton, self.deletebutton, self.kbs])
        self.reload_bindings()
        if focus_on_price:
            self.pricefield.focus()
        else:
            self.descfield.focus()

    def keypress(self, k):
        # Handle keypresses that the fields pass up to the main popup
        if hasattr(k, 'line'):
            linekeys.addbinding(self.plu, k, self.reload_bindings,
                                modifiers.defined_modifiers())

    def save(self):
        td.s.add(self.plu)
        if self.descfield.f == '':
            ui.infopopup(["You may not make the description blank."],
                         title="Error")
            return
        if self.deptfield.read() is None:
            ui.infopopup(["You must specify a department."],
                         title="Error")
            return
        self.plu.description = self.descfield.f
        self.plu.note = self.notefield.f
        self.plu.department = self.deptfield.read()
        self.plu.price = _decimal_or_none(self.pricefield.f)
        self.plu.altprice1 = _decimal_or_none(self.altprice1.f)
        self.plu.altprice2 = _decimal_or_none(self.altprice2.f)
        self.plu.altprice3 = _decimal_or_none(self.altprice3.f)
        try:
            td.s.flush()
            user.log(f"Updated price lookup {self.plu.logref}")
        except IntegrityError:
            ui.infopopup(["You may not rename a price lookup to have the "
                          "same description as another price lookup."],
                         title="Duplicate price lookup error")
            return
        self.dismiss()
        ui.infopopup([f"Updated price lookup '{self.plu.description}'."],
                     colour=ui.colour_info,
                     dismiss=keyboard.K_CASH, title="Confirmation")

    def delete(self):
        self.dismiss()
        td.s.add(self.plu)
        user.log(f"Deleted price lookup {self.plu.logref}")
        td.s.delete(self.plu)
        td.s.flush()
        ui.infopopup(["The price lookup has been deleted."],
                     title="Price Lookup deleted", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def editbinding(self):
        if self.kbs.cursor is None:
            return
        line = self.kbs.dl[self.kbs.cursor]
        linekeys.changebinding(line.userdata, self.reload_bindings,
                               modifiers.defined_modifiers())

    def deletebinding(self):
        if self.kbs.cursor is None:
            return
        line = self.kbs.dl.pop(self.kbs.cursor)
        self.kbs.redraw()
        td.s.add(line.userdata)
        td.s.delete(line.userdata)
        td.s.flush()

    def reload_bindings(self):
        td.s.add(self.plu)
        f = ui.tableformatter(' l   c   l ')
        kbl = linekeys.keyboard_bindings_table(
            self.plu.keyboard_bindings, f)
        self.win.addstr(18, 1, " " * 56)
        self.win.addstr(18, 1, f("Line key", "Menu key", "Default modifier")
                        .display(56)[0])
        self.kbs.set(kbl)


class listunbound(user.permission_checked, ui.listpopup):
    """Pop up a list of price lookups with no key bindings on any keyboard.
    """
    permission_required = ('list-unbound-plus',
                           "List price lookups with no keyboard bindings")

    def __init__(self):
        l = td.s.query(PriceLookup)\
                .outerjoin(KeyboardBinding)\
                .filter(KeyboardBinding.pluid == None)\
                .all()
        if len(l) == 0:
            ui.infopopup(
                ["There are no price lookups that lack key bindings.",
                 "", "Note that other tills may have key bindings to "
                 "a price lookup even if this till doesn't."],
                title="Unbound price lookups", colour=ui.colour_info,
                dismiss=keyboard.K_CASH)
            return
        f = ui.tableformatter(' l l ')
        headerline = f("Description", "Note")
        self.ll = [f(x.description, x.note, userdata=x) for x in l]
        super().__init__(self.ll, title="Unbound price lookups",
                         colour=ui.colour_info, header=[headerline])

    def keypress(self, k):
        if k == keyboard.K_CASH:
            self.dismiss()
            modify(self.ll[self.s.cursor].userdata)
        else:
            super().keypress(k)


class selectplu(ui.listpopup):
    """Pop-up menu of price lookups

    A pop-up menu of price lookups, sorted by name.
    Price lookups with key bindings can be selected through that binding.

    Optional arguments:
      blurb - text for the top of the window
      create_new - allow a new price lookup to be created
      select_none - a string for a menu item which will result in a call
        to func(None)
    """
    def __init__(self, func, title="Price Lookups", blurb=None,
                 keymap={}, create_new=False, select_none=None):
        self.func = func
        plus = td.s.query(PriceLookup)\
                   .order_by(PriceLookup.dept_id)\
                   .order_by(PriceLookup.description)\
                   .all()
        f = ui.tableformatter(' l l r l ')
        self.ml = [f(x.description, x.note, tillconfig.fc(x.price),
                     x.department, userdata=x) for x in plus]
        self.create_new = create_new
        if create_new:
            self.ml.insert(0, ui.line(" New price lookup"))
        elif select_none:
            self.ml.insert(0, ui.line(f" {select_none}"))
        hl = [f("Description", "Note", "Price", "Department")]
        if blurb:
            hl = [ui.lrline(blurb), ui.emptyline()] + hl
        super().__init__(self.ml, title="Price Lookups", header=hl)

    def keypress(self, k):
        log.debug("plumenu keypress %s", k)
        if hasattr(k, 'line'):
            linekeys.linemenu(k, self.plu_selected, allow_stocklines=False,
                              allow_plus=True)
        elif hasattr(k, 'code'):
            if k.binding and k.binding.plu:
                self.plu_selected(k.binding)
            else:
                ui.beep()
        elif k == keyboard.K_CASH and len(self.ml) > 0:
            self.dismiss()
            line = self.ml[self.s.cursor]
            if line.userdata:
                self.func(line.userdata)
            else:
                if self.create_new:
                    create(self.func)
                else:
                    self.func(None)
        else:
            super().keypress(k)

    def plu_selected(self, kb):
        self.dismiss()
        td.s.add(kb)
        self.func(kb.plu)


def plumenu():
    """Menu allowing price lookups to be created, modified and deleted
    """
    selectplu(
        modify, blurb="Choose a price lookup to modify from the list below, "
        "or press a line key that is already bound to the "
        "price lookup.", create_new=True)
