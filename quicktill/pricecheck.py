"""Price lookup window."""

from . import td
from . import ui
from . import keyboard
from . import stock
from . import linekeys
from . import user
from . import modifiers
from . import tillconfig
from .models import StockItem
from sqlalchemy.orm import undefer


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
                popup(prompt=f"There are no options on key \"{k.keycap}\".  "
                      "Press another line key or scan a barcode.")
        elif hasattr(k, "code"):  # barcode.barcode object
            self.dismiss()
            if k.binding:
                pricecheck_window(k.binding)
            else:
                popup(prompt=f"Barcode '{k.code}' is not recognised.  Scan "
                      "another barcode.")
        else:
            super().keypress(k)


class popup(user.permission_checked, pricecheck_keypress, ui.infopopup):
    permission_required = ("price-check",
                           "Check prices without selling anything")

    def __init__(self, prompt="Press a line key or scan a barcode."):
        super().__init__([prompt], title="Price Check",
                         dismiss=keyboard.K_CLEAR, colour=ui.colour_info)


class pricecheck_display_stockline(pricecheck_keypress, ui.menu):
    """Display stockline -> display menu of items on sale on that line."""
    def __init__(self, stockline):
        st = stockline.stocktype
        sos = stockline.stockonsale
        f = ui.tableformatter(' r r+l ')
        sl = [(f(x.id, x.ondisplay, x.instock),
               pricecheck_stockitem, (x.id,)) for x in sos]
        blurb = [
            f"This line sells {st} at {tillconfig.currency}{st.pricestr}.",
            "",
            f"There are {stockline.ondisplay} {st.unit.name}s on display "
            f"and {stockline.instock} in stock.",
            "", "Choose a stock item for more information, "
            "press another line key, or scan a barcode.",
        ]
        super().__init__(
            sl, title=f"{stockline.name} ({stockline.location}) - "
            f"display capacity {stockline.capacity}",
            blurb=blurb,
            colour=ui.colour_info,
            dismiss_on_select=True)


class pricecheck_continuous_stockline(pricecheck_keypress, ui.menu):
    """Continuous stockline -> display menu of all items of appropriate type."""
    def __init__(self, stockline):
        st = stockline.stocktype
        sos = td.s.query(StockItem)\
                  .filter(StockItem.checked == True)\
                  .filter(StockItem.stocktype == st)\
                  .filter(StockItem.finished == None)\
                  .options(undefer('remaining'))\
                  .order_by(StockItem.id)\
                  .all()
        f = ui.tableformatter(' r r ')
        sl = [(f(x.id, x.remaining), pricecheck_stockitem, (x.id,))
              for x in sos if not x.stockline]
        # We don't use stockline.remaining because that also includes
        # stock of this type that is attached to other stock lines.
        remaining = sum(x.remaining for x in sos if not x.stockline)
        other_remaining = sum(x.remaining for x in sos if x.stockline)
        blurb = []
        if st.saleprice:
            blurb += [
                f"This line sells {st} at {tillconfig.currency}{st.pricestr}.",
            ]
        else:
            blurb += [
                f"{st} does not have a price set."
            ]
        blurb += [
            "",
            f"There are {st.unit.format_qty(remaining)} remaining in stock.",
        ]
        if other_remaining:
            blurb += [
                "",
                "Some stock items are not shown here because they are "
                "on sale on other stock lines.  There are "
                f"{st.unit.format_qty(other_remaining)} on sale on those "
                "stock lines.",
            ]
        blurb += [
            "", "Choose a stock item for more information, "
            "press another line key, or scan a barcode.",
        ]
        super().__init__(
            sl, title=f"{stockline.name} ({stockline.location})",
            blurb=blurb,
            colour=ui.colour_info,
            dismiss_on_select=True)


class pricecheck_stocktype(pricecheck_keypress, ui.menu):
    """Stock type -> display menu of all items of this type."""
    def __init__(self, stocktype):
        st = stocktype
        sos = td.s.query(StockItem)\
                  .filter(StockItem.checked == True)\
                  .filter(StockItem.stocktype == st)\
                  .filter(StockItem.finished == None)\
                  .options(undefer('remaining'))\
                  .order_by(StockItem.id)\
                  .all()
        f = ui.tableformatter(' r r ')
        sl = [(f(x.id, x.remaining), pricecheck_stockitem, (x.id,))
              for x in sos if not x.stockline]
        # We don't use stockline.remaining because that also includes
        # stock of this type that is attached to other stock lines.
        remaining = sum(x.remaining for x in sos if not x.stockline)
        other_remaining = sum(x.remaining for x in sos if x.stockline)
        blurb = []
        if st.saleprice:
            blurb += [
                f"{st} is on sale at {tillconfig.currency}{st.pricestr}.",
            ]
        else:
            blurb += [
                f"{st} does not have a price set."
            ]
        blurb += [
            "",
            f"There are {st.unit.format_qty(remaining)} remaining in stock.",
        ]
        if other_remaining:
            blurb += [
                "",
                "Some stock items are not shown here because they are "
                "on sale on stock lines.  There are "
                f"{st.unit.format_qty(other_remaining)} on sale on those "
                "stock lines.",
            ]
        blurb += [
            "", "Choose a stock item for more information, "
            "press another line key, or scan a barcode.",
        ]
        super().__init__(
            sl, title=f"{st}", blurb=blurb,
            colour=ui.colour_info, dismiss_on_select=True)


class pricecheck_stockitem(pricecheck_keypress, ui.listpopup):
    """A particular stock item on a line."""
    def __init__(self, stockitem_id):
        stockitem = td.s.query(StockItem).get(stockitem_id)
        super().__init__(
            stock.stockinfo_linelist(stockitem.id),
            title=f"Stock item {stockitem.id}",
            dismiss=keyboard.K_CLEAR,
            show_cursor=False,
            colour=ui.colour_info)


class pricecheck_plu(pricecheck_keypress, ui.listpopup):
    """A price lookup."""
    def __init__(self, plu):
        l = ["",
             f" Description: {plu.description} ",
             f"        Note: {plu.note or ''} ",
             f"       Price: {tillconfig.fc(plu.price)} ",
             "",
             f" Alternative price 1: {tillconfig.fc(plu.altprice1)} ",
             f" Alternative price 2: {tillconfig.fc(plu.altprice2)} ",
             f" Alternative price 3: {tillconfig.fc(plu.altprice3)} ",
             ""]
        super().__init__(
            l, title="Price Lookup",
            dismiss=keyboard.K_CLEAR, show_cursor=False,
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
            dismiss=keyboard.K_CLEAR,
            colour=ui.colour_info)


def pricecheck_window(kb):
    """Display a popup for information about a keyboard binding or barcode.

    Given a keyboard binding or barcode, display a suitable popup
    window for information about it.  We're choosing between classes
    defined in this file:

    modifier -> description of the modifier
    price lookup -> info about the PLU
    stockline with no stock -> popup prompt
    display stockline -> list of items on sale
    continuous stockline -> list of items on sale, not on other stocklines
    stock type -> list of items on sale, not on other stocklines
    """
    td.s.add(kb)
    if kb.stockline:
        if kb.stockline.linetype == "regular":
            sos = kb.stockline.stockonsale
            if len(sos) == 0:
                popup(f"There is no stock on sale on '{kb.stockline.name}'.  "
                      "Press another line key.")
            else:
                pricecheck_stockitem(sos[0].id)
        elif kb.stockline.linetype == "display":
            pricecheck_display_stockline(kb.stockline)
        elif kb.stockline.linetype == "continuous":
            pricecheck_continuous_stockline(kb.stockline)
    elif kb.plu:
        pricecheck_plu(kb.plu)
    elif hasattr(kb, "stocktype") and kb.stocktype:
        pricecheck_stocktype(kb.stocktype)
    else:
        pricecheck_modifier(kb.modifier)
