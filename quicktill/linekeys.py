from . import keyboard, ui, td, user
from .models import KeyCap, KeyboardBinding, StockLine, PriceLookup
from sqlalchemy.sql import select, update

import logging
log = logging.getLogger(__name__)


def _complete_class(m):
    result = td.s.execute(
        select([KeyCap.css_class]).where(KeyCap.css_class.ilike(m + '%'))
    )
    return [x[0] for x in result]


def validate_class(s, c):
    t = s[: c + 1]
    l = _complete_class(t)
    if len(l) > 0:
        return l[0]
    # If a string one character shorter matches then we know we
    # filled it in last time, so we should return the string with
    # the rest chopped off rather than just returning the whole
    # thing unedited.
    if len(_complete_class(t[: -1])) > 0:
        return t
    return s


class edit_keycaps(user.permission_checked, ui.dismisspopup):
    """This popup window enables the keycaps of line keys to be edited.
    """
    permission_required = ('edit-keycaps',
                           'Change the names of keys on the keyboard')

    def __init__(self):
        super().__init__(11, 60, title="Edit Keycaps",
                         colour=ui.colour_input)
        self.win.drawstr(
            2, 2, 56,
            "Press a line key; alter the legend and press Cash/Enter.")
        self.win.drawstr(4, 2, 11, "Keycode: ", align=">")
        self.win.drawstr(5, 2, 11, "Legend: ", align=">")
        self.win.drawstr(6, 2, 11, "CSS class: ", align=">")
        self.keycode = None
        self.kclabel = ui.label(4, 13, 45)
        self.kcfield = ui.editfield(5, 13, 45)
        self.classfield = ui.editfield(6, 13, 45, validate=validate_class)
        self.savebutton = ui.buttonfield(8, 13, 10, "Save", keymap={
            keyboard.K_CASH: (self.setcap, None)})
        self.exitbutton = ui.buttonfield(8, 35, 10, "Exit", keymap={
            keyboard.K_CASH: (self.dismiss, None)})
        ui.map_fieldlist([self.kcfield, self.classfield, self.savebutton,
                          self.exitbutton])
        self.kcfield.focus()

    def clear(self):
        self.kclabel.set("")
        self.kcfield.set("")
        self.classfield.set("")

    def selectline(self, linekey):
        self.kclabel.set(linekey.name)
        self.kcfield.set(linekey.keycap)
        self.classfield.set(linekey.css_class)
        self.keycode = linekey
        self.kcfield.focus()

    def setcap(self):
        if self.keycode is None:
            return
        newcap = KeyCap(keycode=self.keycode.name,
                        keycap=self.kcfield.f, css_class=self.classfield.f)
        td.s.merge(newcap)
        td.s.flush()
        self.clear()
        self.exitbutton.focus()

    def keypress(self, k):
        if hasattr(k, 'line'):
            self.selectline(k)
        else:
            super().keypress(k)


def keyboard_bindings_table(bindings, formatter):
    """Given a list of keyboard bindings, from the database, format a
    table to show them.
    """
    f = formatter
    for b in bindings:
        if b.keycode not in keyboard.__dict__:
            keyboard.keycode(b.keycode, b.keycode)
            log.warning(f"Keyboard binding {b}: keycode {b.keycode} "
                        f"does not exist.")
    kbl = [f(str(keyboard.__dict__[x.keycode]),
             str(keyboard.__dict__.get(x.menukey, x.menukey)),
             x.modifier, userdata=x) for x in bindings]
    return kbl


class addbinding(ui.listpopup):
    """Add a binding for a stockline, PLU or modifier to the database.
    """
    def __init__(self, target, keycode, func, available_modifiers=None):
        self.func = func
        self.target = target
        self.available_modifiers = available_modifiers
        if isinstance(target, StockLine) or isinstance(target, PriceLookup):
            td.s.add(target)
        self.name = target.name
        self.keycode = keycode
        existing = td.s.query(KeyboardBinding)\
                       .filter(KeyboardBinding.keycode == self.keycode.name)\
                       .all()
        self.exdict = {}
        lines = []
        f = ui.tableformatter(' l l l   c ')
        if len(existing) > 0:
            lines = [
                ui.emptyline(),
                ui.lrline(f"The '{keycode.keycap}' key already has some other "
                          "stock lines, PLUs or modifiers associated "
                          "with it; they are listed below."),
                ui.emptyline(),
                ui.lrline("When the key is pressed, a menu will be displayed "
                          "enabling the till user to choose between them.  "
                          "You must now choose which key the user must press "
                          f"to select '{self.name}'; make sure it isn't "
                          "already in the list!"),
                ui.emptyline(),
                f('Menu key', '', 'Name', 'Default modifier'),
            ]
        else:
            lines = [
                ui.emptyline(),
                ui.lrline("There are no other options on the "
                          f"'{keycode.keycap}' key, "
                          "so when it's used there will be no need "
                          "for a menu to be displayed.  However, in case "
                          "you add more options to the key in the future, "
                          "you must now choose which key the user will have "
                          f"to press to select '{self.name}'."),
                ui.emptyline(),
                ui.lrline("Pressing '1' now is usually the right thing to do!"),
            ]
        existing.sort(key=lambda x: str(
            keyboard.__dict__.get(x.menukey, x.menukey)))
        for kb in existing:
            keycode = keyboard.__dict__.get(kb.menukey, kb.menukey)
            lines.append(
                f(str(keycode), '->', kb.name, kb.modifier))
            self.exdict[keycode] = None
        lines.append(ui.emptyline())
        lines = [ui.marginline(x, margin=1) for x in lines]
        super().__init__(
            lines, title=f"Add keyboard binding for {self.name}",
            colour=ui.colour_input, show_cursor=False, w=58)

    def keypress(self, k):
        if k == keyboard.K_CLEAR:
            self.dismiss()
            return self.func()
        if k in keyboard.cursorkeys:
            return super().keypress(k)
        if k in self.exdict:
            return
        if isinstance(self.target, StockLine):
            args = {'stockline': self.target}
        elif isinstance(self.target, PriceLookup):
            args = {'plu': self.target}
        else:
            args = {'modifier': self.target.name}
        binding = KeyboardBinding(
            keycode=self.keycode.name,
            menukey=k.name if hasattr(k, 'name') else k,
            **args)
        td.s.add(binding)
        td.s.flush()
        self.dismiss()
        if self.available_modifiers:
            changebinding(binding, self.func, self.available_modifiers)
        else:
            self.func()


def changebinding(binding, func, available_modifiers):
    """Enable the default modifier on the binding to be changed.
    """
    td.s.add(binding)
    blurb = [
        "",
        f"Choose the new default modifier for {binding.name} "
        f"when accessed through {keyboard.__dict__[binding.keycode].keycap} "
        f"option {keyboard.__dict__.get(binding.menukey, binding.menukey)}.",
    ]
    ml = [(name, _finish_changebinding, (binding, func, name))
          for name in available_modifiers]
    ml = [("No modifier", _finish_changebinding, (binding, func, None))] + ml
    ui.automenu(ml, title="Choose default modifier", blurb=blurb)


def _finish_changebinding(binding, func, mod):
    td.s.add(binding)
    binding.modifier = mod
    func()


class move_keys(user.permission_checked, ui.dismisspopup):
    permission_required = ('move-keys',
                           'Change the positions of keys on the keyboard')

    def __init__(self):
        super().__init__(10, 60, title="Move keys", colour=ui.colour_input)
        self.win.set_cursor(False)
        y = 2
        y += self.win.wrapstr(
            2, 2, 56,
            "Keys are moved by swapping one key with another.  "
            "Press one key followed by another and they will be "
            "swapped.  Press Clear when you are finished.")
        y += 1
        self.label = ui.label(y, 2, 56)
        self.reset()

    def reset(self):
        self.key = None
        self.label.set("Push the first key now.")

    def linekey(self, k):
        if self.key:
            self.swap(k)
        else:
            self.key = k
            self.label.set(f"Push the key to swap with {k.keycap}")

    def swap(self, k):
        ui.toast(f"{str(self.key) or '(unlabeled)'} swapped "
                 f"with {str(k) or '(unlabeled)'}")
        # The keycode is (part of) the primary key and the key is not
        # set as deferrable, so we have to swap using an intermediate
        # value.  This occurs within a transaction so will never be
        # visible to other database clients.
        td.s.execute(
            update(KeyboardBinding)
            .where(KeyboardBinding.keycode == self.key.name)
            .values(keycode="swapping"))
        td.s.execute(
            update(KeyboardBinding)
            .where(KeyboardBinding.keycode == k.name)
            .values(keycode=self.key.name))
        td.s.execute(
            update(KeyboardBinding)
            .where(KeyboardBinding.keycode == "swapping")
            .values(keycode=k.name))
        td.s.execute(
            update(KeyCap)
            .where(KeyCap.keycode == self.key.name)
            .values(keycode="swapping"))
        td.s.execute(
            update(KeyCap)
            .where(KeyCap.keycode == k.name)
            .values(keycode=self.key.name))
        td.s.execute(
            update(KeyCap)
            .where(KeyCap.keycode == "swapping")
            .values(keycode=k.name))
        # Ensure that BOTH keycaps have been notified, even if there's no
        # database keycap record for one or the other of them
        td.s.execute(f"notify keycaps, '{self.key.name}'")
        td.s.execute(f"notify keycaps, '{k.name}'")
        self.reset()

    def keypress(self, k):
        if hasattr(k, "line"):
            self.linekey(k)
        elif k == keyboard.K_CLEAR and self.key:
            self.reset()
        else:
            super().keypress(k)


def linemenu(keycode, func, allow_stocklines=True, allow_plus=False,
             allow_mods=False, add_query_options=None,
             suppress_modifier_display=False):
    """Resolve a keycode to a keyboard binding

    Given a keycode, find out what is bound to it.  If there's more
    than one thing, pop up a menu to select a particular binding.
    Call func with the keyboard binding as an argument when a
    selection is made.  No call is made if Clear is pressed.  If
    there's only one keyboard binding in the list, shortcut to the
    function.

    This function returns the number of keyboard bindings found.  Some
    callers may wish to use this to inform the user that a key has no
    bindings rather than having an uninformative empty menu pop up.
    """
    kb = td.s.query(KeyboardBinding)\
             .filter(KeyboardBinding.keycode == keycode.name)
    if not allow_stocklines:
        kb = kb.filter(KeyboardBinding.stocklineid == None)
    if not allow_plus:
        kb = kb.filter(KeyboardBinding.pluid == None)
    if not allow_mods:
        kb = kb.filter((KeyboardBinding.stocklineid != None)
                       | (KeyboardBinding.pluid != None))
    if add_query_options:
        kb = add_query_options(kb)
    kb = kb.all()

    if len(kb) == 1:
        func(kb[0])
    elif len(kb) > 1:
        il = sorted(
            [(keyboard.__dict__.get(x.menukey, x.menukey),
              f"{x.name} ({x.modifier})" if x.modifier
              and (x.stockline or x.plu)
              and not suppress_modifier_display
              else x.name,
              _linemenu_chosen,
              (x.keycode, x.menukey, func, add_query_options))
             for x in kb], key=lambda x: str(x[0]))
        ui.keymenu(il, title=keycode.keycap, colour=ui.colour_line)
    return len(kb)


def _linemenu_chosen(keycode, menukey, func, add_query_options):
    kb = td.s.query(KeyboardBinding)\
             .filter(KeyboardBinding.keycode == keycode)\
             .filter(KeyboardBinding.menukey == menukey)
    if add_query_options:
        kb = add_query_options(kb)
    kb = kb.one_or_none()
    if kb:
        func(kb)
