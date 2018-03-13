"""Price lookup window."""

from . import td
from . import ui
from . import keyboard
from . import stock
from . import linekeys
from . import user
from . import modifiers
from . import tillconfig

class pricecheck_keypress:
    """Process line key presses.

    This class is a mixin for the various classes used by the price
    lookup user interface; it provides preprocessing of keypresses to
    spot line key presses.
    """
    def keypress(self, k):
        if hasattr(k, "line"):
            self.dismiss()
            bindings = linekeys.linemenu(
                k, pricecheck_window, allow_stocklines=True, allow_plus=True,
                allow_mods=True)
            if bindings == 0:
                popup(prompt="There are no options on key \"{}\".  Press "
                      "another line key.".format(k.keycap))
        else:
            super().keypress(k)

class popup(user.permission_checked, pricecheck_keypress, ui.infopopup):
    permission_required = ("price-check",
                           "Check prices without selling anything")
    def __init__(self, prompt="Press a line key."):
        super().__init__([prompt], title="Price Check",
                         dismiss=keyboard.K_CASH, colour=ui.colour_info)

class pricecheck_display_stockline(pricecheck_keypress, ui.menu):
    """Display stockline -> display menu of items on sale on that line."""
    def __init__(self, stockline):
        sos = stockline.stockonsale
        f = ui.tableformatter(' r r+l ')
        sl = [(f(x.id, x.ondisplay, x.instock),
               stock.stockinfo_popup, (x.id,)) for x in sos]
        blurb = ["This line sells {} at {}{}.".format(
            stockline.stocktype.format(),
            tillconfig.currency,
            stockline.stocktype.pricestr),
                 "",
                 "There are {} {}s on display and {} in stock.".format(
                     stockline.ondisplay, stockline.stocktype.unit.name,
                     stockline.instock),
                 "", "Choose a stock item for more information, or "
                 "press another line key.",
        ]
        super().__init__(
            sl, title="{} ({}) - display capacity {}".format(
                stockline.name, stockline.location, stockline.capacity),
            blurb=blurb,
            colour=ui.colour_info,
            dismiss_on_select=False)

class pricecheck_continuous_stockline(pricecheck_keypress, ui.menu):
    """Continuous stockline -> display menu of all items of appropriate type."""
    def __init__(self, stockline):
        sos = stockline.continuous_stockonsale()
        f = ui.tableformatter(' r r ')
        sl = [(f(x.id, x.remaining), stock.stockinfo_popup, (x.id,))
              for x in sos]
        blurb = ["This line sells {} at {}{}.".format(
            stockline.stocktype.format(),
            tillconfig.currency,
            stockline.stocktype.pricestr),
                 "",
                 "There are {} {}s remaining in stock.".format(
                     stockline.remaining, stockline.stocktype.unit.name),
                 "", "Choose a stock item for more information, or "
                 "press another line key.",
        ]
        super().__init__(
            sl, title="{} ({})".format(
                stockline.name, stockline.location),
            blurb=blurb,
            colour=ui.colour_info,
            dismiss_on_select=False)

class pricecheck_stockitem(pricecheck_keypress, ui.listpopup):
    """A particular stock item on a line."""
    def __init__(self, stockitem):
        td.s.add(stockitem)
        super().__init__(
            stock.stockinfo_linelist(stockitem.id),
            title="Stock item {}".format(stockitem.id),
            dismiss=keyboard.K_CASH,
            show_cursor=False,
            colour=ui.colour_info)

class pricecheck_plu(pricecheck_keypress, ui.listpopup):
    """A price lookup."""
    def __init__(self, plu):
        l = ["",
             " Description: {} ".format(plu.description),
             "        Note: {} ".format(plu.note or ""),
             "       Price: {} ".format(tillconfig.fc(plu.price)),
             "",
             " Alternative price 1: {} ".format(tillconfig.fc(plu.altprice1)),
             " Alternative price 2: {} ".format(tillconfig.fc(plu.altprice2)),
             " Alternative price 3: {} ".format(tillconfig.fc(plu.altprice3)),
             ""]
        super().__init__(
            l, title="Price Lookup",
            dismiss=keyboard.K_CASH, show_cursor=False,
            colour=ui.colour_info)

class pricecheck_modifier(pricecheck_keypress, ui.infopopup):
    """A modifier key."""
    def __init__(self, modifier):
        if modifier not in modifiers.all:
            l = ["This modifier does not exist."]
        else:
            mod = modifiers.all[modifier]
            l = mod.description.split('\n\n')
        super().__init__(
            l, title=modifier,
            dismiss=keyboard.K_CASH,
            colour=ui.colour_info)

def pricecheck_window(kb):
    """Display a popup for information about a keyboard binding.

    Given a keyboard binding, display a suitable popup window for
    information about it.  We're choosing between classes
    defined in this file:

    modifier -> description of the modifier
    price lookup -> info about the PLU
    stockline with no stock -> popup prompt
    stockline with capacity -> list of items on sale
    stockline without capacity -> stock info
    """
    td.s.add(kb)
    if kb.stockline:
        if kb.stockline.linetype == "regular":
            sos = kb.stockline.stockonsale
            if len(sos) == 0:
                popup("There is no stock on sale on '{}'.  Press another "
                      "line key.".format(kb.stockline.name))
            else:
                pricecheck_stockitem(sos[0])
        elif kb.stockline.linetype == "display":
            pricecheck_display_stockline(kb.stockline)
        elif kb.stockline.linetype == "continuous":
            pricecheck_continuous_stockline(kb.stockline)
    elif kb.plu:
        pricecheck_plu(kb.plu)
    else:
        pricecheck_modifier(kb.modifier)
