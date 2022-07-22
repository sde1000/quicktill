# -*- coding: utf-8 -*-

# This is a minimal example till configuration. You can use it when
# setting up a new instance of the till software.

# When this module is loaded, 'configname' is set to the configuration
# name requested on the command line.  The module should define
# 'configurations' to be a dict indexed by configuration names.

import quicktill.pdrivers
import quicktill.stockterminal
import quicktill.cash
import quicktill.card
import quicktill.localutils
from decimal import Decimal
import datetime
from contextlib import nullcontext
from collections import defaultdict

# Payment methods.
cash = quicktill.cash.CashPayment(
    'CASH', 'Cash', change_description="Change", drawers=3,
    countup=[])
card = quicktill.card.CardPayment(
    'CARD', 'Card', machines=3, cashback_method=cash,
    max_cashback=Decimal("100.00"), kickout=True,
    rollover_guard_time=datetime.time(4, 0, 0),
    ask_for_machine_id=True)
all_payment_methods = [cash, card]  # Used for session totals entry
payment_methods = all_payment_methods  # Used in register

std = {
    'all_payment_methods': all_payment_methods,
    'payment_methods': payment_methods,
    'database': 'dbname=minimal',
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
# width, height
label11356 = (252, 118)
label99015 = (198, 154)
labelprinter = {
    'labelprinters': [
        # quicktill.pdrivers.cupsprinter(
        #     "DYMO-LabelWriter-450",
        #     driver=quicktill.pdrivers.pdf_page(pagesize=label11356),
        #     description="DYMO label printer"),
        quicktill.pdrivers.commandprinter(
            "evince %s",
            driver=quicktill.pdrivers.pdf_page(pagesize=label99015),
            description="PDF viewer"),
    ],
}

# These keys are used by the register and stock terminal pages if they
# haven't already found a use for a keypress
register_hotkeys = quicktill.localutils.register_hotkeys()

global_hotkeys = quicktill.localutils.global_hotkeys(register_hotkeys)

# After this configuration file is read, the code in quicktill/till.py
# simply looks for configurations[configname]
configurations = defaultdict(lambda: dict(std))


def cf(n):
    return nullcontext(configurations[n])


with cf("default") as c:
    c.update({
        'description': "Stock-control terminal, default user is manager",
        'firstpage': lambda: quicktill.stockterminal.page(
            register_hotkeys, ["Bar"]),
    })
    c.update(windowprinter)
    c.update(labelprinter)

with cf("mainbar") as c:
    c.update({
        'description': "Main bar",
        'hotkeys': global_hotkeys,
        'keyboard': quicktill.localutils.keyboard(
            13, 7, line_base=1, maxwidth=16),
        'keyboard_right': quicktill.localutils.keyboard_rhpanel(
            cash, card),
    })
    c.update(quicktill.localutils.activate_register_with_usertoken(
        register_hotkeys))
    # c.update(localprinter)  # Used when live
    c.update(windowprinter)  # Used for examples
    c.update(labelprinter)

with cf("stockterminal") as c:
    c.update({
        'description': "Stock-control terminal with card reader",
    })
    c.update(quicktill.localutils.activate_stockterminal_with_usertoken(
        register_hotkeys))
    c.update(windowprinter)
    c.update(labelprinter)
