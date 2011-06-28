# -*- coding: utf-8 -*-

import quicktill.keyboard as keyboard
import quicktill.extras as extras
import quicktill.foodcheck as foodcheck
from quicktill.keyboard import *
from quicktill.pdrivers import nullprinter,Epson_TM_U220,pdf,pdflabel,A4
from quicktill import register,ui,kbdrivers,stockterminal
from quicktill.managetill import popup as managetill
from quicktill.managestock import popup as managestock
from quicktill.plu import popup as plu
from quicktill.usestock import popup as usestock
from quicktill.recordwaste import popup as recordwaste
from quicktill.stock import annotate
import math
import os

#vatrate=0.175
# VAT rate changed 1/12/2008
#vatrate=0.150
# VAT rate changed again 1/1/2010
vatrate=0.175

def pembury_deptkeycheck(dept,price):
    """Check that the price entered when a department key is pressed is
    appropriate for that department.  Returns either None (no problem
    found), a string or a list of strings to display to the user.

    """
    if dept==7: # Soft drinks
        if price not in [0.40,0.80,1.60,1.00]:
            return (u"Soft drinks are 40p for a mixer, 80p for a half, "
                    u"and £1.60 for a pint.  If you're selling a bottle, "
                    u"you must press the appropriate button for that bottle.")
    if dept==9: # Wine
        if price not in [2.50,3.50,10.00,3.00,4.00,3.40,4.70,4.00,12.00,14.00]:
            return ([u"Valid prices for wine are £2.50 for a medium glass, "
                     u"£3.50 for a large glass, and £10.00 for a bottle.  "
                     u"If you are selling any of the other wines by the "
                     u"bottle, you should press the \"Wine Bottle\" key "
                     u"instead.","",u"Mulled Mead is £3.40 for a 175ml glass.",
                     u"Mead by the glass: £3.00/£4.00 for Monks Mead, "
                     u"£3.40/£4.70 for Moniack.  Bottles are £12.00 for "
                     u"Monks Mead, £14.00 for Moniack."])

# Price policy function
def pembury_pricepolicy(sd,qty):
    # Start with the standard price
    price=sd['saleprice']*qty
    if sd['dept']==4 and qty==2.0: price=price-0.50
    if sd['dept']==1 and qty==4.0: price=price-1.00
    return price

# Price guess algorithm goes here
def pembury_priceguess(dept,cost,abv):
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
    if abv<3.1: r=2.40
    elif abv<3.3: r=2.50
    elif abv<3.8: r=2.60
    elif abv<4.2: r=2.70
    elif abv<4.7: r=2.80
    elif abv<5.2: r=2.90
    elif abv<5.7: r=3.00
    elif abv<6.2: r=3.10
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+18.0)/72.0
    if cost>idealcost:
        r=r+((cost-idealcost)*(vatrate+1.0))
        r=math.ceil(r*10.0)/10.0
    return r

def guesskeg(cost,abv):
    if abv==5.0: return 3.10 # Budvar
    if abv==4.4: return 3.00 # Moravka
    return None

def guesssnack(cost):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessbottle(cost):
    return math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0

def guesswine(cost):
    return math.ceil(cost*2.0*(vatrate+1.0)*10.0)/10.0

def guessspirit(cost,abv):
    return max(2.00,math.ceil(cost*2.5*(vatrate+1.0)*10.0)/10.0)

def guesscider(cost,abv):
    return math.ceil(cost*2.6*(vatrate+1.0)*10.0)/10.0

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
    extras.reminderpopup((22,50),"Outside area reminder",[
            "Please check the triangular outdoor area and remind everyone "
            "out there that it will be cleared and locked up at 11pm."])
    extras.reminderpopup((23,0),"Outside area reminder",[
            "Please clear everyone out of the triangular outdoor area "
            "and lock the gate and the door."])
    extras.reminderpopup((23,10),"Outside area reminder",[
            "Please check that the triangular outdoor area is locked up "
            "and clear of seats and glasses - this should have been done "
            "at 11pm."])

# This token and secret are for the indpubs twitter account, and are
# probably out of date (and invalid) by now.  To generate a token and
# secret for your own twitter account, do the following:
# $ python
# >>> import quicktill.extras
# >>> quicktill.extras.twitter_auth()
# Follow the prompts - you will generate a PIN using your web browser and
# then type it in to get the token and secret.
tapi=extras.twitter_api(token='324415141-A7Ygvhi3YOMU7tRFys9GG9N5GZe1qJJFLKHMlSAY',
                        token_secret='WfwmwGHyKTdaqIyVjUSpbbPLPhuCrSkr9cqvoMT4Mc')

class tilltwitter(ui.dismisspopup):
    def __init__(self):
        try:
            user=tapi.VerifyCredentials()
        except:
            ui.infopopup(["Unable to connect to Twitter"],
                         title="Error")
            return
        ui.dismisspopup.__init__(self,7,76,
                                 title="@%s Twitter"%user.screen_name,
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Type in your update here and press Enter:")
        self.tfield=ui.editfield(
            4,2,72,flen=140,keymap={
                keyboard.K_CLEAR: (self.dismiss,None),
                keyboard.K_CASH: (self.enter,None,False)})
        self.tfield.focus()
    def enter(self):
        ttext=self.tfield.f
        if len(ttext)<20:
            ui.infopopup(title="Twitter Problem",text=[
                    "That's too short!  Try typing some more."])
            return
        tapi.PostUpdate(ttext)
        self.dismiss()
        ui.infopopup(title="Twittered",text=["Your update has been posted."],
                     dismiss=keyboard.K_CASH,colour=ui.colour_confirm)

def extrasmenu():
    menu=[
        (keyboard.K_ONE,"Bar Billiards checker",extras.bbcheck,None),
        (keyboard.K_TWO,"Train Departure Times",departures,None),
        (keyboard.K_THREE,"Reboot the wireless access point",
         wireless_command,("reboot",)),
        (keyboard.K_FOUR,"Turn the wireless off",
         wireless_command,("ifdown lan",)),
        (keyboard.K_FIVE,"Turn the wireless on",
         wireless_command,("ifup lan",)),
        ]
    if configname=='mainbar':
        menu.append(
            (keyboard.K_SIX,"Coffee pot timer",extras.managecoffeealarm,
             (coffeealarm,)))
    menu.append((keyboard.K_SEVEN,"Post a twitter",tilltwitter,None))
    ui.keymenu(menu,"Extras")

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
    999: panickey,
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
    'allow_tabs':False,
    'nosale':False,
    'checkdigit_print':True,
    'checkdigit_on_usestock':True,
}

kitchen={
    'kitchenprinter':Epson_TM_U220(
    ('testprinter.pembury.i.individualpubs.co.uk',9100),57),
#    'kitchenprinter':nullprinter(),
    'menuurl':'http://till.pembury.i.individualpubs.co.uk:8080/foodmenu.py',
#    'menuurl':'http://localhost:8080/foodmenu.py',
    }

noprinter={
    'printer': (nullprinter,()),
    }
localprinter={
#    'printer': ((Epson_TM_U220),(('testprinter',9100),76,'iso-8859-1',True)),
    'printer': (nullprinter,()),
    }
pdfprinter={
    'printer': (pdf,("lpr %s",)),
    }
xpdfprinter={
    'printer': (pdf,("xpdf %s",)),
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

kb1={
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard([
    # control keys
    ("G01","Alice",K_ALICE),
    ("F01","Bob",K_BOB),
    ("E01","Charlie",K_CHARLIE),
    ("D01","Doris",K_DORIS),
    ("C01","Clear",K_CLEAR),
    ("G02","Manage Till",K_MANAGETILL),
    ("F02","Manage Stock",K_MANAGESTOCK),
    ("E02","Record Waste",K_WASTE),
    ("D02","Recall Trans",K_RECALLTRANS),
    ("C02","Cancel",K_CANCEL),
    ("G03","Print",K_PRINT),
    ("F03","Use Stock",K_USESTOCK),
    ("E03","Manage Trans",K_MANAGETRANS),
    ("D03","Price Check",K_PRICECHECK),
    ("C03","Extras",K_EXTRAS),
    # Cursor keys, numeric keypad, cash/card keys, Quantity keys
    ("C15","Left",K_LEFT),
    ("D16","Up",K_UP),
    ("C16","Down",K_DOWN),
    ("C17","Right",K_RIGHT),
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
    ("D17","Quantity",K_QUANTITY),
    ("E17","Double",K_DOUBLE),
    ("E16","4pt Jug",K_4JUG),
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
    ("G15","Wine",K_DEPT9),
    ("G16","Misc",K_DEPT8),
    ("G17","Hot Drinks",K_DEPT11),
    ("F15","Drink 'In'",K_DRINKIN),
    ("F16","Soft",K_DEPT7),
    ("F17","Food",K_DEPT10),
    # All line keys
    ("G04","Line 2",K_LINE2),
    ("G05","Line 3",K_LINE3),
    ("G06","Line 4",K_LINE4),
    ("G07","Line 5",K_LINE5),
    ("G08","Line 6",K_LINE6),
    ("G09","Order Food",K_FOODORDER),
    ("G10","Line 8",K_LINE8),
    ("G11","Line 9",K_LINE9),
    ("G12","Line 10",K_LINE10),
    ("G13","Line 11",K_LINE11),
    ("G14","Line 12",K_LINE12),
    ("F04","Line 15",K_LINE15),
    ("F05","Line 16",K_LINE16),
    ("F06","Line 17",K_LINE17),
    ("F07","Line 18",K_LINE18),
    ("F08","Line 19",K_LINE19),
    ("F09","Cancel Food",K_CANCELFOOD),
    ("F10","Line 21",K_LINE21),
    ("F11","Line 22",K_LINE22),
    ("F12","Line 23",K_LINE23),
    ("F13","Line 24",K_LINE24),
    ("F14","Line 25",K_LINE25),
    ("E04","Line 28",K_LINE28),
    ("E05","Line 29",K_LINE29),
    ("E06","Line 30",K_LINE30),
    ("E07","Line 31",K_LINE31),
    ("E08","Line 32",K_LINE32),
    ("E09","Line 33",K_LINE33),
    ("E10","Line 34",K_LINE34),
    ("E11","Line 35",K_LINE35),
    ("E12","Line 36",K_LINE36),
    ("E13","Line 37",K_LINE37),
    ("E14","Line 38",K_LINE38),
    ("E15","Line 39",K_LINE39),
    ("D04","Line 41",K_LINE41),
    ("D05","Line 42",K_LINE42),
    ("D06","Line 43",K_LINE43),
    ("D07","Line 44",K_LINE44),
    ("D08","Line 45",K_LINE45),
    ("D09","Line 46",K_LINE46),
    ("D10","Line 47",K_LINE47),
    ("D11","Line 48",K_LINE48),
    ("D12","Line 49",K_LINE49),
    ("D13","Line 50",K_LINE50),
    ("D14","Line 51",K_LINE51),
    ("D15","Line 52",K_LINE52),
    #("C03","Line 53",K_LINE53), # Now the "extras" button
    ("C04","Line 54",K_LINE54),
    ("C05","Line 55",K_LINE55),
    ("C06","Line 56",K_LINE56),
    ("C07","Line 57",K_LINE57),
    ("C08","Line 58",K_LINE58),
    ("C09","Line 59",K_LINE59),
    ("C10","Line 60",K_LINE60),
    ("C11","Line 61",K_LINE61),
    ("C12","Line 62",K_LINE62),
    ("C13","Line 63",K_LINE63),
    ("C14","Line 64",K_LINE64),
    # Pints/halves
    ("B01","Half 1",K_LINE65),
    ("B02","Half 2",K_LINE66),
    ("B03","Half 3",K_LINE67),
    ("B04","Half 4",K_LINE68),
    ("B05","Half 5",K_LINE69),
    ("B06","Half 6",K_LINE70),
    ("B07","Half 7",K_LINE71),
    ("B08","Half 8",K_LINE72),
    ("B09","Half 9",K_LINE73),
    ("B10","Half 10",K_LINE74),
    ("B11","Half 11",K_LINE75),
    ("B12","Half 12",K_LINE76),
    ("B13","Half 13",K_LINE77),
    ("B14","Half 14",K_LINE78),
    ("B15","Half 15",K_LINE79),
    ("B16","Half 16",K_LINE80),
    ("B17","Half Budvar",K_LINE81),
    ("A01","Pint 1",K_LINE82),
    ("A02","Pint 2",K_LINE83),
    ("A03","Pint 3",K_LINE84),
    ("A04","Pint 4",K_LINE85),
    ("A05","Pint 5",K_LINE86),
    ("A06","Pint 6",K_LINE87),
    ("A07","Pint 7",K_LINE88),
    ("A08","Pint 8",K_LINE89),
    ("A09","Pint 9",K_LINE90),
    ("A10","Pint 10",K_LINE91),
    ("A11","Pint 11",K_LINE92),
    ("A12","Pint 12",K_LINE93),
    ("A13","Pint 13",K_LINE94),
    ("A14","Pint 14",K_LINE95),
    ("A15","Pint 15",K_LINE96),
    ("A16","Pint 16",K_LINE97),
    ("A17","Pint Budvar",K_LINE98),
    ]),
    'kbtype':1,
    'pages':[
    (register.page,K_ALICE,("Alice",register_hotkeys)),
    (register.page,K_BOB,("Bob",register_hotkeys)),
    (register.page,K_CHARLIE,("Charlie",register_hotkeys)),
    (register.page,K_DORIS,("Doris",register_hotkeys))],
    }

kb2={
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard([
    # Left-hand two columns - control keys
    ("G01","Eddie",K_EDDIE),
    ("F01","Frank",K_FRANK),
    ("E01","Giles",K_GILES),
    ("D01","Helen",K_HELEN),
    ("C01","Recall Trans",K_RECALLTRANS),
    ("B01","Manage Trans",K_MANAGETRANS),
    ("A01","Clear",K_CLEAR),
    ("G02","Manage Till",K_MANAGETILL),
    ("F02","Manage Stock",K_MANAGESTOCK),
    ("E02","Use Stock",K_USESTOCK),
    ("D02","Record Waste",K_WASTE),
    ("C02","Print",K_PRINT),
    ("B02","Cancel",K_CANCEL),
    ("A02","Price Check",K_PRICECHECK),
    # Cursor keys, numeric keypad, cash/card keys, Quantity keys
    ("C11","Left",K_LEFT),
    ("D12","Up",K_UP),
    ("C12","Down",K_DOWN),
    ("C13","Right",K_RIGHT),
    ("D14",".",K_POINT),
    ("D15","0",K_ZERO),
    ("D16","00",K_ZEROZERO),
    ("E14","1",K_ONE),
    ("E15","2",K_TWO),
    ("E16","3",K_THREE),
    ("F14","4",K_FOUR),
    ("F15","5",K_FIVE),
    ("F16","6",K_SIX),
    ("G14","7",K_SEVEN),
    ("G15","8",K_EIGHT),
    ("G16","9",K_NINE),
    ("B15","Cash/Enter",K_CASH),
    ("C15","Card",K_CARD),
    ("C14","20",K_TWENTY),
    ("B14","10",K_TENNER),
    ("A14","5",K_FIVER),
    ("D13","Quantity",K_QUANTITY),
    ("E13","Double",K_DOUBLE),
    ("E12","4pt Jug",K_4JUG),
    ("H11","Order Food",K_FOODORDER),
    ("H12","Cancel Food",K_CANCELFOOD),
    # Eventually all these keys will be managed by entries in the database
    # For now they are hard-coded here
    # Departments
    ("G11","Wine",K_DEPT9),
    ("G12","Misc",K_DEPT8),
    ("G13","Hot Drinks",K_DEPT11),
    ("F11","Drink 'In'",K_DRINKIN),
    ("F12","Soft",K_DEPT7),
    ("F13","Food",K_DEPT10),
    # All line keys
    ("H03","Half Cider 1",K_LINE1),
    ("H04","Half Cider 2",K_LINE2),
    ("H05","Half Cider 3",K_LINE3),
    ("H06","Half Cider 4",K_LINE4),
    ("H07","Half Cider 5",K_LINE5),
    ("H08","Half Cider 6",K_LINE6),
    ("H09","Half Cider 7",K_LINE7),
    ("H10","Half Cider 8",K_LINE8),
    ("G03","Pint Cider 1",K_LINE11),
    ("G04","Pint Cider 2",K_LINE12),
    ("G05","Pint Cider 3",K_LINE13),
    ("G06","Pint Cider 4",K_LINE14),
    ("G07","Pint Cider 5",K_LINE15),
    ("G08","Pint Cider 6",K_LINE16),
    ("G09","Pint Cider 7",K_LINE17),
    ("G10","Pint Cider 8",K_LINE18),
    ("F03","Half A1",K_LINE21),
    ("F04","Half A2",K_LINE22),
    ("F05","Half A3",K_LINE23),
    ("F06","Half A4",K_LINE24),
    ("F07","Half A5",K_LINE25),
    ("F08","Half A6",K_LINE26),
    ("F09","Half A7",K_LINE27),
    ("F10","Half A8",K_LINE28),
    ("E03","Pint A1",K_LINE31),
    ("E04","Pint A2",K_LINE32),
    ("E05","Pint A3",K_LINE33),
    ("E06","Pint A4",K_LINE34),
    ("E07","Pint A5",K_LINE35),
    ("E08","Pint A6",K_LINE36),
    ("E09","Pint A7",K_LINE37),
    ("E10","Pint A8",K_LINE38),
    ("D03","Half B1",K_LINE41),
    ("D04","Half B2",K_LINE42),
    ("D05","Half B3",K_LINE43),
    ("D06","Half B4",K_LINE44),
    ("D07","Half B5",K_LINE45),
    ("D08","Half B6",K_LINE46),
    ("D09","Half B7",K_LINE47),
    ("D10","Half B8",K_LINE48),
    ("C03","Pint B1",K_LINE51),
    ("C04","Pint B2",K_LINE52),
    ("C05","Pint B3",K_LINE53),
    ("C06","Pint B4",K_LINE54),
    ("C07","Pint B5",K_LINE55),
    ("C08","Pint B6",K_LINE56),
    ("C09","Pint B7",K_LINE57),
    ("C10","Pint B8",K_LINE58),
    ("B03","Half C1",K_LINE61),
    ("B04","Half C2",K_LINE62),
    ("B05","Half C3",K_LINE63),
    ("B06","Half C4",K_LINE64),
    ("B07","Half C5",K_LINE65),
    ("B08","Half C6",K_LINE66),
    ("B09","Half C7",K_LINE67),
    ("B10","Half C8",K_LINE68),
    ("A03","Pint C1",K_LINE71),
    ("A04","Pint C2",K_LINE72),
    ("A05","Pint C3",K_LINE73),
    ("A06","Pint C4",K_LINE74),
    ("A07","Pint C5",K_LINE75),
    ("A08","Pint C6",K_LINE76),
    ("A09","Pint C7",K_LINE77),
    ("A10","Pint C8",K_LINE78),
    ("H01","Unlabelled",K_LINE81),
    ("H02","Unlabelled",K_LINE82),
    ("E11","Unlabelled",K_LINE83),
    ("D11","Unlabelled",K_LINE84),
    ("B11","Unlabelled",K_LINE85),
    ("B12","Unlabelled",K_LINE86),
    ("B13","Unlabelled",K_LINE87),
    ("A11","Unlabelled",K_LINE88),
    ("A12","Unlabelled",K_LINE89),
    ("A13","Unlabelled",K_LINE90),
    ("H13","Panic",999), # Heh
    ("H14","Unlabelled",K_LINE91),
    ("H15","Unlabelled",K_LINE92),
    ("H16","Extras",K_EXTRAS),
    ]),
    'kbtype':2,
    'pages':[
    (register.page,K_EDDIE,("Eddie",register_hotkeys)),
    (register.page,K_FRANK,("Frank",register_hotkeys)),
    (register.page,K_GILES,("Giles",register_hotkeys)),
    (register.page,K_HELEN,("Helen",register_hotkeys))],
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
    }

stockcontrol={
    'kbdriver':kbdrivers.curseskeyboard(),
    'kbtype':0,
    'pages':[(stockterminal.page,K_ALICE,(stock_hotkeys,))],
}    

# Config0 is a QWERTY-keyboard stock-control terminal
config0={'description':"Stock-control terminal"}
config0.update(std)
config0.update(stockcontrol)
config0.update(localprinter)
config0.update(labelprinter)

# Config1 is the main bar terminal
config1={'description':"Pembury Tavern main bar"}
config1.update(std)
config1.update(kb1)
config1.update(xpdfprinter)
config1.update(labelprinter)
config1.update(kitchen)

# Config2 is the festival terminal
config2={'description':"Pembury Tavern festival bar"}
config2.update(std)
config2.update(kb2)
config2.update(localprinter)
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
    }
