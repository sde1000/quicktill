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
from quicktill.cash import CashPayment
from quicktill.card import CardPayment
from decimal import Decimal,ROUND_UP
import math
import os
import socket,struct

import logging
log=logging.getLogger('config')

# Keys that we refer to in this config file
K_ALICE=keycode('K_ALICE','Alice')
K_BOB=keycode('K_BOB','Bob')
K_CHARLIE=keycode('K_CHARLIE','Charlie')
K_DORIS=keycode('K_DORIS','Doris')

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
    price=item.stocktype.saleprice*qty
    if item.stocktype.dept_id==4 and qty==2.0: price=price-Decimal("0.50")
    if item.stocktype.dept_id==1 and qty==4.0: price=price-Decimal("1.00")
    return price

# Suggested sale price algorithm

# We are passed a StockType (from which we can get manufacturer, name,
# department, abv and so on); StockUnit (size of container, eg. 72
# pints) and the ex-VAT cost of that unit
def haymakers_priceguess(stocktype,stockunit,cost):
    if stocktype.dept_id==1:
        return guessbeer(stocktype,stockunit,cost)
    if stocktype.dept_id==2:
        return Decimal("3.10") # It's Moravka.  It's all we do.
    if stocktype.dept_id==3:
        return markup(stocktype,stockunit,cost,Decimal("2.6"))
    if stocktype.dept_id==4:
        return max(Decimal("2.50"),
                   markup(stocktype,stockunit,cost,Decimal("2.5")))
    if stocktype.dept_id==5:
        return markup(stocktype,stockunit,cost,Decimal("2.0"))
    if stocktype.dept_id==6:
        return markup(stocktype,stockunit,cost,Decimal("2.5"))
    return None

# Unit is a pint
def guessbeer(stocktype,stockunit,cost):
    cost_per_pint=cost/stockunit.size
    abv=stocktype.abv
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
    r=Decimal(r)
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((Decimal(abv)*Decimal(10.0))+Decimal(18.0))/Decimal(72.0)
    if cost_per_pint>idealcost:
        r=r+stocktype.department.vat.current.exc_to_inc(cost_per_pint-idealcost)
    r=r.quantize(Decimal("0.1"),rounding=ROUND_UP) # Round to 10p
    return r

def markup(stocktype,stockunit,cost,markup):
    return stocktype.department.vat.current.exc_to_inc(
        cost*markup/stockunit.size).\
        quantize(Decimal("0.1"),rounding=ROUND_UP)

# Payment methods.  Here we create instances of payment methods that
# we accept.
cash=CashPayment('CASH','Cash',change_description="Change",drawers=2)
card=CardPayment('CARD','Card',machines=2,cashback_method=cash,
                 max_cashback=Decimal("50.00"))
bitcoin=btcmerch.BitcoinPayment(
    'BTC','Bitcoin',site='haymakers',username='haymakers',
    base_url='http://www.individualpubs.co.uk/merchantservice/',
    password='not-a-valid-password')
all_payment_methods=[cash,card,bitcoin] # Used for session totals entry
payment_methods=all_payment_methods # Used in register

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

std={
    'pubname':"The Haymakers",
    'pubnumber':"01223 311077",
    'pubaddr':("54 High Street, Chesterton","Cambridge CB4 1NG"),
    'currency':u"£",
    'all_payment_methods':all_payment_methods,
    'payment_methods':payment_methods,
    'cashback_limit':50.0,
    'cashback_first':True,
    'pricepolicy':haymakers_pricepolicy,
    'priceguess':haymakers_priceguess,
    'deptkeycheck':haymakers_deptkeycheck,
    'database':'dbname=haymakers',
    'allow_tabs':True,
    'nosale':True,
    'checkdigit_print':True,
    'checkdigit_on_usestock':True,
    'usestock_hook':usestock_hook,
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

# Should we let line keys be named with things other than integers
# (although allow integers for backwards compatibility)?  Strings
# would do, they could be nice and descriptive although may not
# contain characters that are invalid in Python identifiers.

kb1={
    # (location, legend, keycode)
    'kbdriver':kbdrivers.prehkeyboard(
        [
            # control keys
            ("H01",K_ALICE),
            ("G01",K_BOB),
            ("F01",K_CHARLIE),
            ("E01",K_DORIS),
            ("H02",K_MANAGETILL),
            ("G02",K_MANAGESTOCK),
            ("F02",K_USESTOCK),
            ("E02",K_WASTE),
            ("D01",K_RECALLTRANS),
            ("D02",K_MANAGETRANS),
            ("C01",K_PRICECHECK),
            ("C02",K_PRINT),
            ("B01",K_CANCEL),
            ("B02",K_APPS),
            ("A01",K_CLEAR),
            ("D13",K_FOODORDER),
            ("D14",K_CANCELFOOD),
            # Cursor keys, numeric keypad, cash/card keys, Quantity keys
            ("C11",K_LEFT),
            ("D12",K_UP),
            ("C12",K_DOWN),
            ("C13",K_RIGHT),
            ("E14",K_POINT),
            ("E15",K_ZERO),
            ("E16",K_ZEROZERO),
            ("F14",K_ONE),
            ("F15",K_TWO),
            ("F16",K_THREE),
            ("G14",K_FOUR),
            ("G15",K_FIVE),
            ("G16",K_SIX),
            ("H14",K_SEVEN),
            ("H15",K_EIGHT),
            ("H16",K_NINE),
            ("B15",K_CASH),
            ("C15",paymentkey('K_CARD','Card',card)),
            ("D15",K_LOCK),
            ("C14",notekey('K_TWENTY','£20',cash,Decimal("20.00"))),
            ("B14",notekey('K_TENNER','£10',cash,Decimal("10.00"))),
            ("A14",notekey('K_FIVER','£5',cash,Decimal("5.00"))),
            ("E13",K_QUANTITY),
            ("E12",modkey('K_DOUBLE','Double',Decimal(2),[4])),
            ("A02",modkey('K_4JUG','4pt jug',Decimal(4),[1,2,3])),
            # Departments
            ("H12",deptkey(8)),
            ("H13",deptkey(11)),
            ("G12",K_DRINKIN), # Not a department!
            ("G13",deptkey(9)),
            ("F12",deptkey(7)),
            ("F13",deptkey(10)),
            # All line keys
            ("H03",linekey(1)),
            ("H04",linekey(2)),
            ("H05",linekey(3)),
            ("H06",linekey(4)),
            ("H07",linekey(5)),
            ("H08",linekey(6)),
            ("H09",linekey(7)),
            ("H10",linekey(8)),
            ("H11",linekey(9)),
            ("G03",linekey(10)),
            ("G04",linekey(11)),
            ("G05",linekey(12)),
            ("G06",linekey(13)),
            ("G07",linekey(14)),
            ("G08",linekey(15)),
            ("G09",linekey(16)),
            ("G10",linekey(17)),
            ("G11",linekey(18)),
            ("F03",linekey(19)),
            ("F04",linekey(20)),
            ("F05",linekey(21)),
            ("F06",linekey(22)),
            ("F07",linekey(23)),
            ("F08",linekey(24)),
            ("F09",linekey(25)),
            ("F10",linekey(26)),
            ("F11",linekey(27)),
            ("E03",linekey(28)),
            ("E04",linekey(29)),
            ("E05",linekey(30)),
            ("E06",linekey(31)),
            ("E07",linekey(32)),
            ("E08",linekey(33)),
            ("E09",linekey(34)),
            ("E10",linekey(35)),
            ("E11",linekey(36)),
            ("D03",linekey(37)),
            ("D04",linekey(38)),
            ("D05",linekey(39)),
            ("D06",linekey(40)),
            ("D07",linekey(41)),
            ("D08",linekey(42)),
            ("D09",linekey(43)),
            ("D10",linekey(44)),
            ("D11",linekey(45)),
            ("C03",linekey(46)),
            ("C04",linekey(47)),
            ("C05",linekey(48)),
            ("C06",linekey(49)),
            ("C07",linekey(50)),
            ("C08",linekey(51)),
            ("C09",linekey(52)),
            ("C10",linekey(53)),
            ("B03",linekey(55)),
            ("B04",linekey(56)),
            ("B05",linekey(57)),
            ("B06",linekey(58)),
            ("B07",linekey(59)),
            ("B08",linekey(60)),
            ("B09",linekey(61)),
            ("B10",linekey(62)),
            ("B11",linekey(63)),
            ("B12",linekey(64)),
            ("B13",linekey(65)),
            ("A03",linekey(67)),
            ("A04",linekey(68)),
            ("A05",linekey(69)),
            ("A06",linekey(70)),
            ("A07",linekey(71)),
            ("A08",linekey(72)),
            ("A09",linekey(73)),
            ("A10",linekey(74)),
            ("A11",linekey(75)),
            ("A12",linekey(76)),
            ("A13",linekey(77)),
            ],
        magstripe={
            1: ("M1H","M1T"),
            2: ("M2H","M2T"),
            3: ("M3H","M3T"),
            }),
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
#         'menuurl':'http://localhost:8080/foodmenu.py',
         'menuurl':"file:testmenu.py",
         'kitchenprinter':nullprinter(),
         'firstpage': lambda: foodcheck.page([]),
         }
config3.update(std)
config3.update(xpdfprinter)

# Things to define:
#  description - summary of the configuration
#  kbdriver - keyboard driver
#  printer - (driver,args)
#  labelprinter - (driver,args)
#  pages - available pages
#  pubname
#  pubnumber
#  pubaddr
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
