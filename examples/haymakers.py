# -*- coding: utf-8 -*-

import quicktill.keyboard as keyboard
import quicktill.extras as extras
import quicktill.foodcheck as foodcheck
from quicktill.keyboard import *
from quicktill.pdrivers import nullprinter,linux_lpprinter,fileprinter,netprinter,commandprinter,Epson_TM_U220_driver,Epson_TM_T20_driver,pdf_driver,pdf_page,pdf_labelpage,A4,cupsprinter
from quicktill import register,ui,kbdrivers,stockterminal,user
from quicktill.managetill import popup as managetill
from quicktill.managestock import popup as managestock
from quicktill.pricecheck import popup as pricecheck
from quicktill.usestock import popup as usestock
from quicktill.recordwaste import popup as recordwaste
from quicktill import lockscreen
from quicktill.stock import annotate
from quicktill import timesheets
from quicktill.cash import CashPayment
from quicktill.card import CardPayment
from quicktill.bitcoin import BitcoinPayment
from quicktill import modifiers
from decimal import Decimal,ROUND_UP
import datetime

import logging
log=logging.getLogger('config')

# Keys that we refer to in this config file
K_MANAGESTOCK=keycode("K_MANAGESTOCK","Manage Stock")
K_PRICECHECK=keycode("K_PRICECHECK","Price Check")
K_STOCKINFO=keycode("K_STOCKINFO","Stock Info")
K_APPS=keycode("K_APPS","Apps")
K_LOCK=keycode("K_LOCK","Lock")

user.group('basic-user','Basic user [group]',
           set.union(user.default_groups.basic_user,
                     set(["merge-trans","record-waste"])))

user.group('skilled-user','Skilled user [group]',
           user.default_groups.skilled_user)

user.group('manager','Pub manager [group]',
           user.default_groups.manager)

def dl(*l):
    return [Decimal(x) for x in l]

class Half(modifiers.SimpleModifier):
    """When used with a stock line, checks that the item is sold in pints
    and then sets the serving size to 0.5 and halves the price.

    When used with a price lookup, checks that the department is 7
    (soft drinks) and halves the price.

    """
    def mod_stockline(self,stockline,transline):
        st=transline.stockref.stockitem.stocktype
        if st.unit_id!='pt':
            raise modifiers.Incompatible(
                "The {} modifier can only be used with stock "
                "that is sold in pints.".format(self.name))
        # There may not be a price at this point
        if transline.amount: transline.amount=transline.amount/2
        transline.stockref.qty=transline.stockref.qty*Decimal("0.5")
        transline.text="{} half pint".format(st.format())
    def mod_plu(self,plu,transline):
        if plu.dept_id!=7:
            raise modifiers.Incompatible(
                "The {} modifier can only be used with stock that is "
                "sold in pints.".format(self.name))
        if transline.amount: transline.amount=transline.amount/2
        transline.text="{} half pint".format(transline.text)

class Mixer(modifiers.SimpleModifier):
    """When used with a price lookup, checks that the department is 7
    (soft drinks) and quarters the price.

    """
    def mod_plu(self,plu,transline):
        if plu.dept_id!=7:
            raise modifiers.Incompatible(
                "The {} modifier can only be used with stock that is "
                "sold in pints.".format(self.name))
        if transline.amount: transline.amount=transline.amount/4
        transline.text="{} mixer".format(transline.text)

class Double(modifiers.SimpleModifier):
    """When used with a stock line, checks that the item is sold in 25ml
    or 50ml measures and then sets the serving size to 2, doubles the
    price, and subtracts 50p.

    """
    def mod_stockline(self,stockline,transline):
        st=transline.stockref.stockitem.stocktype
        if st.unit_id not in ('25ml','50ml'):
            raise modifiers.Incompatible(
                "The {} modifier can only be used with spirits."\
                .format(self.name))
        # There may not be a price at this point
        if transline.amount:
            transline.amount=transline.amount*Decimal(2)-Decimal("0.50")
        transline.stockref.qty=transline.stockref.qty*Decimal(2)
        transline.text="{} double {}".format(st.format(),st.unit.name)

class Staff(modifiers.SimpleModifier):
    """Used to set the staff price on coffee capsules.

    """
    def mod_stockline(self,stockline,transline):
        st=transline.stockref.stockitem.stocktype
        if st.manufacturer!="Nespresso":
            raise modifiers.Incompatible(
                "The {} modifier can only be used with coffee capsules."\
                .format(self.name))
        # There may not be a price at this point
        transline.amount=Decimal("0.50")
        transline.text="{} {} staff price".format(st.format(),st.unit.name)

class Wine(modifiers.BaseModifier):
    """Wine serving modifier.  Can only be used with price lookups.

    Checks that the PLU department is 9 (wine) and then selects the
    appropriate alternative price; small is alt price 1, large is alt
    price 3.

    """
    def __init__(self,name,text,field):
        super(Wine,self).__init__(name)
        self.text=text
        self.field=field
    def mod_plu(self,plu,transline):
        if plu.dept_id!=9:
            raise modifiers.Incompatible(
                "This modifier can only be used with wine.")
        price=getattr(plu,self.field)
        if not price:
            raise modifiers.Incompatible(
                "The {} price lookup does not have {} set."
                .format(plu.description,self.field))
        transline.amount=price
        transline.text=transline.text+" "+self.text
Wine("Small","125ml glass","altprice1")
Wine("Medium","175ml glass","altprice2")
Wine("Large","250ml glass","altprice3")

# Suggested sale price algorithm

# We are passed a StockType (from which we can get manufacturer, name,
# department, abv and so on); StockUnit (size of container, eg. 72
# pints) and the ex-VAT cost of that unit
def haymakers_priceguess(stocktype,stockunit,cost):
    if stocktype.dept_id==1:
        return markup(stocktype,stockunit,cost,Decimal("3.0"))
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

def markup(stocktype,stockunit,cost,markup):
    return stocktype.department.vat.current.exc_to_inc(
        cost*markup/stockunit.size).\
        quantize(Decimal("0.1"),rounding=ROUND_UP)

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

# Payment methods.  Here we create instances of payment methods that
# we accept.
cash=CashPayment('CASH','Cash',change_description="Change",drawers=2,
                 countup=[])
card=CardPayment('CARD','Card',machines=2,cashback_method=cash,
                 max_cashback=Decimal("50.00"),kickout=True,
                 rollover_guard_time=datetime.time(4,0,0))
bitcoin=BitcoinPayment(
    'BTC','Bitcoin',site='test',username='test',
    base_url='http://btcmerch.i.individualpubs.co.uk/merchantservice/',
    password='testpasswd')
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
        t="Next cider: "+item.stocktype.format()
    elif item.stocktype.dept_id==1:
        # Real ale.  Tweet if not from Milton, or if particularly strong
        if item.stocktype.manufacturer!="Milton":
            t="Next guest beer: "+item.stocktype.format()
        if item.stocktype.abv and item.stocktype.abv>Decimal("6.4"):
            t="Next strong beer: "+item.stocktype.format()
    if t: extras.twitter_post(tapi,default_text=t,fail_silently=True)

tsapi=timesheets.Api("haymakers","not-a-valid-password",
                     "https://www.individualpubs.co.uk",
                     "/schedule/haymakers/api/users/")

def qr():
    import quicktill.printer as printer
    with printer.driver as p:
        p.printqrcode(bytes("https://www.individualpubs.co.uk/", "utf-8"))

def appsmenu():
    menu=[
        ("1", "Twitter", extras.twitter_client, (tapi,)),
        ]
    if configname == 'mainbar':
        menu.append(
            ("2", "Timesheets", timesheets.popup, (tsapi,)))
    menu.append(
        ("3", "QR code print", qr, ()))
    ui.keymenu(menu, title="Apps")

register_hotkeys={
    K_PRICECHECK: pricecheck,
    K_MANAGETILL: managetill,
    K_MANAGESTOCK: managestock,
    K_USESTOCK: usestock,
    K_WASTE: recordwaste,
    K_APPS: appsmenu,
    's': managestock,
    'S': managestock,
    'a': annotate,
    'A': annotate,
    'r': recordwaste,
    'R': recordwaste,
    't': appsmenu,
    'T': appsmenu,
    'm': managetill,
    'M': managetill,
    'l': lockscreen.lockpage,
    'L': lockscreen.lockpage,
    }

std={
    'pubname':"The Haymakers",
    'pubnumber':"01223 311077",
    'pubaddr':("54 High Street, Chesterton","Cambridge CB4 1NG"),
    'currency':"£",
    'all_payment_methods':all_payment_methods,
    'payment_methods':payment_methods,
    'priceguess':haymakers_priceguess,
    'database':'dbname=haymakers',
    'allow_tabs':True,
    'checkdigit_print':True,
    'checkdigit_on_usestock':True,
    'usestock_hook':usestock_hook,
}

kitchen={
    'kitchenprinter':nullprinter(), # testing only
    'menuurl':'http://till.haymakers.i.individualpubs.co.uk/foodmenu.py',
    }

noprinter={
    'printer': nullprinter(),
    }
localprinter={
    'printer': linux_lpprinter("/dev/epson-tm-t20",
                               driver=Epson_TM_T20_driver(80)),
#    'printer': fileprinter("/dev/epson-tm-u220",
#                           driver=Epson_TM_U220_driver(57, has_cutter=True)),
    }
pdfprinter={
    'printer': cupsprinter("barprinter",driver=pdf_driver()),
    }
xpdfprinter={
    'printer': commandprinter("evince %s",driver=pdf_driver()),
    }
# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4=[2,4,"99.1mm","67.7mm","3mm","0mm",A4]
staples_3by6=[3,6,"63.5mm","46.6mm","2.8mm","0mm",A4]
label11356=(252,118)
label99015=(198,154)
labelprinter={
    'labelprinters': [
#        cupsprinter("barprinter",
#                    driver=pdf_labelpage(*staples_3by6),
#                    options={"MediaType":"Labels"},
#                    description="A4 sheets of 18 labels per sheet"),
        cupsprinter("LabelWriter-450",
                    driver=pdf_page(pagesize=label11356),
                    description="DYMO label printer"),
        ],
}

kb1={
    'kbdriver':kbdrivers.prehkeyboard(
        [
            # control keys
            ("H01", user.token('builtin:alice')),
            ("G01", user.token('builtin:bob')),
            ("F01", user.token('builtin:charlie')),
            ("E01", K_STOCKINFO),
            ("H02", K_MANAGETILL),
            ("G02", K_MANAGESTOCK),
            ("F02", K_USESTOCK),
            ("E02", K_WASTE),
            ("D01", K_RECALLTRANS),
            ("D02", K_MANAGETRANS),
            ("C01", K_PRICECHECK),
            ("C02", K_PRINT),
            ("B01", K_CANCEL),
            ("B02", K_APPS),
            ("A01", K_CLEAR),
            ("D13", K_FOODORDER),
            ("D14", K_CANCELFOOD),
            # Cursor keys, numeric keypad, cash/card keys, Quantity keys
            ("C11", K_LEFT),
            ("D12", K_UP),
            ("C12", K_DOWN),
            ("C13", K_RIGHT),
            ("E14", "."),
            ("E15", "0"),
            ("E16", "00"),
            ("F14", "1"),
            ("F15", "2"),
            ("F16", "3"),
            ("G14", "4"),
            ("G15", "5"),
            ("G16", "6"),
            ("H14", "7"),
            ("H15", "8"),
            ("H16", "9"),
            ("B15", K_CASH),
            ("C15", paymentkey('K_CARD','Card',card)),
            ("D15", K_LOCK),
            ("C14", notekey('K_TWENTY','£20',cash,Decimal("20.00"))),
            ("B14", notekey('K_TENNER','£10',cash,Decimal("10.00"))),
            ("A14", notekey('K_FIVER','£5',cash,Decimal("5.00"))),
            ("E13", K_QUANTITY),
            ("A02", K_MARK),
            # Departments
            ("G12", K_DRINKIN), # Not a department!
            ("G13", None), # was Wine dept key
            ("F12", None), # was Soft Drinks dept key
            ("F13", None), # was Food dept key
            # All line keys
            ("H03", linekey(1)),
            ("H04", linekey(2)),
            ("H05", linekey(3)),
            ("H06", linekey(4)),
            ("H07", linekey(5)),
            ("H08", linekey(6)),
            ("H09", linekey(7)),
            ("H10", linekey(8)),
            ("H11", linekey(9)),
            ("H12", linekey(79)), # formerly Misc dept key
            ("H13", linekey(80)), # formerly Hot Drinks dept key
            ("G03", linekey(10)),
            ("G04", linekey(11)),
            ("G05", linekey(12)),
            ("G06", linekey(13)),
            ("G07", linekey(14)),
            ("G08", linekey(15)),
            ("G09", linekey(16)),
            ("G10", linekey(17)),
            ("G11", linekey(18)),
            ("F03", linekey(19)),
            ("F04", linekey(20)),
            ("F05", linekey(21)),
            ("F06", linekey(22)),
            ("F07", linekey(23)),
            ("F08", linekey(24)),
            ("F09", linekey(25)),
            ("F10", linekey(26)),
            ("F11", linekey(27)),
            ("E03", linekey(28)),
            ("E04", linekey(29)),
            ("E05", linekey(30)),
            ("E06", linekey(31)),
            ("E07", linekey(32)),
            ("E08", linekey(33)),
            ("E09", linekey(34)),
            ("E10", linekey(35)),
            ("E11", linekey(36)),
            ("E12", linekey(78)), # formerly Double
            ("D03", linekey(37)),
            ("D04", linekey(38)),
            ("D05", linekey(39)),
            ("D06", linekey(40)),
            ("D07", linekey(41)),
            ("D08", linekey(42)),
            ("D09", linekey(43)),
            ("D10", linekey(44)),
            ("D11", linekey(45)),
            ("C03", linekey(46)),
            ("C04", linekey(47)),
            ("C05", linekey(48)),
            ("C06", linekey(49)),
            ("C07", linekey(50)),
            ("C08", linekey(51)),
            ("C09", linekey(52)),
            ("C10", linekey(53)),
            ("B03", linekey(55)),
            ("B04", linekey(56)),
            ("B05", linekey(57)),
            ("B06", linekey(58)),
            ("B07", linekey(59)),
            ("B08", linekey(60)),
            ("B09", linekey(61)),
            ("B10", linekey(62)),
            ("B11", linekey(63)),
            ("B12", linekey(64)),
            ("B13", linekey(65)),
            ("A03", linekey(67)),
            ("A04", linekey(68)),
            ("A05", linekey(69)),
            ("A06", linekey(70)),
            ("A07", linekey(71)),
            ("A08", linekey(72)),
            ("A09", linekey(73)),
            ("A10", linekey(74)),
            ("A11", linekey(75)),
            ("A12", linekey(76)),
            ("A13", linekey(77)),
            # 78 is E12 (formerly Double)
            # 79 is H12 (formerly Misc)
            # 80 is H13 (formerly Hot)
            ],
        magstripe=[
            ("M1H", "M1T"),
            ("M2H", "M2T"),
            ("M3H", "M3T"),
            ]),
    'firstpage': lockscreen.lockpage,
    'usertoken_handler': lambda t:register.handle_usertoken(
        t,register_hotkeys,autolock=K_LOCK),
    'usertoken_listen': ('127.0.0.1',8455),
    'usertoken_listen_v6': ('::1',8455),
    }

stock_hotkeys={
    's': managestock,
    'S': managestock,
    'a': annotate,
    'A': annotate,
    'r': recordwaste,
    'R': recordwaste,
    't': appsmenu,
    'T': appsmenu,
    'm': managetill,
    'M': managetill,
    'l': lockscreen.lockpage,
    'L': lockscreen.lockpage,
    }

global_hotkeys={
    K_STOCKINFO: lambda: stockterminal.page(register_hotkeys,["Bar"]),
    K_LOCK: lockscreen.lockpage,
}

stockcontrol={
    'kbdriver':kbdrivers.curseskeyboard(),
    'firstpage': lambda: stockterminal.page(
        stock_hotkeys,["Bar"],user=user.built_in_user(
            "Stock Terminal","Stock Terminal",['manager'])),
}

stockcontrol_terminal={
    'kbdriver':kbdrivers.curseskeyboard(),
    'firstpage': lockscreen.lockpage,
    'usertoken_handler': lambda t:stockterminal.handle_usertoken(
        t,register_hotkeys,["Bar"],max_unattended_updates=5),
    'usertoken_listen': ('127.0.0.1',8455),
}

config0={'description':"Stock-control terminal, no user"}
config0.update(std)
config0.update(stockcontrol)
config0.update(xpdfprinter)
config0.update(labelprinter)

config1={'description':"Haymakers main bar",
         'hotkeys':global_hotkeys}
config1.update(std)
config1.update(kb1)
config1.update(localprinter)
config1.update(labelprinter)
config1.update(kitchen)

config2={'description':"Stock-control terminal, card reader"}
config2.update(std)
config2.update(stockcontrol_terminal)
config2.update(xpdfprinter)
config2.update(labelprinter)

config3={'description':"Test menu file 'testmenu.py' in current directory",
         'kbdriver':kbdrivers.curseskeyboard(),
         'menuurl':"file:testmenu.py",
         'kitchenprinter':nullprinter("kitchen"),
         'printer':nullprinter("bar"),
         'firstpage': lambda: foodcheck.page([]),
         }
config3.update(std)

configurations={
    'default': config0,
    'mainbar': config1,
    'stockterminal': config2,
    'testmenu': config3,
    }
