# Various region-specific utility functions
# and configuration that is recommended for many common cases
from . import kbdrivers
from . import user
from .keyboard import *
import datetime
from decimal import Decimal
from dateutil.easter import easter, EASTER_WESTERN
from dateutil.relativedelta import relativedelta, MO, FR

def is_england_banking_day(d):
    """Is a day a likely England banking day?

    Returns True if it is, or False if it is not.

    Not completely guaranteed to be correct; the government may insert
    or delete bank holidays at will.  Only covers bank holidays from
    1st December 2016.
    """
    # If it is a Saturday or Sunday, is definitely not a banking day
    if d.isoweekday() in (6, 7):
        return False

    # Bank holidays with fixed dates: New Years Day, Christmas Day,
    # Boxing Day
    if d.month == 1 and d.day == 1:
        return False
    if d.month == 12 and d.day == 25:
        return False
    if d.month == 12 and d.day == 26:
        return False

    # Substitute bank holidays if fixed date bank holidays fall on a
    # Saturday or Sunday
    if d.month == 1 and d.day == 2:
        if datetime.date(d.year, 1, 1).isoweekday() in (6, 7):
            return False
    if d.month == 1 and d.day == 3:
        if datetime.date(d.year, 1, 1).isoweekday() == 6:
            return False
    if d.month == 12 and d.day == 27:
        # Bank holiday if either the 25th or 26th was a Saturday or Sunday
        if datetime.date(d.year, 12, 25).isoweekday() in (6, 7) \
           or datetime.date(d,year, 12, 26).isoweekday() in (6, 7):
            return False
    if d.month == 12 and d.day == 28:
        # Bank holiday if the 25th was a Saturday and the 26th was a Sunday
        if datetime.date(d.year, 12, 25).isoweekday() == 6 \
           and datetime.date(d.year, 12, 26).isoweekday() == 7:
            return False

    # Good Friday and Easter Monday both depend on the date of Easter.
    easter_sunday = easter(d.year, method=EASTER_WESTERN)
    good_friday = easter_sunday - datetime.timedelta(days=2)
    easter_monday = easter_sunday + datetime.timedelta(days=1)
    if d == good_friday or d == easter_monday:
        return False

    # The early May bank holiday is the first Monday of May
    start_of_may = datetime.date(d.year, 5, 1)
    first_monday_of_may = start_of_may + relativedelta(weekday=MO)
    if d == first_monday_of_may:
        return False
    # The Spring bank holiday is the last Monday of May
    last_monday_of_may = start_of_may + relativedelta(day=31, weekday=MO(-1))
    if d == last_monday_of_may:
        return False

    # The Summer bank holiday is the last Monday of August in England,
    # Wales and Northern Ireland (and the first Monday of August in
    # Scotland, although we're not going to calculate that).
    start_of_august = datetime.date(d.year, 8, 1)
    last_monday_of_august = start_of_august \
                            + relativedelta(day=31, weekday=MO(-1))
    if d == last_monday_of_august:
        return False

    # That's it, unless the government introduce any non-standard bank
    # holidays.  If we've got this far, the day is a banking day.
    return True

def delta_england_banking_days(date, n):
    """Return the date plus a number of banking days

    Given any date, return the date of the nth banking day after it.
    """
    if n < 1:
        raise ValueError("It doesn't make sense to ask for the {}th banking "
                         "day after a date!".format(n))
    while n > 0:
        date = date + datetime.timedelta(days=1)
        if is_england_banking_day(date):
            n = n - 1
    return date

def stdkeyboard_16by8(line_base=1, cash_payment_method=None,
                      card_payment_method=None, overrides={}):
    """Standard 16x8 keyboard layout

    A standard keyboard layout for a 16 by 8 key keyboard that
    produces inputs of the form [A01] to [H16].
    """
    kb = {}
    # First assign a linekey() to every key position, which we will
    # override later for special keys.
    linenumber = iter(range(line_base, line_base + 128))
    for row in ["H", "G", "F", "E", "D", "C", "B", "A"]:
        for col in range(1, 17):
            kb["{}{:02}".format(row, col)] = linekey(next(linenumber))
    kb.update({
        "H01": user.token('builtin:alice'),
        "G01": user.token('builtin:bob'),
        "F01": user.token('builtin:charlie'),
        "E01": K_STOCKTERMINAL,
        "H02": K_MANAGETILL,
        "G02": K_MANAGESTOCK,
        "F02": K_USESTOCK,
        "E02": K_WASTE,
        "D01": K_RECALLTRANS,
        "D02": K_MANAGETRANS,
        "C01": K_PRICECHECK,
        "C02": K_PRINT,
        "B01": K_CANCEL,
        "B02": K_APPS,
        "A01": K_CLEAR,
        "A02": K_MARK,
        "D13": K_FOODORDER,
        "D14": K_FOODMESSAGE,
        "C11": K_LEFT,
        "D12": K_UP,
        "C12": K_DOWN,
        "C13": K_RIGHT,
        "E14": ".",
        "E15": "0",
        "E16": "00",
        "F14": "1",
        "F15": "2",
        "F16": "3",
        "G14": "4",
        "G15": "5",
        "G16": "6",
        "H14": "7",
        "H15": "8",
        "H16": "9",
        "B15": K_CASH,
        "D15": K_LOCK,
        "E13": K_QUANTITY,
        "H13": K_DRINKIN,
    })
    if cash_payment_method:
        kb.update({
            "C14": notekey('K_TWENTY', '£20', cash_payment_method,
                           Decimal("20.00")),
            "B14": notekey('K_TENNER', '£10', cash_payment_method,
                           Decimal("10.00")),
            "A14": notekey('K_FIVER', '£5', cash_payment_method,
                           Decimal("5.00")),
        })
    if card_payment_method:
        cardkey = paymentkey('K_CARD', 'Card', card_payment_method)
        kb.update({
            "C15": cardkey,
            "C16": cardkey,
        })
    kb.update(overrides)
    return kbdrivers.prehkeyboard(
        kb.items(),
        magstripe=[
            ("M1H", "M1T"),
            ("M2H", "M2T"),
            ("M3H", "M3T"),
        ])

def stdkeyboard_20by7(line_base=1, cash_payment_method=None,
                      card_payment_method=None, overrides={}):
    """Standard 20x7 keyboard layout

    A standard keyboard layout for a 20 by 7 key keyboard that
    produces inputs of the form [A01] to [G20].
    """
    kb = {}
    # First assign a linekey() to every key position, which we will
    # override later for special keys.
    linenumber = iter(range(line_base, line_base + 140))
    for row in ["G", "F", "E", "D", "C", "B", "A"]:
        for col in range(1, 21):
            kb["{}{:02}".format(row, col)] = linekey(next(linenumber))
    kb.update({
        "G01": user.token('builtin:eve'),
        "F01": user.token('builtin:frank'),
        "E01": user.token('builtin:giles'),
        "D01": K_STOCKTERMINAL,
        "C01": K_RECALLTRANS,
        "B01": K_CANCEL,
        "A01": K_CLEAR,
        "G02": K_MANAGETILL,
        "F02": K_MANAGESTOCK,
        "E02": K_USESTOCK,
        "G03": K_PRINT,
        "F03": K_WASTE,
        "E03": K_PRICECHECK,
        "G04": K_MANAGETRANS,
        "G05": K_APPS,
        "G07": K_FOODORDER,
        "G08": K_FOODMESSAGE,
        "F15": K_LEFT,
        "G16": K_UP,
        "F16": K_DOWN,
        "F17": K_RIGHT,
        "D18": ".",
        "D19": "0",
        "D20": "00",
        "E18": "1",
        "E19": "2",
        "E20": "3",
        "F18": "4",
        "F19": "5",
        "F20": "6",
        "G18": "7",
        "G19": "8",
        "G20": "9",
        "B19": K_CASH,
        "E17": K_QUANTITY,
        "E13": K_LOCK,
    })
    if cash_payment_method:
        kb.update({
            "C18": notekey('K_TWENTY', '£20', cash_payment_method,
                           Decimal("20.00")),
            "B18": notekey('K_TENNER', '£10', cash_payment_method,
                           Decimal("10.00")),
            "A18": notekey('K_FIVER', '£5', cash_payment_method,
                           Decimal("5.00")),
        })
    if card_payment_method:
        cardkey = paymentkey('K_CARD', 'Card', card_payment_method)
        kb.update({
            "C19": cardkey,
            "C20": cardkey,
        })
    kb.update(overrides)
    return kbdrivers.prehkeyboard(
        kb.items(),
        magstripe=[
            ("M1H", "M1T"),
            ("M2H", "M2T"),
            ("M3H", "M3T"),
        ])
