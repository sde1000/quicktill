#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""Till configuration file for the Oakdale Arms main till.

(There may be a sub-till for the festival bar, with a different
keyboard layout.)

"""

import sys,os,sets,time,math,logging,urllib
#sys.path.append('../quicktill-0.7.5')

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
import keyboard
from pdrivers import Epson_TM_U220,nullprinter
import tillconfig,till,register,kbdrivers

if training:
    dbname=":training"
else:
    dbname=":oakdale"

# For each key on the keyboard we record
# (location, legend, keycode)
kbdrv=kbdrivers.prehkeyboard([
    # Left-hand two columns - control keys
    ("G01","Alice",K_ALICE),
    ("F01","Bob",K_BOB),
    ("E01","Charlie",K_CHARLIE),
    ("D01","Doris",K_DORIS),
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
    ("C18","£20",K_TWENTY),
    ("B18","£10",K_TENNER),
    ("A18","£5",K_FIVER),
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
    ("G03","Salted Nuts",K_LINE1),
    ("G04","Dry Roast Nuts",K_LINE2),
    ("G05","Peperami Red",K_LINE3),
    ("G06","Peperami Green",K_LINE4),
    ("G07","Twiglets",K_LINE5),
    ("G08","Order Food",K_FOODORDER),
    ("G09","Bacardi Breezer",K_LINE7),
    ("G10","Smirnoff Ice",K_LINE8),
    ("G11","Unmarked",K_LINE9),
    ("G12","Guinness F.E.",K_LINE10),
    ("G13","Gold Label",K_LINE11),
    ("G14","Duchesse",K_LINE12),
    ("F03","Sea Salt Crisps",K_LINE14),
    ("F04","Jalapeno Pepper",K_LINE15),
    ("F05","Poppadums",K_LINE16),
    ("F06","Salt & Pepper",K_LINE17),
    ("F07","Pork Scratchings",K_LINE18),
    ("F08","Cancel Food",K_CANCELFOOD),
    ("F09","Tonic",K_LINE20),
    ("F10","Diet Tonic",K_LINE21),
    ("F11","J2O",K_LINE22),
    ("F12","Other Bottled Beer",K_LINE23),
    ("F13","Orval",K_LINE24),
    ("F14","Val-Dieu",K_LINE25),
    ("E03","Mini Cheddars",K_LINE27),
    ("E04","Plain Crisps",K_LINE28),
    ("E05","Roast Ox Crisps",K_LINE29),
    ("E06","Salt & Vinegar",K_LINE30),
    ("E07","Chilli & Peppers",K_LINE31),
    ("E08","Cheese & Onion",K_LINE32),
    ("E09","Dry Ginger",K_LINE33),
    ("E10","Fentimans Ginger",K_LINE34),
    ("E11","Schneider Weisse",K_LINE35),
    ("E12","Schneider Aventinus",K_LINE36),
    ("E13","Liefmans Frambozen",K_LINE37),
    ("E14","Liefmans Kriek",K_LINE38),
    ("E15","Unlabelled",K_LINE39),
    ("D03","Optic 1",K_LINE40),
    ("D04","Optic 2",K_LINE41),
    ("D05","Optic 3",K_LINE42),
    ("D06","Optic 4",K_LINE43),
    ("D07","Optic 5",K_LINE44),
    ("D08","Optic 6",K_LINE45),
    ("D09","Optic 7",K_LINE46),
    ("D10","Optic 8",K_LINE47),
    ("D11","Optic 9",K_LINE48),
    ("D12","Optic 10",K_LINE49),
    ("D13","Optic 11",K_LINE50),
    ("D14","Optic 12",K_LINE51),
    ("D15","Brandy",K_LINE52),
    ("C03","Other Spirit",K_LINE53),
    ("C04","Bushmills Whisky",K_LINE54),
    ("C05","Martini",K_LINE55),
    ("C06","Gordon's Gin",K_LINE56),
    ("C07","Malibu",K_LINE57),
    ("C08","Captain Morgan",K_LINE58),
    ("C09","Jack Daniel's",K_LINE59),
    ("C10","Southern Comfort",K_LINE60),
    ("C11","Archers Schnapps",K_LINE61),
    ("C12","Bells Whisky",K_LINE62),
    ("C13","Bacardi Rum",K_LINE63),
    ("C14","Smirnoff Vodka",K_LINE64),
    # Pints/halves
    ("B03","Half 1",K_LINE65),
    ("B04","Half 2",K_LINE66),
    ("B05","Half 3",K_LINE67),
    ("B06","Half 4",K_LINE68),
    ("B07","Half 5",K_LINE69),
    ("B08","Half 6",K_LINE70),
    ("B09","Half 7",K_LINE71),
    ("B10","Half 8",K_LINE72),
    ("B11","Half Cider",K_LINE73),
    ("B12","Half St Press",K_LINE74),
    ("B13","Half Murphys",K_LINE75),
    ("B14","Half XXXX",K_LINE76),
    ("B15","Half Budvar",K_LINE77),
    ("B16","Half Cellar A",K_LINE78),
    ("B17","Half Cellar B",K_LINE79),
    ("A03","Pint 1",K_LINE80),
    ("A04","Pint 2",K_LINE81),
    ("A05","Pint 3",K_LINE82),
    ("A06","Pint 4",K_LINE83),
    ("A07","Pint 5",K_LINE84),
    ("A08","Pint 6",K_LINE85),
    ("A09","Pint 7",K_LINE86),
    ("A10","Pint 8",K_LINE87),
    ("A11","Pint Cider",K_LINE88),
    ("A12","Pint St Press",K_LINE89),
    ("A13","Pint Murphys",K_LINE90),
    ("A14","Pint XXXX",K_LINE91),
    ("A15","Pint Budvar",K_LINE92),
    ("A16","Pint Cellar A",K_LINE93),
    ("A17","Pint Cellar B",K_LINE94),
    ])
tillconfig.kbtype=1

if autorun or training:
    pdriver=Epson_TM_U220("/dev/lp0",57)
else:
    pdriver=nullprinter()

tillconfig.has_media_slot=True

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

if training:
    pages=[(register.page,keyboard.K_ALICE,("Training A",)),
           (register.page,keyboard.K_BOB,("Training B",)),
           (register.page,keyboard.K_CHARLIE,("Training C",)),
           (register.page,keyboard.K_DORIS,("Training D",))]
else:
    pages=[(register.page,keyboard.K_ALICE,("Alice",)),
           (register.page,keyboard.K_BOB,("Bob",)),
           (register.page,keyboard.K_CHARLIE,("Charlie",)),
           (register.page,keyboard.K_DORIS,("Doris",))]


#f=file("oakdaleglobal.py")
f=urllib.urlopen("http://www.sinister.greenend.org.uk/oakdaleglobal.py")
g=f.read()
f.close()

exec(g)

till.run(dbname,kbdrv,pdriver,pdriver.kickout,pages)
