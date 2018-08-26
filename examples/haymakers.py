# -*- coding: utf-8 -*-

import quicktill.extras
import quicktill.foodcheck
from quicktill.keyboard import *
import quicktill.pdrivers
import quicktill.register
import quicktill.ui
import quicktill.stockterminal
import quicktill.user
import quicktill.managetill
import quicktill.managestock
import quicktill.stocktype
import quicktill.pricecheck
import quicktill.usestock
import quicktill.recordwaste
import quicktill.lockscreen
import quicktill.stock
import quicktill.cash
import quicktill.card
import quicktill.bitcoin
import quicktill.modifiers
import quicktill.timesheets
import quicktill.xero
import quicktill.localutils
from decimal import Decimal, ROUND_UP
import datetime
import logging
log = logging.getLogger('config')

quicktill.user.group(
    'basic-user', 'Basic user [group]',
    set.union(quicktill.user.default_groups.basic_user,
              set(["merge-trans", "record-waste"])))

quicktill.user.group(
    'skilled-user', 'Skilled user [group]',
    quicktill.user.default_groups.skilled_user)

quicktill.user.group(
    'manager','Pub manager [group]',
    quicktill.user.default_groups.manager)

class Half(quicktill.modifiers.SimpleModifier):
    """Half pint modifier.

    When used with a stock line, checks that the item is sold in pints
    and then sets the serving size to 0.5 and halves the price.

    When used with a price lookup, checks that the department is 7
    (soft drinks) and halves the price.
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

    def mod_plu(self, plu, sale):
        if plu.dept_id != 7:
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with stock that is "
                "sold in pints.".format(self.name))
        if sale.price:
            sale.price = sale.price / 2
        sale.description = "{} half pint".format(sale.description)

class Mixer(quicktill.modifiers.SimpleModifier):
    """Mixers modifier.

    When used with a stockline, checks that the stock is sold in ml
    and priced in pints (568ml), sets the quantity to 100ml and the
    sale price to £0.70.

    When used with a price lookup, checks that the department is 7
    (soft drinks) and quarters the price.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit_id != 'ml' \
           or sale.stocktype.saleprice_units != 568:
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with soft drinks."\
                .format(self.name))
        if sale.price:
            sale.price = sale.price / 4
        sale.qty = Decimal("100.0")
        sale.description = "{} mixer".format(sale.stocktype.format())

    def mod_plu(self, plu, sale):
        if plu.dept_id != 7:
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with stock that is "
                "sold in pints.".format(self.name))
        if sale.price:
            sale.price = sale.price / 4
        sale.description = "{} mixer".format(sale.description)

class Double(quicktill.modifiers.SimpleModifier):
    """Double spirits modifier.

    When used with a stock line, checks that the item is sold in 25ml
    or 50ml measures and then sets the serving size to 2, doubles the
    price, and subtracts 50p.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit_id not in ('25ml', '50ml'):
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with spirits."\
                .format(self.name))
        # There may not be a price at this point
        if sale.price:
            sale.price = sale.price * Decimal(2) - Decimal("0.50")
        sale.qty = sale.qty * Decimal(2)
        sale.description = "{} double {}".format(
            sale.stocktype.format(), sale.stocktype.unit.name)

class Staff(quicktill.modifiers.SimpleModifier):
    """Staff price modifier.

    Used to set the staff price on coffee capsules.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.manufacturer != "Nespresso":
            raise quicktill.modifiers.Incompatible(
                "The {} modifier can only be used with coffee capsules."\
                .format(self.name))
        # There may not be a price at this point
        sale.price = Decimal("0.50")
        sale.description = "{} {} staff price".format(
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
        super(Wine, self).__init__(name)
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

Wine("Small", Decimal("125.0"), "125ml glass", "altprice1", Decimal("0.40"))
Wine("Medium", Decimal("175.0"), "175ml glass", "altprice2", Decimal("0.30"))
Wine("Large", Decimal("250.0"), "250ml glass", "altprice3", Decimal("0.10"))
Wine("Wine Bottle", Decimal("750.0"), "75cl bottle", "price", Decimal("0.00"))

# We are passed a StockType (from which we can get manufacturer, name,
# department, abv and so on); StockUnit (size of container, eg. 72
# pints) and the ex-VAT cost of that unit
class PriceGuess(quicktill.stocktype.PriceGuessHook):
    @staticmethod
    def guess_price(stocktype, stockunit, cost):
        if stocktype.dept_id == 1:
            return markup(stocktype, stockunit, cost, Decimal("3.0"))
        if stocktype.dept_id == 3:
            return markup(stocktype, stockunit, cost, Decimal("2.6"))
        if stocktype.dept_id == 4:
            return max(
                Decimal("2.50"),
                markup(stocktype, stockunit, cost, Decimal("2.5")))
        if stocktype.dept_id == 5:
            return markup(stocktype, stockunit, cost, Decimal("2.0"))
        if stocktype.dept_id == 6:
            return markup(stocktype, stockunit, cost, Decimal("2.5"))

def markup(stocktype, stockunit, cost, markup):
    return stocktype.department.vat.current.exc_to_inc(
        cost * markup / stockunit.size).\
        quantize(Decimal("0.1"), rounding=ROUND_UP)

# Payment methods.
cash = quicktill.cash.CashPayment(
    'CASH', 'Cash', change_description="Change", drawers=2,
    countup=[], account_code="054")
def card_expected_payment_date(sessiondate):
    return quicktill.localutils.delta_england_banking_days(sessiondate, 3)
card = quicktill.card.CardPayment(
    'CARD', 'Card', machines=2, cashback_method=cash,
    max_cashback=Decimal("50.00"), kickout=True,
    rollover_guard_time=datetime.time(4, 0, 0),
    account_code="011", account_date_policy=card_expected_payment_date,
    ask_for_machine_id=False)
bitcoin = quicktill.bitcoin.BitcoinPayment(
    'BTC', 'Bitcoin', site='haymakers', username='haymakers',
    base_url='http://btcmerch.i.individualpubs.co.uk/merchantservice/',
    password='not-a-real-password', account_code="641")
all_payment_methods = [cash, card] # Used for session totals entry
payment_methods = all_payment_methods # Used in register

tapi = quicktill.extras.twitter_api(
    token='not-a-real-token',
    token_secret='not-a-real-secret',
    consumer_key='not-a-real-key',
    consumer_secret='not-a-real-secret')

class UseStockTwitterHook(quicktill.usestock.UseStockHook):
    def __init__(self, tapi):
        self.tapi = tapi

    def regular_usestock(self, item, line):
        t = None
        if item.stocktype.dept_id == 3:
            # It's a cider. Tweet it.
            t = "Next cider: " + item.stocktype.format()
        elif item.stocktype.dept_id == 1:
            # Real ale.  Tweet if not from Milton, or if particularly strong
            if item.stocktype.manufacturer != "Milton":
                t = "Next guest beer: " + item.stocktype.format()
            if item.stocktype.abv and item.stocktype.abv > Decimal("6.4"):
                t = "Next strong beer: " + item.stocktype.format()
        if t:
            quicktill.extras.twitter_post(
                tapi, default_text=t, fail_silently=True)

tsapi = quicktill.timesheets.Api(
    "haymakers", "not-a-real-password",
    "https://www.individualpubs.co.uk",
    "/schedule/haymakers/api/users/")

try:
    with open("xero-consumer-key") as f:
        xero_consumer_key = f.read().strip()
except:
    xero_consumer_key = None
try:
    with open("xero-private-key.pem") as f:
        xero_private_key = f.read()
except:
    xero_private_key = None

# Contact ID and shortcode have been replaced with details from Xero
# demo company
xapi = quicktill.xero.XeroIntegration(
    consumer_key=xero_consumer_key,
    private_key=xero_private_key,
    sales_contact_id="fe196ff8-8b29-4090-b059-380bff6013c5",
    reference_template="Haymakers takings session {session.id}",
    tracking_category_name="Site",
    tracking_category_value="Haymakers",
    shortcode="!w3V8N",
    discrepancy_account="405",
    tillweb_base_url="https://www.individualpubs.co.uk/tillweb/haymakers/",
    start_date=datetime.date(2016, 12, 1))

def appsmenu():
    menu = [
        ("1", "Twitter", quicktill.extras.twitter_client, (tapi,)),
    ]
    if configname == 'mainbar':
        menu.append(
            ("2", "Timesheets", quicktill.timesheets.popup, (tsapi,)))
    menu.append(
        ("4", "Xero integration", xapi.app_menu, ()))
    quicktill.ui.keymenu(menu, title="Apps")

register_hotkeys = {
    K_PRICECHECK: quicktill.pricecheck.popup,
    K_MANAGETILL: quicktill.managetill.popup,
    K_MANAGESTOCK: quicktill.managestock.popup,
    K_USESTOCK: quicktill.usestock.popup,
    K_WASTE: quicktill.recordwaste.popup,
    K_APPS: appsmenu,
    's': quicktill.managestock.popup,
    'S': quicktill.managestock.popup,
    'a': quicktill.stock.annotate,
    'A': quicktill.stock.annotate,
    'r': quicktill.recordwaste.popup,
    'R': quicktill.recordwaste.popup,
    't': appsmenu,
    'T': appsmenu,
    'm': quicktill.managetill.popup,
    'M': quicktill.managetill.popup,
    'l': quicktill.lockscreen.lockpage,
    'L': quicktill.lockscreen.lockpage,
}

std = {
    'pubname': "The Haymakers",
    'pubnumber': "01223 311077",
    'pubaddr': ("54 High Street, Chesterton", "Cambridge CB4 1NG"),
    'currency': "£",
    'all_payment_methods': all_payment_methods,
    'payment_methods': payment_methods,
    'database': 'dbname=haymakers',
    'checkdigit_print': True,
    'checkdigit_on_usestock': True,
    'discounts': [
        ("5% Shareholder Discount", Decimal(0.05)),
        ("10% Shareholder Discount", Decimal(0.10)),
        ("20% Shareholder Discount", Decimal(0.20)),
        ("Staff Discount", Decimal(0.25)),
        ("Director's Discount", Decimal(0.50)),
    ],
    'discount-note-dept': 8,
}

kitchen = {
    'kitchenprinter': quicktill.pdrivers.nullprinter("kitchen"),
    'menuurl': 'http://till.haymakers.i.individualpubs.co.uk/foodmenu.py',
}

noprinter = {
    'printer': quicktill.pdrivers.nullprinter(),
}
localprinter = {
    'printer': quicktill.pdrivers.linux_lpprinter(
        "/dev/usb/lp?", driver=quicktill.pdrivers.Epson_TM_T20_driver(80)),
}
pdfprinter = {
    'printer': quicktill.pdrivers.cupsprinter(
        "barprinter", driver=quicktill.pdrivers.pdf_driver()),
}
xpdfprinter = {
    'printer': quicktill.pdrivers.commandprinter(
        "evince %s", driver=quicktill.pdrivers.pdf_driver()),
}

# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4 = [2, 4, "99.1mm", "67.7mm", "3mm", "0mm", quicktill.pdrivers.A4]
staples_3by6 = [3, 6, "63.5mm", "46.6mm", "2.8mm", "0mm", quicktill.pdrivers.A4]
label11356 = (252, 118)
label99015 = (198, 154)
labelprinter = {
    'labelprinters': [
        #quicktill.pdrivers.cupsprinter(
        #    "barprinter",
        #    driver=quicktill.pdrivers.pdf_labelpage(*staples_3by6),
        #    options={"MediaType": "Labels"},
        #    description="A4 sheets of 18 labels per sheet"),
        quicktill.pdrivers.cupsprinter(
            "DYMO-LabelWriter-450",
            driver=quicktill.pdrivers.pdf_page(pagesize=label99015),
            description="DYMO label printer"),
    ],
}

kb1 = {
    'keyboard': quicktill.localutils.stdkeyboard_16by8(
        cash_payment_method=cash, card_payment_method=card),
    'firstpage': quicktill.lockscreen.lockpage,
    'usertoken_handler': lambda t: quicktill.register.handle_usertoken(
        t, register_hotkeys, autolock=K_LOCK),
    'usertoken_listen': ('127.0.0.1', 8455),
}

stock_hotkeys = {
    's': quicktill.managestock.popup,
    'S': quicktill.managestock.popup,
    'a': quicktill.stock.annotate,
    'A': quicktill.stock.annotate,
    'r': quicktill.recordwaste.popup,
    'R': quicktill.recordwaste.popup,
    't': appsmenu,
    'T': appsmenu,
    'm': quicktill.managetill.popup,
    'M': quicktill.managetill.popup,
    'l': quicktill.lockscreen.lockpage,
    'L': quicktill.lockscreen.lockpage,
}

global_hotkeys = {
    K_STOCKTERMINAL: lambda: quicktill.stockterminal.page(
        register_hotkeys,["Bar"]),
    K_LOCK: quicktill.lockscreen.lockpage,
}

stockcontrol = {
    'firstpage': lambda: quicktill.stockterminal.page(
        stock_hotkeys, ["Bar"]),
}

stockcontrol_terminal = {
    'firstpage': quicktill.lockscreen.lockpage,
    'usertoken_handler': lambda t: quicktill.stockterminal.handle_usertoken(
        t, register_hotkeys, ["Bar"], max_unattended_updates=5),
    'usertoken_listen': ('127.0.0.1', 8455),
}

config0 = {'description': "Stock-control terminal, no user"}
config0.update(std)
config0.update(stockcontrol)
config0.update(xpdfprinter)
config0.update(labelprinter)

config1 = {'description': "Haymakers main bar",
           'hotkeys': global_hotkeys}
config1.update(std)
config1.update(kb1)
config1.update(localprinter)
config1.update(labelprinter)
config1.update(kitchen)

config2 = {'description':"Stock-control terminal, card reader"}
config2.update(std)
config2.update(stockcontrol_terminal)
config2.update(xpdfprinter)
config2.update(labelprinter)

config3 = {'description':"Test menu file 'testmenu.py' in current directory",
           'menuurl': "file:testmenu.py",
           'kitchenprinter': quicktill.pdrivers.nullprinter("kitchen"),
           'printer': quicktill.pdrivers.nullprinter("bar"),
           'firstpage': lambda: quicktill.foodcheck.page(
               [], user=quicktill.user.built_in_user(
                   "Food check", "Food check", ['kitchen-order'])),
}
config3.update(std)

config4 = {'description': "Haymakers festival bar",
           'hotkeys': global_hotkeys}
config4.update(std)
config4.update(kb1)
config4['keyboard'] = quicktill.localutils.stdkeyboard_20by7(
    151, cash_payment_method=cash, card_payment_method=card)
config4.update(localprinter)
config4.update(labelprinter)
config4.update(kitchen)

configurations = {
    'default': config0,
    'mainbar': config1,
    'stockterminal': config2,
    'testmenu': config3,
    'festival': config4,
}
