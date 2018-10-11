# Various region-specific utility functions
# and configuration that is recommended for many common cases
from . import kbdrivers
from . import user
from . import lockscreen
from . import stockterminal
from . import pricecheck
from . import managetill
from . import managestock
from . import usestock
from . import recordwaste
from . import stock
from . import register
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
    # Christmas and Boxing Day substitutes.  Cases:
    # CD and BD both on weekdays: no substitutes
    cd_wd = datetime.date(d.year, 12, 25).isoweekday()
    if cd_wd == 5:
        # CD on Friday, BD on Saturday: one substitute on Monday 28th
        if d.month == 12 and d.day == 28:
            return False
    elif cd_wd == 6:
        # CD on Saturday, BD on Sunday: substitutes on Monday 27th and
        # Tuesday 28th
        if d.month == 12 and d.day in (27, 28):
            return False
    elif cd_wd == 7:
        # CD on Sunday, BD on Monday: substitute on Tuesday 27th
        if d.month == 12 and d.day == 27:
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

    A standard keyboard layout for a 16 by 8 key keyboard.  Returns a
    dict of (row, col): keyboard.Key()
    """
    kb = {}
    # First assign a linekey() to every key position, which we will
    # override and/or delete later for special keys.
    linenumber = iter(range(line_base, line_base + 128))
    for row in range(0, 8):
        for col in range(0, 16):
            kb[(row, col)] = Key(linekey(next(linenumber)))
    kb.update({
        (0, 0): Key(user.tokenkey('builtin:alice', "Alice"),
                    css_class="usertoken"),
        (1, 0): Key(user.tokenkey('builtin:bob', "Bob"),
                    css_class="usertoken"),
        (2, 0): Key(user.tokenkey('builtin:charlie', "Charlie"),
                    css_class="usertoken"),
        (3, 0): Key(K_STOCKTERMINAL, css_class="management"),
        (0, 1): Key(K_MANAGETILL, css_class="management"),
        (1, 1): Key(K_MANAGESTOCK, css_class="management"),
        (2, 1): Key(K_USESTOCK, css_class="management"),
        (3, 1): Key(K_WASTE, css_class="management"),
        (4, 0): Key(K_RECALLTRANS, css_class="register"),
        (4, 1): Key(K_MANAGETRANS, css_class="register"),
        (5, 0): Key(K_PRICECHECK, css_class="register"),
        (5, 1): Key(K_PRINT, css_class="register"),
        (6, 0): Key(K_CANCEL, css_class="management"),
        (6, 1): Key(K_APPS, css_class="management"),
        (7, 0): Key(K_CLEAR, css_class="clear"),
        (7, 1): Key(K_MARK, css_class="register"),
        (4, 12): Key(K_FOODORDER, css_class="kitchen"),
        (4, 13): Key(K_FOODMESSAGE, css_class="kitchen"),
        (5, 10): Key(K_LEFT, css_class="cursor"),
        (4, 11): Key(K_UP, css_class="cursor"),
        (5, 11): Key(K_DOWN, css_class="cursor"),
        (5, 12): Key(K_RIGHT, css_class="cursor"),
        (3, 13): Key(".", css_class="numeric"),
        (3, 14): Key("0", css_class="numeric"),
        (3, 15): Key("00", css_class="numeric"),
        (2, 13): Key("1", css_class="numeric"),
        (2, 14): Key("2", css_class="numeric"),
        (2, 15): Key("3", css_class="numeric"),
        (1, 13): Key("4", css_class="numeric"),
        (1, 14): Key("5", css_class="numeric"),
        (1, 15): Key("6", css_class="numeric"),
        (0, 13): Key("7", css_class="numeric"),
        (0, 14): Key("8", css_class="numeric"),
        (0, 15): Key("9", css_class="numeric"),
        (6, 14): Key(K_CASH, width=2, height=2, css_class="payment"),
        (4, 14): Key(K_LOCK, width=2, css_class="lock"),
        (3, 12): Key(K_QUANTITY, css_class="register"),
        (0, 12): Key(K_DRINKIN, css_class="register"),
    })
    del kb[(6, 15)], kb[(7, 14)], kb[(7, 15)] # Cash key
    del kb[(4, 15)] # Lock key
    if cash_payment_method:
        kb.update({
            (5, 13): Key(notekey('K_TWENTY', '£20', cash_payment_method,
                                 Decimal("20.00")),
                         css_class="payment"),
            (6, 13): Key(notekey('K_TENNER', '£10', cash_payment_method,
                                 Decimal("10.00")),
                         css_class="payment"),
            (7, 13): Key(notekey('K_FIVER', '£5', cash_payment_method,
                                 Decimal("5.00")),
                         css_class="payment"),
        })
    if card_payment_method:
        kb.update({
            (5, 14): Key(paymentkey('K_CARD', 'Card', card_payment_method),
                         css_class="payment", width=2),
        })
        del kb[(5, 15)]
    kb.update(overrides)
    return kb

def stdkeyboard_20by7(line_base=1, cash_payment_method=None,
                      card_payment_method=None, overrides={}):
    """Standard 20x7 keyboard layout

    A standard keyboard layout for a 20 by 7 key keyboard.  Returns a
    dict of (row, col): keyboard.Key()
    """
    kb = {}
    # First assign a linekey() to every key position, which we will
    # override later for special keys.
    linenumber = iter(range(line_base, line_base + 140))
    for row in range(0, 7):
        for col in range(0, 20):
            kb[(row, col)] = Key(linekey(next(linenumber)))
    kb.update({
        (0, 0): Key(user.tokenkey('builtin:eve', "Eve"),
                    css_class="usertoken"),
        (1, 0): Key(user.tokenkey('builtin:frank', "Frank"),
                    css_class="usertoken"),
        (2, 0): Key(user.tokenkey('builtin:giles', "Giles"),
                    css_class="usertoken"),
        (3, 0): Key(K_STOCKTERMINAL, css_class="management"),
        (4, 0): Key(K_RECALLTRANS, css_class="register"),
        (5, 0): Key(K_CANCEL, css_class="management"),
        (6, 0): Key(K_CLEAR, css_class="clear"),
        (0, 1): Key(K_MANAGETILL, css_class="management"),
        (1, 1): Key(K_MANAGESTOCK, css_class="management"),
        (2, 1): Key(K_USESTOCK, css_class="managment"),
        (0, 2): Key(K_PRINT, css_class="register"),
        (1, 2): Key(K_WASTE, css_class="management"),
        (2, 2): Key(K_PRICECHECK, css_class="register"),
        (0, 3): Key(K_MANAGETRANS, css_class="register"),
        (0, 4): Key(K_APPS, css_class="management"),
        (0, 6): Key(K_FOODORDER, css_class="kitchen"),
        (0, 7): Key(K_FOODMESSAGE, css_class="kitchen"),
        (1, 14): Key(K_LEFT, css_class="cursor"),
        (0, 15): Key(K_UP, css_class="cursor"),
        (1, 15): Key(K_DOWN, css_class="cursor"),
        (1, 16): Key(K_RIGHT, css_class="cursor"),
        (3, 17): Key(".", css_class="numeric"),
        (3, 18): Key("0", css_class="numeric"),
        (3, 19): Key("00", css_class="numeric"),
        (2, 17): Key("1", css_class="numeric"),
        (2, 18): Key("2", css_class="numeric"),
        (2, 19): Key("3", css_class="numeric"),
        (1, 17): Key("4", css_class="numeric"),
        (1, 18): Key("5", css_class="numeric"),
        (1, 19): Key("6", css_class="numeric"),
        (0, 17): Key("7", css_class="numeric"),
        (0, 18): Key("8", css_class="numeric"),
        (0, 19): Key("9", css_class="numeric"),
        (5, 18): Key(K_CASH, width=2, height=2, css_class="payment"),
        (2, 16): Key(K_QUANTITY, css_class="register"),
        (2, 12): Key(K_LOCK, css_class="lock"),
    })
    del kb[(5, 19)], kb[(6, 18)], kb[(6, 19)] # Cash key
    if cash_payment_method:
        kb.update({
            (4, 17): Key(notekey('K_TWENTY', '£20', cash_payment_method,
                                 Decimal("20.00")),
                         css_class="payment"),
            (5, 17): Key(notekey('K_TENNER', '£10', cash_payment_method,
                                 Decimal("10.00")),
                         css_class="payment"),
            (6, 17): Key(notekey('K_FIVER', '£5', cash_payment_method,
                                 Decimal("5.00")),
                         css_class="payment"),
        })
    if card_payment_method:
        kb.update({
            (4, 18): Key(paymentkey('K_CARD', 'Card', card_payment_method),
                         css_class="payment", width=2),
        })
        del kb[(4, 19)]
    kb.update(overrides)
    return kb

# These keys are used by the register and stock terminal pages if they
# haven't already found a use for a keypress
def register_hotkeys(appsmenu=None):
    hk = {
        K_PRICECHECK: pricecheck.popup,
        K_MANAGETILL: managetill.popup,
        K_MANAGESTOCK: managestock.popup,
        K_USESTOCK: usestock.popup,
        K_WASTE: recordwaste.popup,
        K_APPS: appsmenu,
        's': managestock.popup,
        'S': managestock.popup,
        'a': stock.annotate,
        'A': stock.annotate,
        'r': recordwaste.popup,
        'R': recordwaste.popup,
        't': appsmenu,
        'T': appsmenu,
        'm': managetill.popup,
        'M': managetill.popup,
    }
    if appsmenu:
        hk[K_APPS] = appsmenu
        hk['t'] = appsmenu
        hk['T'] = appsmenu
    return hk

# Useful dictionaries of things that will be referenced by most
# configuration files
def global_hotkeys(register_hotkeys, stockterminal_location=["Bar"]):
    return {
        K_STOCKTERMINAL: lambda: stockterminal.page(
            register_hotkeys, ["Bar"]),
        K_LOCK: lockscreen.lockpage,
    }

# Dictionary to include in config to enable usertokens to activate the register
def activate_register_with_usertoken(register_hotkeys):
    return {
        'firstpage': lockscreen.lockpage,
        'usertoken_handler': lambda t: register.handle_usertoken(
            t, register_hotkeys, autolock=K_LOCK),
        'usertoken_listen': ('127.0.0.1', 8455),
        'usertoken_listen_v6': ('::1', 8455),
    }

def activate_stockterminal_with_usertoken(
        register_hotkeys,
        stockterminal_location=["Bar"],
        max_unattended_updates=5):
    return {
        'firstpage': lockscreen.lockpage,
        'usertoken_handler': lambda t: stockterminal.handle_usertoken(
            t, register_hotkeys, stockterminal_location,
            max_unattended_updates=max_unattended_updates),
        'usertoken_listen': ('127.0.0.1', 8455),
        'usertoken_listen_v6': ('::1', 8455),
    }
