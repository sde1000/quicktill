"""Price lookup window.

"""

from __future__ import unicode_literals
from . import td,ui,keyboard,stock,linekeys,user,modifiers,tillconfig

class pricecheck_keypress(object):
    """
    This class is a mixin for the various classes used by the price
    lookup user interface; it provides preprocessing of keypresses to
    spot line key presses.

    """
    def keypress(self,k):
        if hasattr(k,"line"):
            self.dismiss()
            bindings=linekeys.linemenu(k,pricecheck_window,
                                       allow_stocklines=True,allow_plus=True,
                                       allow_mods=True)
            if bindings==0:
                popup(prompt="There are no options on key \"{}\".  Press "
                      "another line key.".format(k.keycap))
        else:
            super(pricecheck_keypress,self).keypress(k)

class popup(user.permission_checked,pricecheck_keypress,ui.infopopup):
    permission_required=("price-check","Check prices without selling anything")
    def __init__(self,prompt="Press a line key."):
        ui.infopopup.__init__(
            self,[prompt],title="Price Check",
            dismiss=keyboard.K_CASH,colour=ui.colour_info)

class pricecheck_line_with_capacity(pricecheck_keypress,ui.menu):
    """
    Stockline with capacity -> display menu of items on sale on that line.

    """
    def __init__(self,stockline):
        sos=stockline.stockonsale
        f=ui.tableformatter(' r l r+l ')
        sl=[(f(x.id,x.stocktype.format(),x.ondisplay,x.instock),
             pricecheck_stockitem,(x,)) for x in sos]
        ui.menu.__init__(self,sl,title="%s (%s) - display capacity %d"%
                         (stockline.name,stockline.location,stockline.capacity),
                         blurb=("Choose a stock item for more information, or "
                                "press another line key."),
                         colour=ui.colour_info)

class pricecheck_stockitem(pricecheck_keypress,ui.listpopup):
    """
    A particular stock item on a line.

    """
    def __init__(self,stockitem):
        td.s.add(stockitem)
        ui.listpopup.__init__(self,
                              stock.stockinfo_linelist(stockitem.id),
                              title="Stock item %d"%stockitem.id,
                              dismiss=keyboard.K_CASH,
                              show_cursor=False,
                              colour=ui.colour_info)

class pricecheck_plu(pricecheck_keypress,ui.listpopup):
    """A price lookup.

    """
    def __init__(self,plu):
        l=["",
           " Description: {}".format(plu.description),
           "        Note: {}".format(plu.note or ""),
           "       Price: {}".format(tillconfig.fc(plu.price)),
           "",
           " Alternative price 1: {}".format(tillconfig.fc(plu.altprice1)),
           " Alternative price 2: {}".format(tillconfig.fc(plu.altprice1)),
           " Alternative price 3: {}".format(tillconfig.fc(plu.altprice1)),
           ""]
        ui.listpopup.__init__(self,l,title="Price Lookup",
                              dismiss=keyboard.K_CASH,show_cursor=False,
                              colour=ui.colour_info)

class pricecheck_modifier(pricecheck_keypress,ui.infopopup):
    """A modifier key.

    """
    def __init__(self,modifier):
        if modifier not in modifiers.all:
            l=["This modifier does not exist."]
        else:
            mod=modifiers.all[modifier]
            l=mod.description.split('\n\n')
        ui.infopopup.__init__(self,l,title=modifier,
                              dismiss=keyboard.K_CASH,
                              colour=ui.colour_info)

def pricecheck_window(kb):
    """Given a keyboard binding, display a suitable popup window for
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
        sos=kb.stockline.stockonsale
        if len(sos)==0:
            popup("There is no stock on sale on '{}'.  Press another "
                  "line key.".format(kb.stockline.name))
        elif kb.stockline.capacity:
            pricecheck_line_with_capacity(kb.stockline)
        else:
            pricecheck_stockitem(sos[0])
    elif kb.plu:
        pricecheck_plu(kb.plu)
    else:
        pricecheck_modifier(kb.modifier)
