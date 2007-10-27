"""Price lookup window.

"""

import td,ui,keyboard,stock,stocklines,tillconfig

def plu_keypress(key):
    stocklines.linemenu(key,plu_window)
    
plu_keymap={}
for i in keyboard.lines:
    plu_keymap[i]=(plu_keypress,(i,),True)

def popup():
    ui.infopopup(["Press a line key."],title="Price Check",
                 dismiss=keyboard.K_CASH,
                 colour=ui.colour_info,keymap=plu_keymap)

def plu_window(line):
    name,qty,dept,pullthru,menukey,stocklineid,loc,cap=line
    sn=td.stock_onsale(stocklineid)
    if len(sn)==1:
        stock.stockinfo_popup(sn[0][0],plu_keymap)
    elif len(sn)>1:
        sinfo=td.stock_info([x[0] for x in sn])
        for a,b in zip(sn,sinfo):
            if a[1] is None: b['displayqty']=0.0
            else: b['displayqty']=a[1]
        lines=ui.table([("%d"%x['stockid'],
                         stock.format_stock(x).ljust(40),
                         "%d"%max(x['displayqty']-x['used'],0),
                         "%d"%(x['size']-max(x['displayqty'],x['used'])))
                        for x in sinfo]).format(' r l r+l ')
        sl=[(x,stock.stockinfo_popup,(y['stockid'],plu_keymap))
            for x,y in zip(lines,sinfo)]
        ui.menu(sl,title="%s (%s) - display capacity %d"%
                (name,loc,cap),
                blurb=("Choose a stock item for more information, or "
                       "press another line key."),
                keymap=plu_keymap, colour=ui.colour_info)
    else:
        ui.infopopup(["There is no stock on '%s'.  "
                      "Press another line key."%name],
                     title="Price Check",dismiss=keyboard.K_CASH,
                     colour=ui.colour_info,keymap=plu_keymap)
