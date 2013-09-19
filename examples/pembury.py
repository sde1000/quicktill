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
from quicktill.stock import annotate
from quicktill.lockscreen import popup as lockscreen
from quicktill import timesheets,btcmerch
import math
import os
from decimal import Decimal

# VAT rate changed 4/1/2011
vatrate=0.2

def pembury_deptkeycheck(dept,price):
    """Check that the price entered when a department key is pressed is
    appropriate for that department.  Returns either None (no problem
    found), a string or a list of strings to display to the user.

    """
    if dept==7: # Soft drinks
        if price not in [0.50,0.90,1.80]:
            return (u"Soft drinks are 50p for a mixer, 90p for a half, "
                    u"and £1.80 for a pint.  If you're selling a bottle, "
                    u"you must press the appropriate button for that bottle.")
    if dept==9: # Wine
        if price not in [2.70,4.10,5.40,16.00, # New wines low rate
                         3.30,5.00,6.60,19.80]: # New wines high rate
            return ([u"Prices for wines (except Ana Sauv Blanc) are:",
                     u"£2.70 for a 125ml glass,",
                     u"£4.10 for a 175ml glass,",
                     u"£5.40 for a 250ml glass,",
                     u"£16.00 for a bottle.",
                     u"",
                     u"The Ana Sauv Blanc is £3.30/£5.00/£6.60/£19.80."])
    if dept==11: # Hot drinks
        if price not in [1.00,2.00]:
            return (u"Tea is £1.00, coffee is £2.00.")

# Price policy function
def pembury_pricepolicy(item,qty):
    # Start with the standard price
    price=item.saleprice*qty
    if item.stocktype.dept_id==4 and qty==2.0: price=price-0.50
    if item.stocktype.dept_id==1 and qty==4.0: price=price-1.00
    return price

# Price guess algorithm goes here
def pembury_priceguess(dept,cost,abv,vatrate=vatrate):
    if dept==1:
        return guessbeer(cost,abv,vatrate)
    if dept==2:
        return guesskeg(cost,abv,vatrate)
    if dept==3:
        return guesscider(cost,abv,vatrate)
    if dept==4:
        return guessspirit(cost,abv,vatrate)
    if dept==5:
        return guesssnack(cost,vatrate)
    if dept==6:
        return guessbottle(cost,vatrate)
    if dept==9:
        return guesswine(cost,vatrate)
    return None

# Unit is a pint
def guessbeer(cost,abv,vatrate):
    if abv is None: return None
    if abv<3.1: r=2.40
    elif abv<3.3: r=2.80
    elif abv<3.8: r=2.90
    elif abv<4.2: r=3.00
    elif abv<4.7: r=3.10
    elif abv<5.2: r=3.20
    elif abv<5.7: r=3.30
    elif abv<6.2: r=3.40
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+18.0)/72.0
    if cost>idealcost:
        r=r+((cost-idealcost)*(vatrate+1.0))
        r=math.ceil(r*10.0)/10.0
    return r

def guesskeg(cost,abv,vatrate):
    if abv==4.4: return 3.40 # Moravka
    return None

def guesssnack(cost,vatrate):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessbottle(cost,vatrate):
    return math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0

def guesswine(cost,vatrate):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessspirit(cost,abv,vatrate):
    return max(3.00,math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0)

def guesscider(cost,abv,vatrate):
    if abv<5.2: r=3.00
    elif abv<5.7: r=3.10
    elif abv<6.2: r=3.20
    elif abv<6.5: r=3.30
    elif abv<6.7: r=3.40
    elif abv<6.9: r=3.50
    elif abv<7.2: r=3.60
    elif abv<7.5: r=3.70
    elif abv<7.8: r=3.80
    else: r=None
    return r

def departures():
    menu=[
        (keyboard.K_ONE,"Hackney Downs",extras.departurelist,
         ("Hackney Downs","HAC")),
        (keyboard.K_TWO,"Hackney Central",extras.departurelist,
         ("Hackney Central","HKC")),
        (keyboard.K_THREE,"London Liverpool Street",extras.departurelist,
         ("London Liverpool Street","LST")),
        ]
    ui.keymenu(menu,"Stations")

def wireless_command(cmd):
    try:
        os.system("ssh root@public.pembury.individualpubs.co.uk %s"%cmd)
    except:
        pass

# We really want to limit this to the mainbar configuration.  If we do
# not then there is a race between other instances of the software
# running on the main till (eg. the default configuration as a stock
# terminal) that means only one of them will be successful at deleting
# the alarm file; the others will catch an exception and exit.
if configname=='mainbar':
    coffeealarm=extras.coffeealarm("/home/till/coffeealarm")
    extras.reminderpopup((22,45),"Outside area reminder",[
            "Please check the triangular outdoor area and remind everyone "
            "out there that it will be cleared and locked up at 11pm."])
    extras.reminderpopup((23,0),"Outside area reminder",[
            "Please clear everyone out of the triangular outdoor area "
            "and lock the gate and the door."])
    extras.reminderpopup((23,10),"Outside area reminder",[
            "Please check that the triangular outdoor area is locked up "
            "and clear of seats and glasses - this should have been done "
            "at 11pm."])
    extras.reminderpopup((17,15),"Rubbish reminder",[
            "Please put the rubbish out - red sack for general waste, "
            "and strip of tape for cardboard.  The rubbish must be put "
            "out before 6:15pm.  DO NOT PUT GLASS BOTTLES OUT.  Bottle "
            "recycling must be put out at 10am on Thursdays, Saturdays "
            "and Sundays."])

# To generate a token and secret for your twitter account, do the
# following:
# $ python
# >>> import quicktill.extras
# >>> quicktill.extras.twitter_auth()
# Follow the prompts - you will generate a PIN using your web browser and
# then type it in to get the token and secret.
tapi=extras.twitter_api(
    token='not-a-valid-token',
    token_secret='not-a-valid-secret')

def usestock_hook(stock,line):
    t=None
    if stock.stocktype.dept_id==3:
        # It's a cider. Tweet it.
        t="Next cider: %s"%(stock.stocktype.format())
    elif stock.stocktype.dept_id==1:
        # Real ale.  Tweet if not from Milton, or if particularly strong
        if stock.stocktype.manufacturer!="Milton":
            t="Next guest beer: %s"%stock.stocktype.format()
        if (stock.stocktype.abv is not None
            and stock.stocktype.abv>Decimal('6.4')):
            t="Next strong beer: %s"%stock.stocktype.format()
    if t: extras.twitter_post(tapi,default_text=t,fail_silently=True)

tsapi=timesheets.Api("pembury","not-a-valid-password",
                     "https://admin.individualpubs.co.uk",
                     "/schedule/pembury/api/users/")

def extrasmenu():
    menu=[
        (keyboard.K_TWO,"Twitter",extras.twitter_client,(tapi,)),
        ]
    if configname=='mainbar':
        menu=[(keyboard.K_ONE,"Timesheets",timesheets.popup,(tsapi,))]+menu
        menu=menu+[
            (keyboard.K_THREE,"Reboot the wireless access point",
             wireless_command,("reboot",)),
            (keyboard.K_FOUR,"Turn the wireless off",
             wireless_command,("ifdown lan",)),
            (keyboard.K_FIVE,"Turn the wireless on",
             wireless_command,("ifup lan",)),
            (keyboard.K_SIX,"Coffee pot timer",extras.managecoffeealarm,
             (coffeealarm,))]
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
    K_EXTRAS: extrasmenu,
    K_APPS: extrasmenu,
    K_LOCK: lockscreen,
    K_PANIC: panickey,
    ord('s'): managestock,
    ord('S'): managestock,
    ord('a'): annotate,
    ord('A'): annotate,
    ord('r'): recordwaste,
    ord('R'): recordwaste,
    ord('t'): extrasmenu,
    ord('T'): extrasmenu,
    ord('m'): managetill,
    ord('M'): managetill,
    }

modkeyinfo={
    'Half': (0.5, [1,2,3]), # Half pint must be ale, keg or cider
    'Double': (2.0, [4]), # Double must be spirits
    '4pt Jug': (4.0, [1,2,3]), # 4pt Jug must be ale, keg or cider
}

std={
    'pubname':"The Pembury Tavern",
    'pubnumber':"020 8986 8597",
    'pubaddr':("90 Amhurst Road","London E8 1JH"),
    'currency':u"£",
    'cashback_limit':50.0,
    'pricepolicy':pembury_pricepolicy,
    'priceguess':pembury_priceguess,
    'deptkeycheck':pembury_deptkeycheck,
    'modkeyinfo':modkeyinfo,
    'database':'dbname=pembury', # XXX needs changing before deployment,
    # because this file may be used by remote terminals too
    'allow_tabs':False if configname in ["mainbar","secondtill"] else True,
    'nosale':False,
    'checkdigit_print':True,
    'checkdigit_on_usestock':True,
    'cashback_first':True,
    'transaction_notes':["","Kitchen tab","Party tab","Cash on counter"],
    'usestock_hook':usestock_hook,
    # The URL below is not the actual URL the service is deployed at!
    'btcmerch':btcmerch.Api(
        "pembury","not-a-valid-password","pembury",
        "http://www.individualpubs.co.uk/merchantservice/"),
}

kitchen={
    'kitchenprinter':nullprinter(),
    'menuurl':'http://till.pembury.i.individualpubs.co.uk:8080/foodmenu.py',
    }

noprinter={
    'printer': (nullprinter,()),
    }
localprinter={
    'printer': (Epson_TM_U220,("/dev/lp0",57)),
    }
thermalprinter={
    'printer': (Epson_TM_T20,("/dev/usb/lp0",80)),
    }
usbprintercutter={
    'printer': (Epson_TM_U220,("/dev/usb/lp0",57,'iso-8859-1',True)),
    }
pdfprinter={
    'printer': (pdf,("lpr %s",)),
    }
xpdfprinter={
    'printer': (pdf,("evince %s",300)),
    }
# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4=[2,4,"99.1mm","67.7mm","3mm","0mm",A4]
staples_3by6=[3,6,"63.5mm","46.6mm","2.8mm","0mm",A4]
# The Laserjet 1320 doesn't believe in 'Label' media anywhere other than
# tray one.  The labels are actually in tray three; I set the type to
# "Letterhead" to stop other print jobs using them.
labelprinter={
    'labelprinter': (pdflabel,["lpr -o MediaType=Letterhead %s"]+staples_3by6),
    }

kb2={ # Festival keyboard
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard([
    # Control keys
    ("G01","Eddie",K_EDDIE),
    ("F01","Frank",K_FRANK),
    ("E01","Giles",K_GILES),
    ("D01","Helen",K_HELEN),
    ("C01","Recall Trans",K_RECALLTRANS),
    ("B01","Cancel",K_CANCEL),
    ("A01","Clear",K_CLEAR),
    ("G02","Manage Till",K_MANAGETILL),
    ("F02","Manage Stock",K_MANAGESTOCK),
    ("E02","Use Stock",K_USESTOCK),
    ("G03","Print",K_PRINT),
    ("F03","Record Waste",K_WASTE), 
    ("E03","Price Check",K_PRICECHECK),
    ("G04","Manage Trans",K_MANAGETRANS),
    ("G05","Extras",K_EXTRAS),
    ("G06","Panic",K_PANIC), # Heh
    ("G07","Order Food",K_FOODORDER),
    ("G08","Cancel Food",K_CANCELFOOD),
    # Cursor keys, numeric keypad, cash/card keys, Quantity keys
    ("F15","Left",K_LEFT),
    ("G16","Up",K_UP),
    ("F16","Down",K_DOWN),
    ("F17","Right",K_RIGHT),
    ("D18",".",K_POINT),
    ("D19","0",K_ZERO),
    ("D20","00",K_ZEROZERO),
    ("E18","1",K_ONE),
    ("E19","2",K_TWO),
    ("E20","3",K_THREE),
    ("F18","4",K_FOUR),
    ("F19","5",K_FIVE),
    ("F20","6",K_SIX),
    ("G18","7",K_SEVEN),
    ("G19","8",K_EIGHT),
    ("G20","9",K_NINE),
    ("B19","Cash/Enter",K_CASH),
    ("C19","Card",K_CARD),
    ("C18","20",K_TWENTY),
    ("B18","10",K_TENNER),
    ("A18","5",K_FIVER),
    ("E17","Quantity",K_QUANTITY),
    ("E16","4pt Jug",K_4JUG),
    ("E15","Half",K_HALF),
    # Eventually all these keys will be managed by entries in the database
    # For now they are hard-coded here
    # Departments
    ("G14","Wine",K_DEPT9),
    ("F14","Soft",K_DEPT7),
    ("E14","Hot Drinks",K_DEPT11),
    # All line keys
    ("G09","Crisps",K_LINE1),
    ("G10","Line",K_LINE2),
    ("G11","Line",K_LINE3),
    ("G12","Line",K_LINE4),
    ("G13","Line",K_LINE5),
    ("G15","Line",K_LINE6),
    ("G17","Line",K_LINE7),
    ("F04","Half Cider 1",K_LINE10),
    ("F05","Half Cider 2",K_LINE11),
    ("F06","Half Cider 3",K_LINE12),
    ("F07","Half Cider 4",K_LINE13),
    ("F08","Half Cider 5",K_LINE14),
    ("F09","Nuts",K_LINE15),
    ("F10","Line",K_LINE16),
    ("F11","Line",K_LINE17),
    ("F12","Line",K_LINE18),
    ("F13","Line",K_LINE19),
    ("E04","Pint Cider 1",K_LINE20),
    ("E05","Pint Cider 2",K_LINE21),
    ("E06","Pint Cider 3",K_LINE22),
    ("E07","Pint Cider 4",K_LINE23),
    ("E08","Pint Cider 5",K_LINE24),
    ("E09","Scratchings",K_LINE25),
    ("E10","Line",K_LINE26),
    ("E11","Line",K_LINE27),
    ("E12","Line",K_LINE28),
    ("E13","Line",K_LINE29),
    ("D02","Half A1",K_LINE30),
    ("D03","Half A2",K_LINE31),
    ("D04","Half A3",K_LINE32),
    ("D05","Half A4",K_LINE33),
    ("D06","Half A5",K_LINE34),
    ("D07","Half A6",K_LINE35),
    ("D08","Half A7",K_LINE36),
    ("D09","Half A8",K_LINE37),
    ("D10","Half A9",K_LINE38),
    ("D11","Half A10",K_LINE39),
    ("D12","Half A11",K_LINE40),
    ("D13","Half A12",K_LINE41),
    ("D14","Half A13",K_LINE42),
    ("D15","Half A14",K_LINE43),
    ("D16","Half A15",K_LINE44),
    ("D17","Half A16",K_LINE45),
    ("C02","Pint A1",K_LINE46),
    ("C03","Pint A2",K_LINE47),
    ("C04","Pint A3",K_LINE48),
    ("C05","Pint A4",K_LINE49),
    ("C06","Pint A5",K_LINE50),
    ("C07","Pint A6",K_LINE51),
    ("C08","Pint A7",K_LINE52),
    ("C09","Pint A8",K_LINE53),
    ("C10","Pint A9",K_LINE54),
    ("C11","Pint A10",K_LINE55),
    ("C12","Pint A11",K_LINE56),
    ("C13","Pint A12",K_LINE57),
    ("C14","Pint A13",K_LINE58),
    ("C15","Pint A14",K_LINE59),
    ("C16","Pint A15",K_LINE60),
    ("C17","Pint A16",K_LINE61),
    ("B02","Half B1",K_LINE62),
    ("B03","Half B2",K_LINE63),
    ("B04","Half B3",K_LINE64),
    ("B05","Half B4",K_LINE65),
    ("B06","Half B5",K_LINE66),
    ("B07","Half B6",K_LINE67),
    ("B08","Half B7",K_LINE68),
    ("B09","Half B8",K_LINE69),
    ("B10","Half B9",K_LINE70),
    ("B11","Half B10",K_LINE71),
    ("B12","Half B11",K_LINE72),
    ("B13","Half B12",K_LINE73),
    ("B14","Half B13",K_LINE74),
    ("B15","Half B14",K_LINE75),
    ("B16","Half B15",K_LINE76),
    ("B17","Half B16",K_LINE77),
    ("A02","Pint B1",K_LINE78),
    ("A03","Pint B2",K_LINE79),
    ("A04","Pint B3",K_LINE80),
    ("A05","Pint B4",K_LINE81),
    ("A06","Pint B5",K_LINE82),
    ("A07","Pint B6",K_LINE83),
    ("A08","Pint B7",K_LINE84),
    ("A09","Pint B8",K_LINE85),
    ("A10","Pint B9",K_LINE86),
    ("A11","Pint B10",K_LINE87),
    ("A12","Pint B11",K_LINE88),
    ("A13","Pint B12",K_LINE89),
    ("A14","Pint B13",K_LINE90),
    ("A15","Pint B14",K_LINE91),
    ("A16","Pint B15",K_LINE92),
    ("A17","Pint B16",K_LINE93),
    ]),
    'kbtype':2,
    'pages':[
    (register.page,K_EDDIE,("Eve",register_hotkeys)),
    (register.page,K_FRANK,("Frank",register_hotkeys)),
    (register.page,K_GILES,("Giles",register_hotkeys)),
    (register.page,K_HELEN,("Helen",register_hotkeys))],
    }

kb3={ # New till keyboard
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard([
    # Control keys
    ("H01","Alice",K_ALICE),
    ("G01","Bob",K_BOB),
    ("F01","Charlie",K_CHARLIE),
    ("E01","Doris",K_DORIS),
    ("H02","Manage Till",K_MANAGETILL),
    ("H03","Print",K_PRINT),
    ("G02","Manage Stock",K_MANAGESTOCK),
    ("G03","Use Stock",K_USESTOCK),
    ("F02","Record Waste",K_WASTE),
    ("E02","Manage Trans",K_MANAGETRANS),
    ("D02","Apps",K_APPS),
    ("D01","Price Check",K_PRICECHECK),
    ("C01","Recall Trans",K_RECALLTRANS),
    ("B01","Cancel",K_CANCEL),
    ("A01","Clear",K_CLEAR),
    ("F12","Order Food",K_FOODORDER),
    ("F13","Cancel Food",K_CANCELFOOD),
    ("G13","Drink 'In'",K_DRINKIN),
    # Cursor keys, numeric keypad, cash/card keys, Quantity keys, modifiers
    ("D12","Left",K_LEFT),
    ("D14","Right",K_RIGHT),
    ("E13","Up",K_UP),
    ("D13","Down",K_DOWN),
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
    ("A14","£5",K_FIVER),
    ("B14","£10",K_TENNER),
    ("C14","£20",K_TWENTY),
    ("E12","Quantity",K_QUANTITY),
    ("A13","Half",K_HALF),
    ("B13","Double",K_DOUBLE),
    ("C13","4pt jug",K_4JUG),
    # Department keys
    ("G12","Soft",K_DEPT7),
    ("H12","Wine",K_DEPT9),
    ("H13","Hot Drinks",K_DEPT11),
    # Line keys
    ("H04","Line 1",K_LINE1),
    ("H05","Line 2",K_LINE2),
    ("H06","Line 3",K_LINE3),
    ("H07","Line 4",K_LINE4),
    ("H08","Line 5",K_LINE5),
    ("H09","Line 6",K_LINE6),
    ("H10","Line 7",K_LINE7),
    ("H11","Line 8",K_LINE8),
    ("G04","Line 11",K_LINE11),
    ("G05","Line 12",K_LINE12),
    ("G06","Line 13",K_LINE13),
    ("G07","Line 14",K_LINE14),
    ("G08","Line 15",K_LINE15),
    ("G09","Line 16",K_LINE16),
    ("G10","Line 17",K_LINE17),
    ("G11","Line 18",K_LINE18),
    ("F03","Line 21",K_LINE21),
    ("F04","Line 22",K_LINE22),
    ("F05","Line 23",K_LINE23),
    ("F06","Line 24",K_LINE24),
    ("F07","Line 25",K_LINE25),
    ("F08","Line 26",K_LINE26),
    ("F09","Line 27",K_LINE27),
    ("F10","Line 28",K_LINE28),
    ("F11","Line 29",K_LINE29),
    ("E03","Line 31",K_LINE31),
    ("E04","Line 32",K_LINE32),
    ("E05","Line 33",K_LINE33),
    ("E06","Line 34",K_LINE34),
    ("E07","Line 35",K_LINE35),
    ("E08","Line 36",K_LINE36),
    ("E09","Line 37",K_LINE37),
    ("E10","Line 38",K_LINE38),
    ("E11","Line 39",K_LINE39),
    ("D03","Line 41",K_LINE41),
    ("D04","Line 42",K_LINE42),
    ("D05","Line 43",K_LINE43),
    ("D06","Line 44",K_LINE44),
    ("D07","Line 45",K_LINE45),
    ("D08","Line 46",K_LINE46),
    ("D09","Line 47",K_LINE47),
    ("D10","Line 48",K_LINE48),
    ("D11","Line 49",K_LINE49),
    ("C02","Line 51",K_LINE51),
    ("C03","Line 52",K_LINE52),
    ("C04","Line 53",K_LINE53),
    ("C05","Line 54",K_LINE54),
    ("C06","Line 55",K_LINE55),
    ("C07","Line 56",K_LINE56),
    ("C08","Line 57",K_LINE57),
    ("C09","Line 58",K_LINE58),
    ("C10","Line 59",K_LINE59),
    ("C11","Line 60",K_LINE60),
    ("C12","Line 61",K_LINE61),
    ("B02","Line 62",K_LINE62),
    ("B03","Line 63",K_LINE63),
    ("B04","Line 64",K_LINE64),
    ("B05","Line 65",K_LINE65),
    ("B06","Line 66",K_LINE66),
    ("B07","Line 67",K_LINE67),
    ("B08","Line 68",K_LINE68),
    ("B09","Line 69",K_LINE69),
    ("B10","Line 70",K_LINE70),
    ("B11","Line 71",K_LINE71),
    ("B12","Line 72",K_LINE72),
    ("A02","Line 73",K_LINE73),
    ("A03","Line 74",K_LINE74),
    ("A04","Line 75",K_LINE75),
    ("A05","Line 76",K_LINE76),
    ("A06","Line 77",K_LINE77),
    ("A07","Line 78",K_LINE78),
    ("A08","Line 79",K_LINE79),
    ("A09","Line 80",K_LINE80),
    ("A10","Line 81",K_LINE81),
    ("A11","Line 82",K_LINE82),
    ("A12","Line 83",K_LINE83),
    ]),
    'kbtype':3,
    'pages':[
    (register.page,K_ALICE,("Alice",register_hotkeys)),
    (register.page,K_BOB,("Bob",register_hotkeys)),
    (register.page,K_CHARLIE,("Charlie",register_hotkeys)),
    (register.page,K_DORIS,("Doris",register_hotkeys))],
    }

stock_hotkeys={
    ord('s'): managestock,
    ord('S'): managestock,
    ord('a'): annotate,
    ord('A'): annotate,
    ord('r'): recordwaste,
    ord('R'): recordwaste,
    ord('t'): extrasmenu,
    ord('T'): extrasmenu,
    ord('m'): managetill,
    ord('M'): managetill,
    ord('l'): lockscreen,
    ord('L'): lockscreen,
    }

stockcontrol={
    'kbdriver':kbdrivers.curseskeyboard(),
    'kbtype':0,
    'pages':[(stockterminal.page,K_ALICE,(stock_hotkeys,["Bar"]))],
}    

# Config0 is a QWERTY-keyboard stock-control terminal
config0={'description':"Stock-control terminal"}
config0.update(std)
config0.update(stockcontrol)
config0.update(xpdfprinter) # XXX for testing
config0.update(labelprinter)

# Config1 is the main bar terminal
config1={'description':"Pembury Tavern main bar left hand till"}
config1.update(std)
config1.update(kb3)
config1.update(xpdfprinter) # XXX for testing
config1.update(labelprinter)
config1.update(kitchen)

# Config2 is the festival terminal
config2={'description':"Pembury Tavern festival bar"}
config2.update(std)
config2.update(kb2)
config2.update(xpdfprinter) # XXX for testing
config2.update(labelprinter)
config2.update(kitchen)

config3={'description':"Test menu file 'testmenu.py' in current directory",
         'kbdriver':kbdrivers.curseskeyboard(),
         'kbtype':0,
         'menuurl':"file:testmenu.py",
         'kitchenprinter':nullprinter(),
         'pages':[(foodcheck.page,keyboard.K_ALICE,([],))],
         }
config3.update(std)
config3.update(xpdfprinter)

# Config4 is the second main bar terminal
config4={'description':"Pembury Tavern main bar right hand till"}
config4.update(std)
config4.update(kb3)
config4.update(xpdfprinter) # XXX for testing
config4.update(labelprinter)
config4.update(kitchen)

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
    'festivalbar': config2,
    'testmenu': config3,
    'secondtill': config4,
    }
