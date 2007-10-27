#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""Till configuration file for the Coalheavers Arms.

"""

import sys,os,math,logging
# Local test version for new keycaps scheme
#sys.path.append('../quicktill-0.7.1')

# Were we invoked automatically, i.e. are we the real till instance,
# or just a test copy?
autorun=False
if len(sys.argv)>1 and sys.argv[1]=='auto':
    autorun=True

# Training mode involves using a different database, and having a
# prominent notice at the top of the screen.
training=False
if len(sys.argv)>1 and sys.argv[1]=='training':
    training=True

if autorun:
    f=file('till.pid','w')
    f.write("%d\n"%os.getpid())
    f.close()

from keyboard import *
from pdrivers import Epson_TM_U220,nullprinter
import tillconfig,till,register,kbdrivers

tillconfig.configversion="$Id: coalheavers.py,v 1.5 2005/03/21 12:59:25 till Exp $"
tillconfig.pubname="The Coalheavers Arms"
tillconfig.pubnumber="01733 565664"
tillconfig.pubaddr=("5 Park Street","Peterborough","PE2 9BH")

tillconfig.vatrate=0.175
tillconfig.vatno="783 9983 50"
tillconfig.companyaddr=(
    "Individual Pubs Limited","Unit 111, Norman Ind. Estate",
    "Cambridge Road, Milton","Cambridge CB4 6AT")

tillconfig.currency="£"

if training:
    dbname=":training"
else:
    dbname=":coalheavers"

# For each key on the keyboard we record
# (location, legend, keycode)
kbdrv=kbdrivers.prehkeyboard([
    ("G01","Alice",K_ALICE),
    ("F01","Bob",K_BOB),
    ("E01","Charlie",K_CHARLIE),
    ("C01","Clear",K_CLEAR),
    ("D01","Cancel",K_CANCEL),
    ("D02","Use Stock",K_USESTOCK),
    ("C02","Manage Stock",K_MANAGESTOCK),
    ("D03","Record Waste",K_WASTE),
    ("C03","Manage Till",K_MANAGETILL),
    ("G02","Print",K_PRINT),
    ("F02","Recall Trans",K_RECALLTRANS),
    ("E02","Price Check",K_PRICECHECK),
    ("C07","Left",K_LEFT),
    ("D08","Up",K_UP),
    ("C08","Down",K_DOWN),
    ("C09","Right",K_RIGHT),
    ("C10",".",K_POINT),
    ("C11","0",K_ZERO),
    ("C12","00",K_ZEROZERO),
    ("D10","1",K_ONE),
    ("D11","2",K_TWO),
    ("D12","3",K_THREE),
    ("E10","4",K_FOUR),
    ("E11","5",K_FIVE),
    ("E12","6",K_SIX),
    ("F10","7",K_SEVEN),
    ("F11","8",K_EIGHT),
    ("F12","9",K_NINE),
    ("D09","Quantity",K_QUANTITY),
    ("B11","Cash/Enter",K_CASH),
    ("G10","£20",K_TWENTY),
    ("G11","£10",K_TENNER),
    ("G12","£5",K_FIVER),
    ("G08","Spirits",K_DEPT4),
    ("G09","Misc",K_DEPT8),
    ("F08","Wine",K_DEPT9),
    ("F09","Soft",K_DEPT7),
    ("E08","Food",K_DEPT10),
    ("E09","Bottles",K_DEPT6),
    ("G03","Plain Crisps",K_LINE1),
    ("G04","Cheese & Onion",K_LINE2),
    ("G05","Salt & Vinegar",K_LINE3),
    ("G06","Salt & Pepper",K_LINE4),
    ("G07","Roast Ox Crisps",K_LINE5),
    ("F03","Salted Nuts",K_LINE6),
    ("F04","Dry Roast Nuts",K_LINE7),
    ("F05","Chilli Nuts",K_LINE8),
    ("F06","Fruit & Nuts",K_LINE9),
    ("F07","Honey Nuts",K_LINE10),
    ("E03","Pistachio Nuts",K_LINE11),
    ("E04","Twiglets",K_LINE12),
    ("E05","Mini Cheddars",K_LINE13),
    ("E06","Wheat Crunchies",K_LINE14),
    ("E07","Pickles",K_LINE15),
    ("D04","Scampi Fries",K_LINE16),
    ("D05","Bacon Fries",K_LINE17),
    ("D06","Cheese Moments",K_LINE18),
    ("D07","Pork Scratchings",K_LINE19),
    ("C04","Peperami",K_LINE20),
    ("C05","Chocolate",K_LINE21),
    ("C06","Cockles",K_LINE22),
    ("B01","Half 1",K_LINE23),
    ("B02","Half 2",K_LINE24),
    ("B03","Half 3",K_LINE25),
    ("B04","Half 4",K_LINE26),
    ("B05","Half 5",K_LINE27),
    ("B06","Half 6",K_LINE28),
    ("B07","Half 7",K_LINE29),
    ("B08","Half 8",K_LINE30),
    ("B09","Half Lager",K_LINE31),
    ("B10","Half Cider",K_LINE32),
    ("A01","Pint 1",K_LINE33),
    ("A02","Pint 2",K_LINE34),
    ("A03","Pint 3",K_LINE35),
    ("A04","Pint 4",K_LINE36),
    ("A05","Pint 5",K_LINE37),
    ("A06","Pint 6",K_LINE38),
    ("A07","Pint 7",K_LINE39),
    ("A08","Pint 8",K_LINE40),
    ("A09","Pint Lager",K_LINE41),
    ("A10","Pint Cider",K_LINE42),
    ("A13","Card",K_CARD),
    ("A14","Manage Trans",K_MANAGETRANS),
    ("M1H","Magstripe 1 Header",K_M1H),
    ("M1T","Magstripe 1 Trailer",K_M1T),
    ("M2H","Magstripe 2 Header",K_M2H),
    ("M2T","Magstripe 2 Trailer",K_M2T),
    ("M3H","Magstripe 3 Header",K_M3H),
    ("M3T","Magstripe 3 Trailer",K_M3T),
])

tillconfig.kbtype=1

if autorun or training:
    pdriver=Epson_TM_U220("/dev/lp0",57)
else:
    pdriver=nullprinter()

tillconfig.has_media_slot=True
tillconfig.cashback_limit=50.0

# Define log output here?
log=logging.getLogger()
formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler=logging.StreamHandler()
handler.setFormatter(formatter)
handler.setLevel(logging.ERROR)
log.addHandler(handler)
if autorun:
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    debughandler=logging.FileHandler("debug.log")
    debughandler.setLevel(logging.DEBUG)
    debughandler.setFormatter(formatter)
    infohandler=logging.FileHandler("info.log")
    infohandler.setLevel(logging.INFO)
    infohandler.setFormatter(formatter)
    errorhandler=logging.FileHandler("error.log")
    errorhandler.setLevel(logging.ERROR)
    errorhandler.setFormatter(formatter)
    log.addHandler(debughandler)
    log.addHandler(infohandler)
    log.addHandler(errorhandler)
    log.setLevel(logging.DEBUG)

# Price policy function here?  Not needed for Coalheavers because
# there are no variable item prices.

# Price guess algorithm goes here
def priceguess(dept,cost,abv):
    if dept==1:
        return guessbeer(cost,abv)
    if dept==2:
        return 2.60
    if dept==3:
        return 2.40
    if dept==5:
        return guesssnack(cost)
    return None
tillconfig.priceguess=priceguess

# Unit is a pint
def guessbeer(cost,abv):
    if abv is None: return None
    if abv<3.2: r=1.80
    elif abv<3.6: r=1.90
    elif abv<4.0: r=2.00
    elif abv<4.4: r=2.10
    elif abv<4.9: r=2.20
    elif abv<5.3: r=2.30
    elif abv<5.7: r=2.40
    elif abv<6.0: r=2.50
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+13.0)/72.0
    if cost>idealcost:
        r=r+((cost-idealcost)*(tillconfig.vatrate+1.0))
        r=math.ceil(r*10.0)/10.0
    return r

def guesssnack(cost):
    return math.ceil(cost*2.0*(tillconfig.vatrate+1.0)*10.0)/10.0

if training:
    pages=[(register.page,K_ALICE,("Training A",)),
           (register.page,K_BOB,("Training B",)),
           (register.page,K_CHARLIE,("Training C",))]
else:
    pages=[(register.page,K_ALICE,("Alice",)),
           (register.page,K_BOB,("Bob",)),
           (register.page,K_CHARLIE,("Charlie",))]

till.run(dbname,kbdrv,pdriver,pdriver.kickout,pages)
