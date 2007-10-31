# -*- coding: iso-8859-1 -*-

import quicktill.keyboard as keyboard
import quicktill.extras as extras
from quicktill.keyboard import *
from quicktill.pdrivers import Epson_TM_U220,pdf,pdflabel,A4
from quicktill import register,ui,kbdrivers,stockterminal
from quicktill.managetill import popup as managetill
from quicktill.managestock import popup as managestock
from quicktill.plu import popup as plu
from quicktill.usestock import popup as usestock
from quicktill.recordwaste import popup as recordwaste
from quicktill.stock import annotate

def pricepolicy(sd,qty):
    # Start with the standard price
    price=sd['saleprice']*qty
    # House doubles are 2.60
    if sd['dept']==4 and qty==2.0 and sd['saleprice']==1.50:
        price=2.60
    # Double single malts are 3.50
    if sd['dept']==4 and qty==2.0 and sd['saleprice']==2.00:
        price=3.50
    return price

# Price guess algorithm goes here
def priceguess(dept,cost,abv):
    if dept==1:
        return guessbeer(cost,abv)
    if dept==2:
        return guesskeg(cost,abv)
    if dept==3:
        return guesscider(cost,abv)
    if dept==5:
        return guesssnack(cost)
    return None

# Unit is a pint
def guessbeer(cost,abv):
    if abv is None: return None
    if abv<3.1: r=2.10
    elif abv<3.3: r=2.20
    elif abv<3.8: r=2.30
    elif abv<4.2: r=2.40
    elif abv<4.7: r=2.50
    elif abv<5.2: r=2.60
    elif abv<5.7: r=2.70
    elif abv<6.2: r=2.80
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+13.0)/72.0
    if cost>idealcost:
        r=r+((cost-idealcost)*(tillconfig.vatrate+1.0))
        r=math.ceil(r*10.0)/10.0
    return r

def guesskeg(cost,abv):
    if abv==5.0: return 2.70 # Budvar
    return None

def guesssnack(cost):
    return math.ceil(cost*2.0*(tillconfig.vatrate+1.0)*10.0)/10.0

def guesscider(cost,abv):
    return math.ceil(cost*2.1*(tillconfig.vatrate+1.0)*10.0)/10.0

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

def extrasmenu():
    menu=[
        (keyboard.K_ONE,"Bar Billiards checker",extras.bbcheck,None),
        (keyboard.K_TWO,"Train Departure Times",departures,None),
        ]
    ui.keymenu(menu,"Extras")

register_hotkeys={
    K_PRICECHECK: plu,
    K_MANAGETILL: managetill,
    K_MANAGESTOCK: managestock,
    K_USESTOCK: usestock,
    K_WASTE: recordwaste,
    K_EXTRAS: extrasmenu,
    }

std={
    'pubname':"The Pembury Tavern",
    'pubnumber':"020 8986 8597",
    'pubaddr':("90 Amhurst Road","London E8 1JH"),
    'vatrate':0.175,
    'vatno':"783 9983 50",
    'companyaddr':("Individual Pubs Limited","Unit 111, Norman Ind. Estate",
                   "Cambridge Road, Milton","Cambridge CB24 6AT"),
    'currency':"£",
    'cashback_limit':50.0,
    'pricepolicy':pricepolicy,
    'priceguess':priceguess,
    'database':'dbname=pembury',
}

kitchen={
    'kitchenprinter':Epson_TM_U220(
    ('kitchenprinter.pembury.i.individualpubs.co.uk',4010),57),
    'menuurl':'http://till5.pembury.i.individualpubs.co.uk:8080/foodmenu.py',
    }

localprinter={
    'printer': (Epson_TM_U220,("/dev/lp0",57)),
    }
pdfprinter={
    'printer': (pdf,("xpdf %s",)),
    }
# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4=[2,4,"99.1mm","67.7mm","3mm","0mm",A4]
staples_3by6=[3,6,"63.5mm","46.6mm","2.8mm","0mm",A4]
labelprinter={
    'labelprinter': (pdflabel,["lpr %s"]+staples_3by6),
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

config0=dict()
config0.update(std)
config0.update(stockcontrol)
config0.update(pdfprinter)
config0.update(labelprinter)

config1=dict()
config1.update(std)
config1.update(kb1)
config1.update(localprinter)
config1.update(labelprinter)
config1.update(kitchen)

# Things to define:
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
    0: config0,
    1: config1,
    }
