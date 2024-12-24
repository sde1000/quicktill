# Various region-specific utility functions
# and configuration that is recommended for many common cases
from . import user
from . import lockscreen
from . import stockterminal
from . import pricecheck
from . import managetill
from . import managestock
from . import usestock
from . import recordwaste
from . import stock
from . import stocklines
from . import register
from . import ui
from . import td
from . import tillconfig
from . import payment
from .models import Transline, zero
from .keyboard import (
    K_STOCKTERMINAL,
    K_MANAGETILL,
    K_MANAGESTOCK,
    K_USESTOCK,
    K_WASTE,
    K_RECALLTRANS,
    K_MANAGETRANS,
    K_PRICECHECK,
    K_PRINT,
    K_CANCEL,
    K_APPS,
    K_CLEAR,
    K_MARK,
    K_FOODORDER,
    K_FOODMESSAGE,
    K_LEFT,
    K_UP,
    K_DOWN,
    K_RIGHT,
    K_CASH,
    K_LOCK,
    K_QUANTITY,
    K_DRINKIN,
    K_PASS_LOGON,
    Key,
    notekey,
    paymentkey,
    linekey,
)
import datetime
from decimal import Decimal
from dateutil.easter import easter, EASTER_WESTERN
from dateutil.relativedelta import relativedelta, MO

import logging
log = logging.getLogger(__name__)


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
    # The Spring bank holiday is the last Monday of May, except in
    # 2022 when there are special arrangements for the Queen's
    # Platinum Jubilee
    if d.year == 2022:
        if d == datetime.date(2022, 6, 2):
            return False  # Moved Spring bank holiday
        if d == datetime.date(2022, 6, 3):
            return False  # Platinum Jubilee bank holiday
    else:
        last_monday_of_may = start_of_may \
            + relativedelta(day=31, weekday=MO(-1))
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

    # The Queen's funeral is a bank holiday
    if d == datetime.date(2022, 9, 19):
        return False

    # That's it, unless the government introduce any more non-standard
    # bank holidays.  If we've got this far, the day is a banking day.
    return True


def delta_england_banking_days(date, n):
    """Return the date plus a number of banking days

    Given any date, return the date of the nth banking day after it.
    """
    if n < 1:
        raise ValueError(f"It doesn't make sense to ask for the {n}th banking "
                         f"day after a date!")
    while n > 0:
        date = date + datetime.timedelta(days=1)
        if is_england_banking_day(date):
            n = n - 1
    return date


def next_england_banking_day(date):
    """Return the next banking day on or after date
    """
    while not is_england_banking_day(date):
        date = date + datetime.timedelta(days=1)
    return date


# Useful payment date policies for the UK

def _uk_barclaycard_expected_payment_date(sessiondate):
    # Card payments are expected in the bank account two days after
    # the session, or the next banking day if the expected date is not
    # a banking day.
    date = sessiondate + datetime.timedelta(days=2)
    while not is_england_banking_day(date):
        date = date + datetime.timedelta(days=1)
    return date


def _uk_amex_expected_payment_date(sessiondate):
    return delta_england_banking_days(sessiondate, 2)


payment.date_policy["uk-barclaycard"] = _uk_barclaycard_expected_payment_date
payment.date_policy["uk-amex"] = _uk_amex_expected_payment_date


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
    del kb[(6, 15)], kb[(7, 14)], kb[(7, 15)]  # Cash key
    del kb[(4, 15)]  # Lock key
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
        (2, 1): Key(K_USESTOCK, css_class="management"),
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
    del kb[(5, 19)], kb[(6, 18)], kb[(6, 19)]  # Cash key
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


def resize(keyboard, maxwidth, maxheight):
    """Chop a keyboard down to size
    """
    kb = {}
    for loc, contents in keyboard.items():
        if loc[1] < maxwidth and loc[0] < maxheight:
            kb[loc] = contents
    return kb


def keyboard(width, height, maxwidth=None, line_base=1, overrides={}):
    """A keyboard suitable for use on-screen

    Keyboard will be the specified width and height.  If maxwidth is
    specified then line keys will be numbered such that width can be
    increased later without disturbing existing keys.
    """
    kb = {}
    if not maxwidth or maxwidth < width:
        maxwidth = width

    # First assign a linekey() to every key position, which we will
    # override and/or delete later for special keys.
    linenumber = iter(range(line_base, line_base + (maxwidth * height)))
    for row in range(0, height):
        for col in range(0, maxwidth):
            n = next(linenumber)
            if col < width:
                kb[(row, col)] = Key(linekey(n))

    # Common control keys
    alice = Key(user.tokenkey('builtin:alice', "Alice"),
                css_class="usertoken")
    bob = Key(user.tokenkey('builtin:bob', "Bob"),
              css_class="usertoken")
    charlie = Key(user.tokenkey('builtin:charlie', "Charlie"),
                  css_class="usertoken")
    stockterminal = Key(K_STOCKTERMINAL, css_class="management")
    managetill = Key(K_MANAGETILL, css_class="management")
    managestock = Key(K_MANAGESTOCK, css_class="management")
    usestock = Key(K_USESTOCK, css_class="management")
    waste = Key(K_WASTE, css_class="management")
    recalltrans2 = Key(K_RECALLTRANS, height=2, css_class="register")
    managetrans = Key(K_MANAGETRANS, css_class="register")
    pricecheck = Key(K_PRICECHECK, css_class="register")
    printkey = Key(K_PRINT, css_class="register")
    cancel = Key(K_CANCEL, css_class="management")
    apps = Key(K_APPS, css_class="management")
    clear = Key(K_CLEAR, css_class="clear")

    # Now fill in control keys according to available height
    if height == 8:
        kb.update({
            (0, 0): alice,         (0, 1): managetill,     # noqa: E241
            (1, 0): bob,           (1, 1): managestock,    # noqa: E241
            (2, 0): charlie,       (2, 1): usestock,       # noqa: E241
            (3, 0): recalltrans2,  (3, 1): waste,          # noqa: E241
                                   (4, 1): managetrans,
            (5, 0): pricecheck,    (5, 1): printkey,       # noqa: E241
            (6, 0): cancel,        (6, 1): apps,           # noqa: E241
            (7, 0): clear,         (7, 1): stockterminal,  # noqa: E241
        })
    elif height == 7:
        kb.update({
            (0, 0): alice,         (0, 1): managetill,     # noqa: E241
            (1, 0): managestock,   (1, 1): usestock,       # noqa: E241
            (2, 0): recalltrans2,  (2, 1): waste,          # noqa: E241
                                   (3, 1): managetrans,
            (4, 0): pricecheck,    (4, 1): printkey,       # noqa: E241
            (5, 0): cancel,        (5, 1): apps,           # noqa: E241
            (6, 0): clear,         (6, 1): stockterminal,  # noqa: E241
        })
    elif height == 6:
        kb.update({
            (0, 0): managetill,    (0, 1): managestock,    # noqa: E241
            (1, 0): waste,         (1, 1): usestock,       # noqa: E241
            (2, 0): recalltrans2,  (2, 1): managetrans,    # noqa: E241
                                   (3, 1): printkey,
            (4, 0): cancel,        (4, 1): pricecheck,     # noqa: E241
            (5, 0): clear,         (5, 1): stockterminal,  # noqa: E241
            (0, width - 1): apps,
        })
    kb.update(overrides)
    return kb


def keyboard_rhpanel(cash_payment_method,
                     card_payment_method,
                     overrides={}):
    kb = {
        (0, 0): Key("7", css_class="numeric"),
        (0, 1): Key("8", css_class="numeric"),
        (0, 2): Key("9", css_class="numeric"),
        (1, 0): Key("4", css_class="numeric"),
        (1, 1): Key("5", css_class="numeric"),
        (1, 2): Key("6", css_class="numeric"),
        (2, 0): Key("1", css_class="numeric"),
        (2, 1): Key("2", css_class="numeric"),
        (2, 2): Key("3", css_class="numeric"),
        (3, 0): Key(".", css_class="numeric"),
        (3, 1): Key("0", css_class="numeric"),
        (3, 2): Key("00", css_class="numeric"),
        (4, 0): Key(K_QUANTITY, css_class="register"),
        (4, 1): Key(K_UP, css_class="cursor"),
        (4, 2): Key(K_MARK, css_class="register"),
        (5, 0): Key(K_LEFT, css_class="cursor"),
        (5, 1): Key(K_DOWN, css_class="cursor"),
        (5, 2): Key(K_RIGHT, css_class="cursor"),
        (6, 0): Key(K_PASS_LOGON, css_class="management"),
        (6, 1): Key(K_LOCK, width=2, css_class="lock"),
        (7, 0): Key(notekey('K_TWENTY', '£20', cash_payment_method,
                            Decimal("20.00")),
                    css_class="payment"),
        (8, 0): Key(notekey('K_TENNER', '£10', cash_payment_method,
                            Decimal("10.00")),
                    css_class="payment"),
        (9, 0): Key(notekey('K_FIVER', '£5', cash_payment_method,
                            Decimal("5.00")),
                    css_class="payment"),
        (7, 1): Key(paymentkey('K_CARD', 'Card', card_payment_method),
                    css_class="payment", width=2),
        (8, 1): Key(K_CASH, width=2, height=2, css_class="payment"),
    }
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
        's': managestock.popup,
        'S': managestock.popup,
        'a': stock.annotate,
        'A': stock.annotate,
        'r': recordwaste.popup,
        'R': recordwaste.popup,
        'm': managetill.popup,
        'M': managetill.popup,
        'n': stocklines.stocklinenotemenu,
        'N': stocklines.stocklinenotemenu,
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
            register_hotkeys, stockterminal_location, user=ui.current_user()),
        K_LOCK: lockscreen.lockpage,
        K_PASS_LOGON: lambda: tillconfig.passlogon_handler(),
    }


# Dictionary to include in config to enable usertokens to activate the register
def activate_register_with_usertoken(register_hotkeys, timeout=300):
    return {
        'firstpage': lockscreen.lockpage,
        'usertoken_handler': lambda t: register.handle_usertoken(
            t, register_hotkeys, autolock=K_LOCK, timeout=timeout),
        'usertoken_listen': ('127.0.0.1', 8455),
        'usertoken_listen_v6': ('::1', 8455),
        'barcode_listen': ('127.0.0.1', 8456),
        'barcode_listen_v6': ('::1', 8456),
    }


def activate_register_with_password(register_hotkeys, timeout=300):
    return {
        'passlogon_handler': lambda: register.handle_passlogon(
            register_hotkeys, autolock=K_LOCK, timeout=timeout),
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
        'barcode_listen': ('127.0.0.1', 8456),
        'barcode_listen_v6': ('::1', 8456),
    }


def activate_stockterminal_with_password(register_hotkeys,
                                         stockterminal_location=["Bar"],
                                         max_unattended_updates=5):
    return {
        'passlogon_handler': lambda: stockterminal.handle_passlogon(
            register_hotkeys, stockterminal_location,
            max_unattended_updates=max_unattended_updates),
    }


class ServiceCharge(register.RegisterPlugin):
    """Apply a service charge to the current transaction

    When the key is pressed, remove any existing service charge and
    add the new service charge based on the current transaction total.
    """
    def __init__(self, key, percentage, dept, description="Service Charge"):
        self._key = key
        self._percentage = Decimal(percentage)
        self._dept = dept
        self._description = description

    def _update_charge(self, reg):
        log.debug("service charge")
        trans = reg.gettrans()
        if not trans:
            ui.infopopup(["You can't apply a service charge with no "
                          "current transaction."], title="Error")
            return
        if trans.closed:
            ui.infopopup(["You can't apply a service charge to a transaction "
                          "that is already closed."], title="Error")
            return
        # Delete all the transaction lines that are in the service charge
        # department, as long as they are not voided or voids
        td.s.query(Transline)\
            .filter(
                Transline.transaction == trans,
                Transline.transcode == 'S',
                Transline.voided_by_id == None,
                Transline.dept_id == self._dept)\
            .delete()
        td.s.flush()
        balance = trans.balance
        if balance > zero:
            td.s.add(
                Transline(
                    items=1, dept_id=self._dept,
                    amount=balance * self._percentage / 100,
                    user=ui.current_user().dbuser,
                    source=tillconfig.terminal_name,
                    transcode='S',
                    text=self._description,
                    transaction=trans))
            td.s.flush()
        reg.reload_trans()

    def keypress(self, reg, key):
        if key == self._key:
            self._update_charge(reg)
            return True
        return False
