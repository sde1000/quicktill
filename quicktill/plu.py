"""Price lookup window.

"""

from . import td,ui,keyboard,stock,stocklines,tillconfig

def plu_keypress(key):
    bindings=stocklines.linemenu(key,plu_window)
    if bindings==0:
        # The previous window will automatically have been dismissed
        # by the time we get here.  If there are no bindings for the
        # key that has just been pressed, return to the "press a key"
        # popup here rather than just returning to the register.
        popup(prompt="There are no stocklines on key \"%s\".  Press another "
              "line key."%keyboard.kcnames[key])

plu_keymap={}
for i in keyboard.lines:
    plu_keymap[i]=(plu_keypress,(i,),True)

def popup(prompt=None):
    if prompt is None: prompt="Press a line key."
    ui.infopopup([prompt],title="Price Check",
                 dismiss=keyboard.K_CASH,
                 colour=ui.colour_info,keymap=plu_keymap)

def plu_window(kb):
    td.s.add(kb)
    sos=kb.stockline.stockonsale
    if len(sos)==1:
        stock.stockinfo_popup(sos[0].stockitem.id,plu_keymap)
    elif len(sos)>1:
        lines=ui.table([("%d"%x.stockitem.id,
                         x.stockitem.stocktype.format().ljust(40),
                         "%d"%max(x.displayqty_or_zero-x.stockitem.used,0),
                         "%d"%(x.stockitem.stockunit.size-max(x.displayqty_or_zero,x.stockitem.used)))
                        for x in sos]).format(' r l r+l ')
        sl=[(x,stock.stockinfo_popup,(y.stockitem.id,plu_keymap))
            for x,y in zip(lines,sos)]
        ui.menu(sl,title="%s (%s) - display capacity %d"%
                (kb.stockline.name,kb.stockline.location,kb.stockline.capacity),
                blurb=("Choose a stock item for more information, or "
                       "press another line key."),
                keymap=plu_keymap, colour=ui.colour_info)
    else:
        ui.infopopup(["There is no stock on '%s'.  "
                      "Press another line key."%kb.stockline.name],
                     title="Price Check",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info,keymap=plu_keymap)
