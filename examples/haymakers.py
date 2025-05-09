# -*- coding: utf-8 -*-

# When this module is loaded, 'configname' is set to the configuration
# name requested on the command line.  The module should define
# 'configurations' to be a dict indexed by configuration names.

import quicktill.extras
from quicktill import keyboard
import quicktill.pdrivers
import quicktill.ui
import quicktill.stockterminal
import quicktill.register
import quicktill.stocktype
import quicktill.usestock
import quicktill.cash
import quicktill.card
import quicktill.squareterminal
import quicktill.modifiers
import quicktill.localutils
import quicktill.secretstore
import quicktill.jsonfoodorder
import quicktill.xero
from decimal import Decimal, ROUND_UP
from collections import defaultdict


# Secret stores

# NB you can add your own Square sandbox API key to this secret store
# with the following command:
# runtill passwd square-sandbox api-key
quicktill.secretstore.Secrets(
    'square-sandbox', b'5Fg5x4WX-BWxjIFc3SEI_wCrRVCAL-Fx0fjuMnLLnv0=')


class ThreeForTwo(quicktill.modifiers.SimpleModifier):
    """Three for the price of two
    """
    def mod_stockline(self, stockline, sale):
        if not sale.price:
            raise quicktill.modifiers.Incompatible("No price is set")
        sale.price = sale.price * Decimal(2)
        sale.qty = sale.qty * Decimal(3)
        sale.description = sale.description + " (3 for the price of 2)"


class TwoForOnePointFive(quicktill.modifiers.SimpleModifier):
    """Two for the price of one-and-a-half
    """
    def mod_stockline(self, stockline, sale):
        if not sale.price:
            raise quicktill.modifiers.Incompatible("No price is set")
        sale.price = sale.price * Decimal("1.5")
        sale.qty = sale.qty * Decimal(2)
        sale.description = sale.description + " (2 for the price of 1.5)"


class Half(quicktill.modifiers.SimpleModifier):
    """Half pint modifier.

    When used with a stock line, checks that the item is sold in pints
    and then sets the serving size to 0.5 and halves the price.

    When used with a price lookup, checks that the department is 7
    (soft drinks) and halves the price.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit.name == 'pint' \
           or (sale.stocktype.unit.name == 'ml'
               and sale.stocktype.unit.base_units_per_sale_unit == 568):
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
        if sale.stocktype.unit.name != 'ml' \
           or sale.stocktype.unit.base_units_per_sale_unit != 568:
            raise quicktill.modifiers.Incompatible(
                f"The {self.name} modifier can only be used with soft drinks.")
        if sale.price:
            sale.price = (sale.price / 4)\
                .quantize(Decimal("0.1"), rounding=ROUND_UP)\
                .quantize(Decimal("0.10"))
        sale.qty = Decimal("100.0")
        sale.description = f"{sale.stocktype} mixer"

    def mod_plu(self, plu, sale):
        if plu.dept_id != 7:
            raise quicktill.modifiers.Incompatible(
                f"The {self.name} modifier can only be used with stock "
                f"that is sold in pints.")
        if sale.price:
            sale.price = (sale.price / 4)\
                .quantize(Decimal("0.1"), rounding=ROUND_UP)\
                .quantize(Decimal("0.10"))
        sale.description = f"{sale.description} mixer"


class Case12(quicktill.modifiers.SimpleModifier):
    """Case of 12 modifier.

    When used with a stockline, checks that the stock is sold in
    bottles, sets the quantity to 12 and the sale price to 10 times
    the price of a single bottle.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit.name != 'bottle':
            raise quicktill.modifiers.Incompatible(
                f"The {self.name} modifier can only be used with bottles.")
        if sale.price:
            sale.price = sale.price * Decimal("10")
        sale.qty = Decimal("12.0")
        sale.description = f"{sale.stocktype} case of 12 bottles"


class Double(quicktill.modifiers.SimpleModifier):
    """Double spirits modifier.

    When used with a stock line, checks that the item is sold in 25ml
    or 50ml measures and then sets the serving size to 2, doubles the
    price, and subtracts 50p.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.unit.name not in ('25ml', '50ml'):
            raise quicktill.modifiers.Incompatible(
                f"The {self.name} modifier can only be used with spirits.")
        # There may not be a price at this point
        if sale.price:
            sale.price = sale.price * Decimal(2) - Decimal("0.50")
        sale.qty = sale.qty * Decimal(2)
        sale.description = f"{sale.stocktype} double "\
            f"{sale.stocktype.unit.name}"


class Staff(quicktill.modifiers.SimpleModifier):
    """Staff price modifier.

    Used to set the staff price on coffee capsules.
    """
    def mod_stockline(self, stockline, sale):
        if sale.stocktype.manufacturer != "Nespresso":
            raise quicktill.modifiers.Incompatible(
                f"The {self.name} modifier can only be used with "
                f"coffee capsules.")
        # There may not be a price at this point
        sale.price = Decimal("0.50")
        sale.description = f"{sale.stocktype} {sale.stocktype.unit.name} "\
            f"staff price"


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
           or (stockline.stocktype.unit.name != 'ml') \
           or (stockline.stocktype.unit.base_units_per_sale_unit != 750) \
           or (stockline.stocktype.dept_id != 9):
            raise quicktill.modifiers.Incompatible(
                "This modifier can only be used with wine.")
        sale.qty = self.size
        sale.description = stockline.stocktype.format() + " " + self.text
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
            raise quicktill.modifiers.Incompatible(
                f"The {plu.description} price lookup does not "
                f"have {self.field} set.")
        sale.price = price
        sale.description = plu.description + " " + self.text


Wine("Small", Decimal("125.0"), "125ml glass", "altprice1", Decimal("0.70"))
Wine("Medium", Decimal("175.0"), "175ml glass", "altprice2", Decimal("0.50"))
Wine("Large", Decimal("250.0"), "250ml glass", "altprice3", Decimal("0.10"))
Wine("Wine Bottle", Decimal("750.0"), "75cl bottle", "price", Decimal("0.00"))


def gp(stocktype, stockunit, cost, gp):
    # Calculate a sale price given a cost price and GP
    # GP is an int or float; 100 is 100%
    exvat = (cost / (Decimal(1) - Decimal(gp / 100.0))) \
        * stocktype.unit.base_units_per_sale_unit / stockunit.size
    return stocktype.department.vat.current.exc_to_inc(exvat)\
        .quantize(Decimal("0.1"), rounding=ROUND_UP)\
        .quantize(Decimal("0.01"))


def markup(stocktype, stockunit, cost, markup):
    return stocktype.department\
                    .vat.current.exc_to_inc(
                        cost * markup * stocktype.unit.base_units_per_sale_unit
                        / stockunit.size)\
                                .quantize(Decimal("0.1"), rounding=ROUND_UP)\
                                .quantize(Decimal("0.01"))


# We are passed a StockType (from which we can get manufacturer, name,
# department, abv and so on); StockUnit (size of container, eg. 72
# pints) and the ex-VAT cost of that unit
class PriceGuess(quicktill.stocktype.PriceGuessHook):
    gp_table = {
        1: 69,  # Real ale
        2: 69,  # Keg
        3: 69,  # Real cider
        4: 69,  # Spirits
        5: 60,  # Snacks
        6: 69,  # Bottles
        7: 70,  # Softs
        9: 60,  # Wine
    }
    min_table = {
        4: Decimal("2.90"),
    }

    @staticmethod
    def guess_price(stocktype, stockunit, cost):
        if stocktype.dept_id in PriceGuess.gp_table:
            return max(
                gp(stocktype, stockunit, cost,
                   PriceGuess.gp_table[stocktype.dept_id]),
                PriceGuess.min_table.get(stocktype.dept_id, Decimal("0.00")))


quicktill.register.PercentageDiscount("Staff food", 20, [10])
quicktill.register.PercentageDiscount("Staff 10% food", 10, [10])
quicktill.register.PercentageDiscount("Free", 100, permission_required=(
    "convert-to-free-drinks", "Convert a transaction to free drinks"))


def appsmenu():
    menu = [
        ("1", "Refusals log", quicktill.extras.refusals, ()),
    ]
    quicktill.ui.keymenu(menu, title="Apps")


# These keys are used by the register and stock terminal pages if they
# haven't already found a use for a keypress
register_hotkeys = quicktill.localutils.register_hotkeys(appsmenu=appsmenu)

global_hotkeys = quicktill.localutils.global_hotkeys(register_hotkeys)

quicktill.jsonfoodorder.FoodOrderPlugin(
    menuurl='https://www.individualpubs.co.uk/haymakers/menu-filtered.json',
    printers=[quicktill.pdrivers.nullprinter()],
    order_key=keyboard.K_FOODORDER, message_key=keyboard.K_FOODMESSAGE,
    message_department=10, allowable_departments=[10])

noprinter = {
    'printer': quicktill.pdrivers.nullprinter(),
}
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
xpdfprinter = {
    'printer': quicktill.pdrivers.commandprinter(
        "evince %s", driver=quicktill.pdrivers.pdf_driver()),
}

# across, down, width, height, horizgap, vertgap, pagesize
staples_2by4 = [2, 4, "99.1mm", "67.7mm", "3mm", "0mm", quicktill.pdrivers.A4]
staples_3by6 = [3, 6, "63.5mm", "46.6mm", "2.8mm", "0mm",
                quicktill.pdrivers.A4]
label11356 = (252, 118)
label99015 = (198, 154)
labelprinter = {
    'labelprinters': [
        quicktill.pdrivers.cupsprinter(
            "LabelWriter-450",
            host="tiki",
            driver=quicktill.pdrivers.pdf_page(pagesize=label99015),
            description="DYMO label printer"),
        quicktill.pdrivers.commandprinter(
            "evince %s",
            driver=quicktill.pdrivers.pdf_labelpage(*staples_3by6)),
    ],
}

std = {
    'database': 'dbname=haymakers',
}

try:
    from contextlib import nullcontext
except ImportError:
    class nullcontext:
        def __init__(self, dummy_resource=None):
            self.dummy_resource = dummy_resource

        def __enter__(self):
            return self.dummy_resource

        def __exit__(self, *args):
            pass


# After this configuration file is read, the code in quicktill/till.py
# simply looks for configurations[configname]

configurations = defaultdict(lambda: dict(std))

with nullcontext(configurations["default"]) as c:
    c.update({
        'description': "Stock-control terminal, no user",
        'firstpage': lambda: quicktill.stockterminal.page(
            register_hotkeys, ["Bar"]),
    })
    c.update(xpdfprinter)
    c.update(labelprinter)

with nullcontext(configurations["mainbar"]) as c:
    c.update({
        'description': "Haymakers main bar",
        'hotkeys': global_hotkeys,
        'keyboard': quicktill.localutils.stdkeyboard_16by8(
            cash_payment_method="CASH", card_payment_method="SQDEV",
            overrides={(0, 5): quicktill.keyboard.Key(
                quicktill.keyboard.K_PASS_LOGIN, css_class="management"),
                       }
        ),
    })
    c.update(quicktill.localutils.activate_register_with_usertoken(
        register_hotkeys))
    c.update(localprinter)
    c.update(labelprinter)

configurations['secondbar'] = configurations['mainbar']

with nullcontext(configurations["stockterminal"]) as c:
    c.update({
        'description': "Stock-control terminal, card reader",
    })
    c.update(quicktill.localutils.activate_stockterminal_with_usertoken(
        register_hotkeys))
    c.update(noprinter)
    c.update(labelprinter)

with nullcontext(configurations["festival"]) as c:
    c.update({
        'description': "Haymakers festival bar",
        'hotkeys': global_hotkeys,
        'keyboard': quicktill.localutils.keyboard(
            13, 6, line_base=301, maxwidth=16,
            overrides={
                (4, 11): keyboard.Key(keyboard.K_FOODORDER,
                                      css_class="kitchen"),
                (5, 11): keyboard.Key(keyboard.K_FOODMESSAGE,
                                      css_class="kitchen"),
            }),
        'keyboard_right': quicktill.localutils.keyboard_rhpanel(
            "CASH", "SQDEV"),
    })
    c.update(quicktill.localutils.activate_register_with_usertoken(
        register_hotkeys))
    c.update(localprinter)
    c.update(labelprinter)
