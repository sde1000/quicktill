# -*- coding: utf-8 -*-

# When this module is loaded, 'configname' is set to the configuration
# name requested on the command line.  The module should define
# 'configurations' to be a dict indexed by configuration names.

import quicktill.extras
from quicktill.keyboard import *
import quicktill.pdrivers
import quicktill.ui
import quicktill.stockterminal
import quicktill.user
import quicktill.stocktype
import quicktill.usestock
import quicktill.cash
import quicktill.card
import quicktill.modifiers
import quicktill.localutils
from decimal import Decimal, ROUND_UP
import datetime
import logging
log = logging.getLogger('config')

# Define three groups of permissions based on built-in lists.  If you
# want any extra groups, or to modify the built-in lists, do that
# here.
quicktill.user.group('basic-user', 'Basic user [group]',
                     quicktill.user.default_groups.basic_user)

quicktill.user.group('skilled-user','Skilled user [group]',
                     quicktill.user.default_groups.skilled_user)

quicktill.user.group('manager','Pub manager [group]',
                     quicktill.user.default_groups.manager)

# Declare the modifiers available to the till.  This is site-specific
# because modifiers refer to things like departments and stock types
# that are set up in the database.  Once declared, modifiers are added
# to buttons and stock lines entries in the database.

class Case(quicktill.modifiers.SimpleModifier):
    """Case modifier.

    When used with a stock line, checks that the item is Club Mate,
    sets the serving size to 20 and multiplies the price by 20.
    """
    def mod_stockline(self, stockline, sale):
        st = sale.stocktype
        if st.manufacturer != 'Club Mate':
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with "
                "Club Mate.".format(self.name))
        if st.name == "Regular 330ml":
            caseqty = 24
        else:
            caseqty = 20
        # There may not be a price at this point
        if sale.price:
            sale.price = sale.price * caseqty
        sale.qty = sale.qty * caseqty
        sale.description = "{} case of {}".format(st.format(), caseqty)

class Half(quicktill.modifiers.SimpleModifier):
    """Half pint modifier.

    When used with a stock line, checks that the item is sold in pints
    and then halves the serving size and price.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit_id == 'pt' \
           or (sale.stocktype.unit_id == 'ml'
               and sale.stocktype.saleprice_units == 568):
            # There may not be a price at this point
            if sale.price:
                sale.price = sale.price / 2
            sale.qty = sale.qty * Decimal("0.5")
            sale.description = "{} half pint".format(sale.stocktype.format())
            return
        raise quicktill.modifiers.Incompatible(
            "The {} modifier can only be used with stock "
            "that is sold in pints.".format(self.name))

class Mixer(quicktill.modifiers.SimpleModifier):
    """Mixers modifier.

    When used with a stockline, checks that the stock is sold in ml
    and priced in pints (568ml), sets the quantity to 100ml and the
    sale price to £0.70.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit_id != 'ml' \
           or sale.stocktype.saleprice_units != 568:
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with soft drinks."\
                .format(self.name))
        if sale.price:
            sale.price = Decimal("0.70")
        sale.qty = Decimal("100.0")
        sale.description = "{} mixer".format(sale.stocktype.format())

class Double(quicktill.modifiers.SimpleModifier):
    """Double spirits modifier.

    When used with a stock line, checks that the item is sold in 25ml
    or 50ml measures and then doubles the serving size and price.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit_id not in ('25ml', '50ml'):
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with spirits."\
                .format(self.name))
        # There may not be a price at this point
        if sale.price:
            sale.price = sale.price * 2
        sale.qty = sale.qty * 2
        sale.description = "{} double {}".format(
            sale.stocktype.format(), sale.stocktype.unit.name)

class Wine(quicktill.modifiers.BaseModifier):
    """Wine serving modifier.

    When used with stocklines, checks that the stockline is a
    continuous stockline selling stock priced per 750ml in department
    9 (wine).  Adjusts the serving size and price appropriately.

    When used with price lookups, checks that the PLU department is 9
    (wine) and then selects the appropriate alternative price; small
    is alt price 1, large is alt price 3.
    """
    def __init__(self, name, size, text, field, extra):
        super().__init__(name)
        self.size = size
        self.text = text
        self.field = field
        self.extra = extra

    def mod_stockline(self, stockline, sale):
        if stockline.linetype != "continuous" \
           or (stockline.stocktype.unit_id != 'ml') \
           or (stockline.stocktype.saleprice_units != 750) \
           or (stockline.stocktype.dept_id != 9):
            raise quicktill.modifiers.Incompatible(
                "This modifier can only be used with wine.")
        sale.qty = self.size
        sale.description = sale.description + " " + self.text
        if sale.price:
            sale.price = (self.size / Decimal("750.0") * sale.price)\
                .quantize(Decimal("0.1"), rounding=ROUND_UP)\
                .quantize(Decimal("0.10"))
            sale.price += self.extra

    def mod_plu(self, plu, sale):
        if plu.dept_id != 9:
            raise quicktill.modifiers.Incompatible(
                "This modifier can only be used with wine.")
        price = getattr(plu, self.field)
        if not price:
            raise modifiers.Incompatible(
                "The {} price lookup does not have {} set."
                .format(plu.description, self.field))
        sale.price = price
        sale.description = plu.description + " " + self.text

Wine("Small", Decimal("125.0"), "125ml glass", "altprice1", Decimal("0.00"))
Wine("Medium", Decimal("175.0"), "175ml glass", "altprice2", Decimal("0.00"))
Wine("Large", Decimal("250.0"), "250ml glass", "altprice3", Decimal("0.00"))
Wine("Wine Bottle", Decimal("750.0"), "75cl bottle", "price", Decimal("0.00"))

# Suggested sale price algorithm

# We are passed a StockType (from which we can get manufacturer, name,
# department, abv and so on); StockUnit (size of container, eg. 72
# pints) and the ex-VAT cost of that unit
class PriceGuess(quicktill.stocktype.PriceGuessHook):
    @staticmethod
    def guess_price(stocktype, stockunit, cost):
        if stocktype.dept_id == 1:
            return markup(stocktype, stockunit, cost, Decimal("3.0"))
        if stocktype.dept_id == 2:
            return markup(stocktype, stockunit, cost, Decimal("2.3"))
        if stocktype.dept_id == 3:
            return markup(stocktype, stockunit, cost, Decimal("2.6"))
        if stocktype.dept_id == 4:
            return max(Decimal("2.50"),
                       markup(stocktype, stockunit, cost, Decimal("2.5")))
        if stocktype.dept_id == 5:
            return markup(stocktype, stockunit, cost, Decimal("2.0"))
        if stocktype.dept_id == 6:
            return markup(stocktype, stockunit, cost, Decimal("2.0"))
        if stocktype.dept_id == 13:
            return markup(stocktype, stockunit, cost, Decimal("2.3"))

def markup(stocktype, stockunit, cost, markup):
    return stocktype.department.vat.current.exc_to_inc(
        cost * markup / stockunit.size).\
        quantize(Decimal("0.1"), rounding=ROUND_UP)

# Payment methods.
cash = quicktill.cash.CashPayment(
    'CASH', 'Cash', change_description="Change", drawers=3,
    countup=[])
card = quicktill.card.CardPayment(
    'CARD', 'Card', machines=3, cashback_method=cash,
    max_cashback=Decimal("100.00"), kickout=True,
    rollover_guard_time=datetime.time(4, 0, 0),
    ask_for_machine_id=True)
all_payment_methods = [cash, card] # Used for session totals entry
payment_methods = all_payment_methods # Used in register

# Twitter API
tapi = quicktill.extras.twitter_api(
    token='not-a-valid-token',
    token_secret='not-a-valid-token-secret',
    consumer_key='not-a-valid-consumer-key',
    consumer_secret='not-a-valid-consumer-secret')

# When an item is put on sale, tweet about it
class UseStockTwitterHook(quicktill.usestock.UseStockHook):
    def __init__(self, tapi):
        self.tapi = tapi

    def regular_usestock(self, item, line):
        t = None
        if item.stocktype.dept_id == 3:
            # It's a cider. Tweet it.
            t = "We just put a cider on sale: " + item.stocktype.format()
        elif item.stocktype.dept_id == 1:
            t = "We just started a fresh cask of {}".format(
                item.stocktype.format())
        elif item.stocktype.dept_id == 2:
            t = "We've just put a keg of {} on sale.".format(
                item.stocktype.format())
        if t:
            quicktill.extras.twitter_post(
                self.tapi, default_text=t, fail_silently=True)

# This is commented out to disable it, because this example config
# file does not include genuine Twitter credentials and the error
# popups would be annoying

#UseStockTwitterHook(tapi)

# This is a very simple 'sample' app
def qr():
    import quicktill.printer as printer
    with printer.driver as p:
        p.printqrcode(bytes("https://www.individualpubs.co.uk/", "utf-8"))

def appsmenu():
    menu = [
        ("1", "Refusals log", quicktill.extras.refusals, ()),
        #("2", "Twitter", quicktill.extras.twitter_client, (tapi,)),
        ("3", "QR code print", qr, ()),
    ]
    quicktill.ui.keymenu(menu, title="Apps")

std = {
    'pubname': "EMFcamp 2018",
    'pubnumber': "",
    'pubaddr': ("Eastnor Castle Deer Park", "Eastnor HR8 1RQ"),
    'currency': "£",
    'all_payment_methods': all_payment_methods,
    'payment_methods': payment_methods,
    'database': 'dbname=emfcamp',
    'allow_tabs': True,
    'checkdigit_print': True,
    'checkdigit_on_usestock': True,
    'custom_css': """
button:not(:active) {
    transition: 250ms ease-in-out;
}
@define-color pumps deepskyblue;
.pint {
    background-color: @pumps;
    color: black;
}
.linekey:active {
    border-color: white;
}

.half {
    background-color: lighter(@pumps);
    color: black;
}
"""
}

# Print to a locally-attached receipt printer
localprinter = {
    'printer': quicktill.pdrivers.autodetect_printer([
        ("/dev/epson-tm-t20",
         quicktill.pdrivers.Epson_TM_T20_driver(80), True),
        ("/dev/epson-tm-t20ii",
         quicktill.pdrivers.Epson_TM_T20_driver(80), True),
        ("/dev/aures-odp-333",
         quicktill.pdrivers.Aures_ODP_333_driver(), False),
        ("/dev/epson-tm-u220",
         quicktill.pdrivers.Epson_TM_U220_driver(57, has_cutter=True), False),
        ]),
}
# 'Print' into a popup window
windowprinter = {
    'printer': quicktill.pdrivers.commandprinter(
        "evince %s",
        driver=quicktill.pdrivers.pdf_driver()),
}

# Label paper definitions
# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4 = [2, 4, "99.1mm", "67.7mm", "3mm", "0mm", quicktill.pdrivers.A4]
staples_3by6 = [3, 6, "63.5mm", "46.6mm", "2.8mm", "0mm", quicktill.pdrivers.A4]
# width, height
label11356 = (252, 118)
label99015 = (198, 154)
labelprinter = {
    'labelprinters': [
        #quicktill.pdrivers.cupsprinter(
        #    "DYMO-LabelWriter-450",
        #    driver=quicktill.pdrivers.pdf_page(pagesize=label11356),
        #    description="DYMO label printer"),
        quicktill.pdrivers.commandprinter(
            "evince %s",
            driver=quicktill.pdrivers.pdf_page(pagesize=label99015),
            description="PDF viewer"),
    ],
}

# These keys are used by the register and stock terminal pages if they
# haven't already found a use for a keypress
register_hotkeys = quicktill.localutils.register_hotkeys(appsmenu=appsmenu)

global_hotkeys = quicktill.localutils.global_hotkeys(register_hotkeys)

config0 = {
    'description': "Stock-control terminal, default user is manager",
    'firstpage': lambda: quicktill.stockterminal.page(
        register_hotkeys, ["Bar"], user=quicktill.user.built_in_user(
            "Stock Terminal", "Stock Terminal", ['manager'])),
}
config0.update(std)
config0.update(windowprinter)
config0.update(labelprinter)

config1 = {
    'description': "Main bar",
    'hotkeys': global_hotkeys,
    'keyboard': quicktill.localutils.stdkeyboard_16by8(
        line_base=1, cash_payment_method=cash, card_payment_method=card),
}
config1.update(std)
config1.update(quicktill.localutils.activate_register_with_usertoken(
    register_hotkeys))
#config1.update(localprinter) # Used when live
config1.update(windowprinter) # Used for examples
config1.update(labelprinter)

config2 = {
    'description': "Stock-control terminal with card reader",
}
config2.update(std)
config2.update(quicktill.localutils.activate_stockterminal_with_usertoken(
    register_hotkeys))
config2.update(windowprinter)
config2.update(labelprinter)

config3 = {
    'description': "Cybar",
    'hotkeys': global_hotkeys,
    'keyboard': quicktill.localutils.stdkeyboard_16by8(
        line_base=201, cash_payment_method=cash, card_payment_method=card),
}
config3.update(std)
config3.update(quicktill.localutils.activate_register_with_usertoken(
    register_hotkeys))
#config3.update(localprinter) # Used when live
config3.update(windowprinter) # Used for examples
config3.update(labelprinter)

# After this configuration file is read, the code in quicktill/till.py
# simply looks for configurations[configname]

configurations = {
    'default': config0,
    'mainbar': config1,
    'stockterminal': config2,
    'cybar': config3,
}
