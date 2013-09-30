# -*- coding: utf-8 -*-

import quicktill.keyboard as keyboard
import quicktill.extras as extras
import quicktill.foodcheck as foodcheck
from quicktill.keyboard import *
from quicktill.pdrivers import nullprinter,Epson_TM_U220,Epson_TM_T20,pdf,pdflabel,A4
from quicktill import register,ui,kbdrivers,stockterminal
from quicktill.managetill import popup as managetill
from quicktill.managestock import popup as managestock
from quicktill.plu import popup as plu
from quicktill.usestock import popup as usestock
from quicktill.recordwaste import popup as recordwaste
from quicktill.lockscreen import popup as lockscreen
from quicktill.stock import annotate
from quicktill import timesheets,btcmerch
from decimal import Decimal
import math
import os
import socket,struct

vatrate=0.2

def haymakers_deptkeycheck(dept,price):
    """Check that the price entered when a department key is pressed is
    appropriate for that department.  Returns either None (no problem
    found), a string or a list of strings to display to the user.

    """
    if dept==7: # Soft drinks
        if price not in [0.50,1.00,2.00]:
            return (u"Soft drinks are 50p for a mixer, £1.00 for a half, "
                    u"and £2.00 for a pint.  If you're selling a bottle, "
                    u"you must press the appropriate button for that bottle.")
    if dept==9: # Wine
        if price not in [2.50,3.70,4.80,14.00]:
            return ([u"£2.50 for a small glass, "
                     u"£3.70 for a medium glass, "
                     u"£4.80 for a large glass, and £14.00 for a bottle."])
    if dept==8: # Misc
        return u"We do not use the Misc button."

# Price policy function
def haymakers_pricepolicy(item,qty):
    # Start with the standard price
    price=item.saleprice*qty
    if item.stocktype.dept_id==4 and qty==2.0: price=price-0.50
    if item.stocktype.dept_id==1 and qty==4.0: price=price-1.00
    return price

# Price guess algorithm goes here
def haymakers_priceguess(dept,cost,abv):
    if dept==1:
        return guessbeer(cost,abv)
    if dept==2:
        return guesskeg(cost,abv)
    if dept==3:
        return guesscider(cost,abv)
    if dept==4:
        return guessspirit(cost,abv)
    if dept==5:
        return guesssnack(cost)
    if dept==6:
        return guessbottle(cost)
    if dept==9:
        return guesswine(cost)
    return None

# Unit is a pint
def guessbeer(cost,abv):
    if abv is None: return None
    if abv<3.1: r=2.50
    elif abv<3.3: r=2.60
    elif abv<3.8: r=2.70
    elif abv<4.2: r=2.80
    elif abv<4.7: r=2.90
    elif abv<5.2: r=3.00
    elif abv<5.7: r=3.10
    elif abv<6.2: r=3.20
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+18.0)/72.0
    if cost>idealcost:
        r=r+((cost-idealcost)*(vatrate+1.0))
        r=math.ceil(r*10.0)/10.0
    return r

def guesskeg(cost,abv):
    if abv==4.4: return 3.10 # Moravka
    return None

def guesssnack(cost):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessbottle(cost):
    return math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0

def guesswine(cost):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessspirit(cost,abv):
    return max(2.50,math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0)

def guesscider(cost,abv):
    return math.ceil(cost*2.6*(vatrate+1.0)*10.0)/10.0

tapi=extras.twitter_api(
    token='not-a-valid-token',
    token_secret='not-a-valid-token-secret',
    consumer_key='not-a-valid-key',
    consumer_secret='not-a-valid-secret')

def usestock_hook(item,line):
    t=None
    if item.stocktype.dept_id==3:
        # It's a cider. Tweet it.
        t="Next cider: %s"%item.stocktype.format()
    elif item.stocktype.dept_id==1:
        # Real ale.  Tweet if not from Milton, or if particularly strong
        if item.stocktype.manufacturer!="Milton":
            t="Next guest beer: %s"%item.stocktype.format()
        if item.stocktype.abv is not None and item.stocktype.abv>Decimal("6.4"):
            t="Next strong beer: %s"%item.stocktype.format()
    if t: extras.twitter_post(tapi,default_text=t,fail_silently=True)

tsapi=timesheets.Api("haymakers","not-a-valid-password",
                     "http://www.individualpubs.co.uk",
                     "/schedule/haymakers/api/users/")

def dalicmd(address,value):
    """
    Very hackily send a message to the lighting system.  Does not
    check for errors.

    """
    message=struct.pack("BB",address,value)
    try:
        s=socket.create_connection(
            ("not-valid-address.individualpubs.co.uk",55825))
        s.send(message)
        result=s.recv(2)
        s.close()
    except:
        pass

def setscene(scene):
    return dalicmd(0xff,0x10+scene)

def groupon(group):
    return dalicmd(0x81+(group<<1),0x05) # "Recall max level"

def groupoff(group):
    return dalicmd(0x81+(group<<1),0x00) # "Off"

def lightsmenu():
    menu=[
        (keyboard.K_ONE,"Start of day cleaning / home time",
         setscene,(0,)),
        (keyboard.K_TWO,"Open for business",setscene,(1,)),
        (keyboard.K_THREE,"Evening - outside lights on",setscene,(2,)),
        (keyboard.K_FOUR,"End of night counting up",setscene,(4,)),
        (keyboard.K_FIVE,"Outside back lights off",groupoff,(7,)),
        (keyboard.K_SIX,"Outside back lights on",groupon,(7,)),
        (keyboard.K_SEVEN,"Outside front lights off",groupoff,(8,)),
        (keyboard.K_EIGHT,"Outside front lights on",groupon,(8,)),
        (keyboard.K_ZERO,"Everything off",setscene,(3,))]
    ui.keymenu(menu,"Lighting")

def appsmenu():
    menu=[
        (keyboard.K_ONE,"Twitter",extras.twitter_client,(tapi,)),
        ]
    if configname=='mainbar':
        menu.append(
            (keyboard.K_TWO,"Timesheets",timesheets.popup,(tsapi,)))
    menu.append(
        (keyboard.K_THREE,"Lights",lightsmenu,()))
    ui.keymenu(menu,"Apps")

def panickey():
    ui.infopopup(["Don't panic, Captain Mainwaring!"],
                 title="Jones",colour=ui.colour_confirm,
                 dismiss=K_CASH)

register_hotkeys={
    K_PRICECHECK: plu,
    K_MANAGETILL: managetill,
    K_MANAGESTOCK: managestock,
    K_USESTOCK: usestock,
    K_WASTE: recordwaste,
    K_APPS: appsmenu,
    K_PANIC: panickey,
    ord('s'): managestock,
    ord('S'): managestock,
    ord('a'): annotate,
    ord('A'): annotate,
    ord('r'): recordwaste,
    ord('R'): recordwaste,
    ord('t'): appsmenu,
    ord('T'): appsmenu,
    ord('m'): managetill,
    ord('M'): managetill,
    }

modkeyinfo={
    'Half': (0.5, [1,2,3]), # Half pint must be ale, keg or cider
    'Double': (2.0, [4]), # Double must be spirits
    '4pt Jug': (4.0, [1,2,3]), # 4pt Jug must be ale, keg or cider
}

std={
    'pubname':"The Haymakers",
    'pubnumber':"01223 311077",
    'pubaddr':("54 High Street, Chesterton","Cambridge CB4 1NG"),
    'currency':u"£",
    'cashback_limit':50.0,
    'cashback_first':True,
    'pricepolicy':haymakers_pricepolicy,
    'priceguess':haymakers_priceguess,
    'deptkeycheck':haymakers_deptkeycheck,
    'modkeyinfo':modkeyinfo,
    'database':'dbname=haymakers',
    'allow_tabs':True,
    'nosale':True,
    'checkdigit_print':True,
    'checkdigit_on_usestock':False,
    'usestock_hook':usestock_hook,
    'btcmerch':btcmerch.Api(
        "haymakers","not-a-password","haymakers",
        "http://www.individualpubs.co.uk/merchantservice/"), # Not valid address
}

kitchen={
#    'kitchenprinter':Epson_TM_U220(
#    ('kitchenprinter.haymakers.i.individualpubs.co.uk',9100),57,
#    has_cutter=True),
    'kitchenprinter': nullprinter(), # XXX testing
    'menuurl':'http://till.haymakers.i.individualpubs.co.uk:8080/foodmenu.py',
    }

noprinter={
    'printer': (nullprinter,()),
    }
localprinter={
    'printer': (Epson_TM_T20,("/dev/usb/lp0",80)),
    }
pdfprinter={
    'printer': (pdf,("lpr %s",)),
    }
xpdfprinter={
    'printer': (pdf,("evince %s",)),
    }
# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4=[2,4,"99.1mm","67.7mm","3mm","0mm",A4]
staples_3by6=[3,6,"63.5mm","46.6mm","2.8mm","0mm",A4]
labelprinter={
    'labelprinter': (pdflabel,["lpr -o MediaType=Labels %s"]+staples_3by6),
    }

kb1={
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard([
    # control keys
    ("H01","Alice",K_ALICE),
    ("G01","Bob",K_BOB),
    ("F01","Charlie",K_CHARLIE),
    ("E01","Doris",K_DORIS),
    ("H02","Manage Till",K_MANAGETILL),
    ("G02","Manage Stock",K_MANAGESTOCK),
    ("F02","Use Stock",K_USESTOCK),
    ("E02","Record Waste",K_WASTE),
    ("D01","Recall Trans",K_RECALLTRANS),
    ("D02","Manage Trans",K_MANAGETRANS),
    ("C01","Price Check",K_PRICECHECK),
    ("C02","Print",K_PRINT),
    ("B01","Cancel",K_CANCEL),
    ("B02","Apps",K_APPS),
    ("A01","Clear",K_CLEAR),
    ("D13","Order Food",K_FOODORDER),
    ("D14","Cancel Food",K_CANCELFOOD),
    # Cursor keys, numeric keypad, cash/card keys, Quantity keys
    ("C11","Left",K_LEFT),
    ("D12","Up",K_UP),
    ("C12","Down",K_DOWN),
    ("C13","Right",K_RIGHT),
    ("E14",".",K_POINT),
    ("E15","0",K_ZERO),
    ("E16","00",K_ZEROZERO),
    ("F14","1",K_ONE),
    ("F15","2",K_TWO),
    ("F16","3",K_THREE),
    ("G14","4",K_FOUR),
    ("G15","5",K_FIVE),
    ("G16","6",K_SIX),
    ("H14","7",K_SEVEN),
    ("H15","8",K_EIGHT),
    ("H16","9",K_NINE),
    ("B15","Cash/Enter",K_CASH),
    ("C15","Card",K_CARD),
    ("D15","Lock",K_LOCK),
    ("C14","20",K_TWENTY),
    ("B14","10",K_TENNER),
    ("A14","5",K_FIVER),
    ("E13","Quantity",K_QUANTITY),
    ("E12","Double",K_DOUBLE),
    ("A02","4pt Jug",K_4JUG),
    # Magnetic stripe reader
    ("M1H","Magstripe 1 Header",K_M1H),
    ("M1T","Magstripe 1 Trailer",K_M1T),
    ("M2H","Magstripe 2 Header",K_M2H),
    ("M2T","Magstripe 2 Trailer",K_M2T),
    ("M3H","Magstripe 3 Header",K_M3H),
    ("M3T","Magstripe 3 Trailer",K_M3T),
    # Eventually all these keys will be managed by entries in the database
    # For now they are hard-coded here
    # Departments
    ("H12","Misc",K_DEPT8),
    ("H13","Hot Drinks",K_DEPT11),
    ("G12","Drink 'In'",K_DRINKIN),
    ("G13","Wine",K_DEPT9),
    ("F12","Soft",K_DEPT7),
    ("F13","Food",K_DEPT10),
    # All line keys
    ("H03","Line 01",K_LINE1),
    ("H04","Line 02",K_LINE2),
    ("H05","Line 03",K_LINE3),
    ("H06","Line 04",K_LINE4),
    ("H07","Line 05",K_LINE5),
    ("H08","Line 06",K_LINE6),
    ("H09","Line 07",K_LINE7),
    ("H10","Line 08",K_LINE8),
    ("H11","Line 09",K_LINE9),
    ("G03","Line 10",K_LINE10),
    ("G04","Line 11",K_LINE11),
    ("G05","Line 12",K_LINE12),
    ("G06","Line 13",K_LINE13),
    ("G07","Line 14",K_LINE14),
    ("G08","Line 15",K_LINE15),
    ("G09","Line 16",K_LINE16),
    ("G10","Line 17",K_LINE17),
    ("G11","Line 18",K_LINE18),
    ("F03","Line 19",K_LINE19),
    ("F04","Line 20",K_LINE20),
    ("F05","Line 21",K_LINE21),
    ("F06","Line 22",K_LINE22),
    ("F07","Line 23",K_LINE23),
    ("F08","Line 24",K_LINE24),
    ("F09","Line 25",K_LINE25),
    ("F10","Line 26",K_LINE26),
    ("F11","Line 27",K_LINE27),
    ("E03","Line 28",K_LINE28),
    ("E04","Line 29",K_LINE29),
    ("E05","Line 30",K_LINE30),
    ("E06","Line 31",K_LINE31),
    ("E07","Line 32",K_LINE32),
    ("E08","Line 33",K_LINE33),
    ("E09","Line 34",K_LINE34),
    ("E10","Line 35",K_LINE35),
    ("E11","Line 36",K_LINE36),
    ("D03","Line 37",K_LINE37),
    ("D04","Line 38",K_LINE38),
    ("D05","Line 39",K_LINE39),
    ("D06","Line 40",K_LINE40),
    ("D07","Line 41",K_LINE41),
    ("D08","Line 42",K_LINE42),
    ("D09","Line 43",K_LINE43),
    ("D10","Line 44",K_LINE44),
    ("D11","Line 45",K_LINE45),
    ("C03","Line 46",K_LINE46),
    ("C04","Line 47",K_LINE47),
    ("C05","Line 48",K_LINE48),
    ("C06","Line 49",K_LINE49),
    ("C07","Line 50",K_LINE50),
    ("C08","Line 51",K_LINE51),
    ("C09","Line 52",K_LINE52),
    ("C10","Line 53",K_LINE53),
    ("B03","Line 55",K_LINE55),
    ("B04","Line 56",K_LINE56),
    ("B05","Line 57",K_LINE57),
    ("B06","Line 58",K_LINE58),
    ("B07","Line 59",K_LINE59),
    ("B08","Line 60",K_LINE60),
    ("B09","Line 61",K_LINE61),
    ("B10","Line 62",K_LINE62),
    ("B11","Line 63",K_LINE63),
    ("B12","Line 64",K_LINE64),
    ("B13","Line 65",K_LINE65),
    ("A03","Line 67",K_LINE67),
    ("A04","Line 68",K_LINE68),
    ("A05","Line 69",K_LINE69),
    ("A06","Line 70",K_LINE70),
    ("A07","Line 71",K_LINE71),
    ("A08","Line 72",K_LINE72),
    ("A09","Line 73",K_LINE73),
    ("A10","Line 74",K_LINE74),
    ("A11","Line 75",K_LINE75),
    ("A12","Line 76",K_LINE76),
    ("A13","Line 77",K_LINE77),
    ]),
    'kbtype':1,
    'firstpage': lambda: register.select_page("Alice", register_hotkeys).\
        list_open_transactions(),
    }

stock_hotkeys={
    ord('s'): managestock,
    ord('S'): managestock,
    ord('a'): annotate,
    ord('A'): annotate,
    ord('r'): recordwaste,
    ord('R'): recordwaste,
    ord('t'): appsmenu,
    ord('T'): appsmenu,
    ord('m'): managetill,
    ord('M'): managetill,
    }

global_hotkeys={
    K_ALICE: lambda: register.select_page("Alice", register_hotkeys),
    K_BOB: lambda: register.select_page("Bob", register_hotkeys),
    K_CHARLIE: lambda: register.select_page("Charlie", register_hotkeys),
    K_DORIS: lambda: stockterminal.page(register_hotkeys,["Bar"]),
    K_LOCK: lockscreen,
}

stockcontrol={
    'kbdriver':kbdrivers.curseskeyboard(),
    'kbtype':0,
    'firstpage': lambda: stockterminal.page(stock_hotkeys,["Bar"]),
}    

# Config0 is a QWERTY-keyboard stock-control terminal
config0={'description':"Stock-control terminal"}
config0.update(std)
config0.update(stockcontrol)
config0.update(xpdfprinter)
config0.update(labelprinter)

# Config1 is the main bar terminal
config1={'description':"Haymakers main bar"}
config1.update(std)
config1.update(kb1)
config1.update(xpdfprinter) # XXX for testing
config1.update(labelprinter)
config1.update(kitchen)
config1['hotkeys']=global_hotkeys

# Config2 is the festival terminal
#config2={'description':"Haymakers festival bar"}
#config2.update(std)
#config2.update(kb2)
#config2.update(localprinter)
#config2.update(labelprinter)
#config2.update(kitchen)

config3={'description':"Test menu file 'testmenu.py' in current directory",
         'kbdriver':kbdrivers.curseskeyboard(),
         'kbtype':0,
#         'menuurl':'http://localhost:8080/foodmenu.py',
         'menuurl':"file:testmenu.py",
         'kitchenprinter':nullprinter(),
         'pages':[(foodcheck.page,keyboard.K_ALICE,([],))],
         }
config3.update(std)
config3.update(xpdfprinter)

# Things to define:
#  description - summary of the configuration
#  kbdriver - keyboard driver
#  kbtype - keyboard type
#  printer - (driver,args)
#  labelprinter - (driver,args)
#  pages - available pages
#  pubname
#  pubnumber
#  pubaddr
#  vatrate  (to be removed)
#  vatno  (to be removed)
#  companyaddr
#  currency
#  cashback_limit
#  pricepolicy  (optional)
#  priceguess  (optional)
#  database  (only if database will be used in this configuration)
#  pdriver
#  kitchenprinter (only if food ordering configured)
#  menuurl (only if food ordering configured)


configurations={
    'default': config0,
    'mainbar': config1,
#    'festivalbar': config2,
    'testmenu': config3,
    }
