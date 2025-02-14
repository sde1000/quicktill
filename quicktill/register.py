"""Cash register page.  Allows transaction entry, voiding of lines."""

# A brief word about how redrawing the screen works:
#
# There are four main areas to worry about: the screen header, the
# transaction note, the display list and the "buffer" line.
#
# The screen header shows the page header, a summary of the other
# pages, and the clock.  It needs updating whenever the current
# transaction changes: from none to present, from present to none, or
# from open to closed.  It is updated by calling self.updateheader().
#
# The transaction note shows whatever note is set for the current
# transaction.  It is updated by calling self._redraw_note().
#
# The display list is a list of line() objects, that correspond to
# lines in a transaction.  When a transaction line is modified you
# must call the update() method of the corresponding line object.  The
# display list is redrawn in one of two ways: 1) Call redraw().  This
# scrolls to the current cursor position.  2) Call self.s.drawdl().  No
# scrolling is performed.  After you append an item to the display
# list, you should call cursor_off() before calling redraw() to make
# sure that we scroll to the end of the list.
#
# The "buffer" line shows either a prompt or the input buffer at the
# left, and the balance of the current transaction at the right.  It
# is implemented as a notional "last entry" in the display list, and
# will only be redrawn when the display list is redrawn.

from . import tillconfig
import math
import time
from . import td, ui, keyboard, printer
import quicktill.stocktype
from . import linekeys
from . import modifiers
from . import payment
from . import user
from . import plugins
from . import config
from . import listen
import logging
import datetime
from .models import Transline, Transaction, Session, StockOut, penny
from .models import PayType, Payment, zero, User, Department, desc
from .models import StockType, StockLine, StockItem
from .models import KeyboardBinding
from .models import max_quantity
from sqlalchemy.sql import func
from decimal import Decimal
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import undefer

log = logging.getLogger(__name__)

# How old can a transaction line be before it is unable to be modified
# in place?
max_transline_modify_age = config.IntervalConfigItem(
    'register:max_transline_modify_age', datetime.timedelta(minutes=1),
    display_name="Transaction line modify-in-place age limit",
    description="For how long after it is created can a transaction line be "
    "modified?  This applies both to adding additional items and voiding "
    "the line.")

# When recalling an open transaction, warn if it is older than this
# If set to None, never warn
open_transaction_warn_after = config.IntervalConfigItem(
    'register:open_transaction_warn_after', datetime.timedelta(days=2),
    display_name="Warn about open transactions after",
    description="When recalling an open transaction, warn the user if it "
    "is older than this.  If blank, never warn.")

# Prohibit adding lines to a transaction if it is older than this
open_transaction_lock_after = config.IntervalConfigItem(
    'register:open_transaction_lock_after', None,
    display_name="Lock open transactions after",
    description="Prohibit adding lines to an open transaction when it is "
    "older than this.  If blank, never lock.")

# Message to give to the user when a transaction is locked
open_transaction_lock_message = config.ConfigItem(
    'register:open_transaction_lock_message', "",
    display_name="Locked transaction message",
    description="Display this message to the user when a transaction "
    "is locked.")

# Allow transactions with payments to be merged?
allow_mergetrans_with_payments = config.BooleanConfigItem(
    'register:allow_mergetrans_with_payments', False,
    display_name="Allow merging transactions with payments",
    description="Allow transactions that have payments to be merged into "
    "other transactions? Only payment types that are explicitly marked "
    "'mergeable' will be permitted; the presence of payments of other "
    "types will still prevent merging.")

# Automatically lock after No Sale?
lock_after_nosale = config.BooleanConfigItem(
    'register:lock_after_nosale', False,
    display_name="Lock after No Sale",
    description="Lock the register after performing a No Sale operation?")

# RemoveCode ID to use for stock that is sold
sold_removecode_id = config.ConfigItem(
    'register:sold_stock_removecode_id', "sold",
    display_name="Code for sold stock",
    description="Stock usage code (RemoveCode.id) for stock that is sold")

# RemoveCode ID to use for stock that is wasted by pulling through
pullthru_removecode_id = config.ConfigItem(
    'register:pullthru_stock_removecode_id', "pullthru",
    display_name="Code for stock pulled through",
    description="Stock usage code (RemoveCode.id) for stock that "
    "is pulled through")

# Default payment method used (sometimes) when Cash/Enter is pressed
# on an open transaction
default_payment_method = config.ConfigItem(
    'register:default_payment_method', "CASH",
    display_name="Default payment method",
    description="Code of payment method to use when Cash/Enter is pressed "
    "on an open transaction. If empty or invalid, pressing Cash/Enter will "
    "always open the payment methods menu.")

# Payment method used for the "Drink 'In'" function
drinkin_payment_method = config.ConfigItem(
    'register:drinkin_payment_method', "CASH",
    display_name="Drink 'In' payment method",
    description="Code of payment method to use for the Drink 'In' function. "
    "If empty or invalid, the Drink 'In' function will be disabled.")

# Payment method used for deferring part-paid transactions
defer_payment_method = config.ConfigItem(
    'register:defer_payment_method', "CASH",
    display_name="Deferred payment method",
    description="Code of payment method to use when deferring a part-paid "
    "transaction that has some non-deferrable payments. The amount of the "
    "non-deferrable payments will be refunded, and a note will be printed "
    "with instructions describing how to apply the payment to the "
    "transaction in a future session.")

# Automatically open the payment method menu after creating a
# transaction that voids lines from another transaction?
payment_method_menu_after_void = config.BooleanConfigItem(
    'register:payment_method_menu_after_void', False,
    display_name="Payment method menu after void",
    description="Automatically open the payment method menu after "
    "creating a transaction that voids lines from another transaction?")

refund_help_text = config.ConfigItem(
    'register:refund_help_text',
    "This transaction has a negative balance, so a "
    "refund is due.  Press the appropriate payment key "
    "to issue a refund of that type.  If you are replacing "
    "items for a customer you can enter the replacement "
    "items now; the till will show the difference in price "
    "between the original and replacement items.",
    display_name="Refund help text",
    description="Prompt displayed when a transaction has a negative balance "
    "and a refund may be due")


# Transaction metadata keys
transaction_message_key = "register-message"

# Colour used for locked transactions in transaction lists
colour_locked = ui.colourpair("locked", "yellow", "blue")

# Permissions checked for explicitly in this module
user.action_descriptions['override-price'] = "Override the sale price " \
    "of an item"
user.action_descriptions['nosale'] = "Open the cash drawer with no payment"
user.action_descriptions['suppress-refund-help-text'] = \
    "Don't show the refund help text"
user.action_descriptions['cancel-line-in-open-transaction'] = \
    "Delete or reverse a line in an open transaction"
user.action_descriptions['void-from-closed-transaction'] = \
    "Create a transaction voiding lines from a closed transaction"
user.action_descriptions['sell-dept'] = \
    "Sell items using a department key"


class RegisterPlugin(metaclass=plugins.InstancePluginMount):
    """A plugin to add functionality to the register

    Create instances of subclasses of this class to add functions to
    the register.

    A number of hooks are available; define a method "hook_{name}" to
    make use of them.  If a hook returns trueish, the default action,
    if any, is not performed.  The hook method is passed the register
    as the first argument, and then any hook-specific arguments.
    Available hooks are:

     - new_page(); there is no default action
     - recalltrans_loaded(trans); transaction loaded using Recall Trans; there
         is no default action
     - linekey(kb, mod)
     - barcode(b, mod) - recognised barcode
     - unknown_barcode(scan)
     - drinkin(trans, amount) - "drink in" function on open transaction
     - nosale() - just before kicking out the cash drawer on closed transaction
     - cashkey(trans) - cash/enter on an open transaction
     - paymentkey(paytype, trans) - payment key on an open transaction
     - close_transaction(trans) - called just before closing a balanced
         transaction
     - start_payment(paytype, trans, amount, balance) - about to invoke a
         payment method
     - printkey(trans)
     - cancelkey(trans) - cancel key on an open or closed transaction
     - cancelmarked(trans) - cancel marked lines on an open or closed
         transaction
     - canceltrans(trans) - trans may be open or closed
     - cancelempty(trans) - cash/enter on an empty transaction
     - sell_plu(trans, plu, items, current_transline) - add or update PLU
           on open transaction
     - cancelline(l)
     - cancelpayment(p)
     - markkey()
     - recalltranskey()
     - defertrans(trans) - trans is open
     - mergetrans(trans) - merge transaction menu option
     - mergetrans_finish(trans, othertrans) - about to merge trans into
         othertrans
     - apply_discount_menu()
     - managetrans(trans) - Manage Transaction menu
    """
    def keypress(self, register, keypress):
        """Handle an unknown keypress on the register

        Called when the register does not recognise a keypress.
        Return True to indicate that the keypress has been handled.

        The register's current transaction, if any, will be valid and
        up to date.
        """
        return False

    def override_refund_help_text(self, register, trans):
        """Customise the refund help text for a transaction

        To override the default help text, return a string.  trans is
        guaranteed to be an open transaction.
        """
        return

    def update_tline(self, tline, tl):
        """Customise the look of a transaction line in the register

        tline is the tline object.  tl is the corresponding Transline
        model instance.

        This method may set:
         - tline.ltext
         - tline.rtext
         - tline.default_colour
        """
        return


class _DiscountPolicyMount(type):
    def __init__(cls, name, bases, attrs):
        if not hasattr(cls, 'policies'):
            cls.policies = {}

    def __call__(cls, *args, **kwargs):
        x = type.__call__(cls, *args, **kwargs)
        cls.policies[x.policy_name] = x
        if x.permission_required:
            user.action_descriptions[x.permission_required[0]] \
                = x.permission_required[1]


class DiscountPolicyPlugin(metaclass=_DiscountPolicyMount):
    """A plugin to add a discount policy to the register

    Create instances of subclasses of this class to add discount policies.
    """
    # Permission required to set this as a transaction's discount policy
    permission_required = None

    def __init__(self, policy_name):
        self.policy_name = policy_name

    def discount_for(self, transline):
        """Calculate the discount for a transaction line and return it

        The amount returned is the discount _per item_, i.e. the value
        to subtract from the 'original_amount' property to apply the
        discount, and the name of the discount, in a 2-tuple.

        Eg. if the transaction line is for 2 items at £0.50 each and
        the discount is 10% and called "foo", return (Decimal(0.05), "foo")

        This method may read any information it needs to make its
        decision by following relationships from transline, but must
        not alter any information in the database.

        It should read the 'original_amount' property instead of the
        'amount' column, because 'amount' may already have a discount
        applied.

        The discount returned must not be less than zero or greater
        than the original transaction line amount.
        """
        return zero, self.policy_name


class PercentageDiscount(DiscountPolicyPlugin):
    """A flat percentage discount, optionally restricted to a set of departments

    Percentage must be between 0.0 and 100.0.
    """

    def __init__(self, policy_name, percentage, departments=None,
                 permission_required=None):
        super().__init__(policy_name)
        self._percentage = percentage
        self._departments = departments
        self.permission_required = permission_required

    def discount_for(self, transline):
        if self._departments:
            if transline.department.id not in self._departments:
                return zero, self.policy_name
        return (transline.original_amount * Decimal(self._percentage / 100.0))\
            .quantize(penny), self.policy_name


def _transaction_age_locked(trans):
    """Is the transaction to be treated as locked?
    """
    if trans.closed or not open_transaction_lock_after():
        return False
    return trans.age > open_transaction_lock_after()


class bufferline(ui.lrline):
    """The last line on the register display

    This is used as the very last line on the register display - a
    special case.  It always consists of two lines: a blank line, and
    then a line showing the prompt or the contents of the input buffer
    at the left, and if appropriate the balance of the transaction on
    the right.
    """
    def __init__(self, reg):
        super().__init__()
        self.colour = ui.colour_default
        self.cursor_colour = ui.colour_default
        self.reg = reg

    def display(self, width):
        self.update()  # clear cached outputs
        if self.reg.qty is not None:
            m = f"{self.reg.qty} of "
        else:
            m = ""
        if self.reg.mod is not None:
            m = m + f"{self.reg.mod.name} "
        if self.reg.buf is not None:
            m = m + self.reg.buf
        if len(m) > 0:
            cursorx = len(m)
            if self.reg.locked:
                m = m + " (locked)"
            self.ltext = m
        else:
            self.ltext = "Locked" if self.reg.locked else self.reg.prompt
            cursorx = 0
            if self.reg.balance < zero and not self.reg.user.has_permission(
                    'suppress-refund-help-text'):
                self.ltext = self.reg.current_refund_help_text
        if self.reg.ml:
            self.rtext = \
                f"Marked lines total "\
                f"{tillconfig.fc(self.reg._total_value_of_marked_translines())}"
        else:
            log.debug("bal %s", repr(tillconfig.fc(self.reg.balance)))
            if self.reg.balance > zero:
                self.rtext = "Amount to pay {}{}".format(
                    "(includes {} discount) ".format(
                        self.reg.discount_policy.policy_name)
                    if self.reg.discount_policy else "",
                    tillconfig.fc(self.reg.balance))
            elif self.reg.balance < zero:
                self.rtext = f"Refund amount {tillconfig.fc(self.reg.balance)}"
            else:
                self.rtext = ""
        # Add the expected blank line
        l = [''] + super().display(width)
        self.cursor = (cursorx, len(l) - 1)
        return l


class tline(ui.lrline):
    """A transaction line loaded to be displayed

    This corresponds to a transaction line in the database.
    """
    def __init__(self, transline):
        super().__init__()
        self.transline = transline
        self.marked = False
        self.default_colour = ui.colour_default
        self.update()

    def update(self):
        super().update()
        tl = td.s.get(Transline, self.transline)
        self.transtime = tl.time
        if tl.voided_by_id:
            self.voided = True
            self.ltext = "(Voided) " + tl.description
        else:
            self.voided = False
            self.ltext = tl.description
        self.rtext = tl.regtotal(tillconfig.currency())
        for i in RegisterPlugin.instances:
            i.update_tline(self, tl)
        self.update_colour()

    def update_colour(self):
        if self.marked:
            self.colour = ui.colour_cancelline
        else:
            if self.voided:
                self.colour = ui.colour_error
            else:
                self.colour = self.default_colour
        self.cursor_colour = self.colour.reversed

    def age(self):
        return datetime.datetime.now() - self.transtime

    def update_mark(self, ml):
        self.marked = self in ml
        self.update_colour()


class edittransnotes(user.permission_checked, ui.dismisspopup):
    """A popup to allow a transaction's notes to be edited."""
    permission_required = ("edit-transaction-note",
                           "Alter a transactions's note")

    def __init__(self, transid, func):
        self.transid = transid
        self.func = func
        trans = td.s.get(Transaction, transid)
        super().__init__(
            5, 60, title=f"Notes for transaction {trans.id}",
            colour=ui.colour_input)
        notes = trans.notes
        self.notesfield = ui.editfield(2, 2, 56, f=notes, flen=60, keymap={
            keyboard.K_CASH: (self.enter, None)})
        self.notesfield.focus()

    def enter(self):
        notes = self.notesfield.f
        self.dismiss()
        self.func(notes)


class splittrans(user.permission_checked, ui.dismisspopup):
    """A popup to allow marked lines to be split into a different transaction.
    """
    permission_required = ("split-trans", "Split a transaction into two parts")

    def __init__(self, total, func):
        super().__init__(
            8, 64, title="Move marked lines to new transaction",
            colour=ui.colour_input)
        self._func = func
        self.win.drawstr(2, 2, 60, f"Total value of marked lines: {total}")
        self.win.drawstr(4, 2, 60, "Notes for the new transaction containing "
                         "the marked lines:")
        self.notesfield = ui.editfield(5, 2, 60, flen=60, keymap={
            keyboard.K_CASH: (self.enter, None)})
        self.notesfield.focus()

    def enter(self):
        notes = self.notesfield.f
        if not notes:
            ui.infopopup(
                ["You must set a note for the new transaction, otherwise you "
                 "will not be able to find it in the list of open "
                 "transactions!"],
                title="Note needed")
            return
        self.dismiss()
        self._func(notes)


class addtransline(user.permission_checked, ui.dismisspopup):
    """A popup to allow an arbitrary transaction line to be created.
    """
    permission_required = ('add-custom-transline',
                           'Add a custom transaction line')

    def __init__(self, func):
        self.func = func
        super().__init__(
            9, 70, title="Add a custom transaction line",
            colour=ui.colour_input)
        self.win.drawstr(2, 2, 13, "Department: ", align=">")
        self.win.drawstr(3, 2, 13, "Description: ", align=">")
        self.deptfield = ui.modellistfield(
            2, 15, 20, Department,
            lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
            keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.descfield = ui.editfield(3, 15, 53, flen=300)
        self.itemsfield = ui.editfield(4, 15, 5, validate=ui.validate_int)
        self.win.addstr(4, 21, f"items @ {tillconfig.currency}")
        self.amountfield = ui.editfield(4, 29 + len(tillconfig.currency()), 8,
                                        validate=ui.validate_positive_float)
        self.win.addstr(4, 38 + len(tillconfig.currency()), '=')
        self.itemsfield.sethook = self.calculate_total
        self.amountfield.sethook = self.calculate_total
        self.addbutton = ui.buttonfield(
            6, 25, 20, "Add transaction line",
            keymap={
                keyboard.K_CASH: (self.enter, None)})
        ui.map_fieldlist(
            [self.deptfield, self.descfield, self.itemsfield,
             self.amountfield, self.addbutton])
        self.total = ui.label(4, 40 + len(tillconfig.currency()), 15)
        self.deptfield.focus()

    def calculate_total(self):
        self.total.set("")
        try:
            items = int(self.itemsfield.f)
            amount = Decimal(self.amountfield.f)
            if items == 0:
                raise Exception("Zero items not permitted")
        except Exception:
            return
        self.total.set(tillconfig.fc(items * amount))

    def enter(self):
        dept = self.deptfield.read()
        if dept is None:
            return ui.infopopup(["You must specify a department."],
                                title="Error")
        text = self.descfield.f if self.descfield.f else dept.description
        try:
            items = int(self.itemsfield.f)
            amount = Decimal(self.amountfield.f)
        except Exception:
            return ui.infopopup(["You must specify the number of items and "
                                 "the amount per item."], title="Error")
        if items == 0:
            return ui.infopopup(["You can't create a transaction line with no "
                                 "items.  Create a transaction line with one "
                                 "item of zero price instead."], title="Error")
        if amount < zero:
            return ui.infopopup(["You can't create a transaction line with a "
                                 "negative amount.  Create a transaction line "
                                 "with a negative number of items instead."],
                                title="Error")
        self.dismiss()
        self.func([(dept.id, text, items, amount)])


class recalltranspopup(user.permission_checked, ui.dismisspopup):
    """Popup to allow transaction number entry

    Recalls the transaction to the register.
    """
    permission_required = (
        "recall-any-trans", "Recall any transaction, even from "
        "previous sessions")

    def __init__(self, reg):
        self._reg = reg
        super().__init__(5, 34, title="Recall Transaction",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 20, "Transaction number: ", align=">")
        self.transfield = ui.editfield(
            2, 22, 10, validate=ui.validate_int, keymap={
                keyboard.K_CASH: (self.enterkey, None)})
        self.transfield.focus()

    def enterkey(self):
        self.dismiss()
        try:
            transid = int(self.transfield.read())
        except Exception:
            return
        self._reg.recalltrans(transid)


class transline_search_popup(ui.dismisspopup):
    """Popup to allow a transaction line to be searched for

    Calls func with the transaction ID as the argument.
    """
    def __init__(self, func):
        self._func = func
        super().__init__(11, 70, title="Search for an item",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 12, "Search for: ", align=">")
        self.win.drawstr(3, 2, 12, "Department: ", align=">")
        self.win.drawstr(3, 35, 30, "(leave blank for 'any')")
        self.win.drawstr(5, 2, 26, "Number of days to search: ",
                         align=">")
        self.win.drawstr(6, 15, 40, "(leave blank for current day only)")
        self.textfield = ui.editfield(
            2, 14, 54,
            keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.deptfield = ui.modellistfield(
            3, 14, 20, Department,
            lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
        )
        self.daysfield = ui.editfield(5, 28, 3, validate=ui.validate_int)
        self.searchbutton = ui.buttonfield(
            8, 30, 10, "Search", keymap={
                keyboard.K_CASH: (self.enter, None, False)})
        ui.map_fieldlist([self.textfield, self.deptfield, self.daysfield,
                          self.searchbutton])
        self.textfield.focus()

    def enter(self):
        if not self.textfield.f:
            ui.infopopup(["You must enter some text to search for."],
                         title="Error")
            return
        self.dismiss()
        dept = self.deptfield.read()
        try:
            days = int(self.daysfield.f)
        except Exception:
            days = 0
        after = datetime.date.today() - datetime.timedelta(days=days)

        q = td.s.query(Transline)\
                .join(Transaction)\
                .join(Session)\
                .filter(Transline.text.ilike(f'%{self.textfield.f}%'))\
                .filter(Session.date >= after)\
                .order_by(Transline.id.desc())
        if dept:
            q = q.filter(Transline.department == dept)
        f = ui.tableformatter(" l r l ")
        header = f("Time", "Qty", "Description")
        menu = [(f(ui.formattime(x.time), x.items, x.text),
                 self._func, (x.transid,)) for x in q.limit(1000).all()]
        ui.menu(menu, blurb=header, title="Search results")


def strtoamount(s):
    if s.find('.') >= 0:
        return Decimal(s).quantize(penny)
    return int(s) * penny


def no_saleprice_popup(user, stocktype):
    """The user tried to sell an item that doesn't have a price set

    Pop up an appropriate error message for an item of stock with a
    missing sale price.  Offer to let the user set it if they have the
    appropriate permissions.
    """
    ist = stocktype
    if user.may('override-price') and user.may('reprice-stock'):
        ui.infopopup(
            [f"No sale price has been set for {ist}.  You can enter a price "
             f"before pressing the line key to set the price just this once, "
             f"or you can press {keyboard.K_MANAGESTOCK} now to set "
             f"the price permanently."],
            title="Unpriced item found", keymap={
                keyboard.K_MANAGESTOCK: (
                    lambda: quicktill.stocktype.reprice_stocktype(ist),
                    None, True)})
    elif user.may('override-price'):
        ui.infopopup(
            [f"No sale price has been set for {ist}.  You can enter a price "
             "before pressing the line key to set the price just this once."],
            title="Unpriced item found")
    else:
        ui.infopopup(
            [f"No sale price has been set for {ist}.  You must ask a manager "
             "to set a price for it before you can sell it."],
            title="Unpriced item found")


def record_pullthru(stockid, qty):
    td.s.add(StockOut(stockid=stockid, qty=qty,
                      removecode_id=pullthru_removecode_id()))
    td.s.flush()


class repeatinfo:
    """Information for repeat keypresses."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _update_timeout_scrollable(ui.scrollable):
    """A scrollable that calls _update_timeout() on its parent when it
    receives the input focus.
    """
    def focus(self):
        super().focus()
        self.parent._update_timeout()


class InvalidSale(Exception):
    def __init__(self, msg):
        self.msg = msg


class ProposedSale:
    """A proposed sale of a single item.

    Details of the sale are collected in an instance of this class.
    When complete, the instance may be passed to a modifier which may
    mutate it as it likes.

    Instance attributes:

    description - the text visible on the register display and receipt
    for this sale

    price - the price that will be charged for the item.  May be None
    if unknown.

    qty - the number of units of stock being sold.  Must be a Decimal,
    or None if no stock is associated with the sale.

    stocktype (read only) - the type of stock being sold.  May be None
    if no stock is associated with the sale.
    """
    def __init__(self, description="", price=None, qty=None, stocktype=None,
                 whole_items=False):
        self.description = description
        self.price = price
        self.qty = qty
        self._stocktype = stocktype
        self._whole_items = whole_items

    @property
    def stocktype(self):
        return self._stocktype

    def validate(self):
        if not self.description:
            raise InvalidSale("No description")
        if self.stocktype:
            if not isinstance(self.qty, Decimal):
                raise InvalidSale("qty is not a Decimal")
            if self._whole_items and math.floor(self.qty) != self.qty:
                raise InvalidSale("qty is not a whole number")
            if not isinstance(self.stocktype, StockType):
                raise InvalidSale("stocktype is not a StockType")
        else:
            if self._whole_items:
                raise InvalidSale("stocktype missing for sale of whole number "
                                  "of items")
            if self.qty is not None:
                raise InvalidSale("qty present with no stocktype")


class page(ui.basicpage):
    def __init__(self, user, hotkeys, autolock=None, timeout=300):
        """A cash register page

        autolock is the keycode of the "Lock" button, if the caller
        wants the register to lock automatically at the end of each
        transaction

        timeout is the length of time in seconds since the most recent
        action before the register automatically deselects itself
        """
        # trans and user are needed for "pagename" which is called in
        # basicpage.__init__()
        # transid is now a transaction ID, not a models.Transaction object
        self._start_time = time.time()
        self.transid = None
        self.user = user
        log.info("Page created for %s", self.user.fullname)
        super().__init__()
        self._autolock = autolock
        self.locked = False
        self._timeout = timeout
        self._timeout_handle = None  # Used to cancel timeout
        self._update_timeout()
        # XXX hack to avoid drawing into bottom right-hand cell; is
        # this still necessary?
        self.h = self.h - 1
        self.hotkeys = hotkeys
        self.defaultprompt = "Ready"
        # Set user's current register to be us
        self.user.dbuser.register_id = tillconfig.register_id
        # Save user's current transaction because it is unset by clear()
        candidate_trans = self.user.dbuser.transaction
        self._clear()
        self.s = _update_timeout_scrollable(
            1, 0, self.w, self.h - 1, self.dl, lastline=bufferline(self))
        self.s.focus()
        if candidate_trans is not None:
            session = Session.current(td.s)
            if candidate_trans.session == session:
                # It's a transaction in the current session - load it
                self._loadtrans(candidate_trans.id)
            else:
                # The session has expired
                log.info("User's transaction %d is for a different session",
                         candidate_trans.id)
        else:
            # We're starting with a clear display.  The user might
            # have been expecting a transaction!  If there's a message
            # left for the user, display it now.
            if self.user.dbuser.message:
                ui.infopopup([self.user.dbuser.message],
                             title="Transaction information")
                self.user.dbuser.message = None
        td.s.flush()
        self._redraw()
        self._notify_user_register_listener = listen.listener.listen_for(
            "user_register", self._notify_user_register)
        self.hook("new_page")
        self._resume_pending_payment()

    def _gettrans(self):
        """Obtain the Transaction object for the current transaction

        Queries the database if the Transaction has not been loaded,
        otherwise loads it from the database session's identity map.

        If there is no current transaction (self.transid is None or the
        referenced transaction doesn't exist) returns None.
        """
        if self.transid:
            return td.s.get(Transaction, self.transid,
                            options=[joinedload(Transaction.meta)])

    def gettrans(self):
        """Obtain the Transaction object for the current transaction

        Used by plugins.
        """
        return self._gettrans()

    def clear(self):
        """Clear the register

        Used by plugins.
        """
        self._clear()
        self._redraw()

    def _update_timeout(self):
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None
        if self._timeout:
            self._timeout_handle = tillconfig.mainloop.add_timeout(
                self._timeout, self.alarm, desc="register auto-lock")

    def clearbuffer(self):
        """Clear user input from the buffer.

        Doesn't reset the prompt or current balance.
        """
        self.buf = ""    # Input buffer
        self.qty = None  # Quantity (integer)
        self.mod = None  # Modifier (modkey object)

    def _clear(self):
        """Reset the page.

        Reset the page to having no current transaction and nothing in
        the input buffer.  Note that this does not cause a redraw;
        various functions may want to fiddle with the state (for
        example loading a previous transaction) before requesting a
        redraw.
        """
        self.dl = []  # Display list
        if hasattr(self, 's'):
            # Tell the scrollable about the new display list
            self.s.set(self.dl)
        self.ml = set()  # Set of marked tlines
        self.transid = None  # Current transaction
        self.discount_policy = None
        self.user.dbuser.transaction = None
        # If the transaction is locked this will be a list of messages to
        # display to the user about why the transaction is locked.  Otherwise,
        # it will be an empty list.
        self.transaction_locked = []
        # If dept/line button pressed, update this transline
        self.repeat = None
        self.keyguard = False
        self.clearbuffer()
        self.balance = zero  # Cache of balance of current transaction
        self.prompt = self.defaultprompt
        self._redraw_note()
        td.s.flush()

    def _clear_marks(self):
        if self.ml:
            self.ml = set()
            for l in self.dl:
                if isinstance(l, tline):
                    l.update_mark(self.ml)
            self.prompt = self.defaultprompt

    def _loadtrans(self, transid, update_discount=False):
        """Load a transaction, overwriting all our existing state.
        """
        log.debug("Register: loadtrans %s", transid)
        # Reload the transaction and its related objects
        trans = td.s.query(Transaction)\
                    .filter_by(id=transid)\
                    .options(subqueryload(Transaction.payments))\
                    .options(joinedload(Transaction.lines)
                             .joinedload(Transline.user))\
                    .options(joinedload(Transaction.meta))\
                    .options(undefer(Transaction.total))\
                    .one()
        self.transid = trans.id
        if trans.user:
            # There is a unique constraint on User.trans_id - if
            # another user has this transaction, remove it from them
            # before claiming it for the current user otherwise we
            # will receive an integrity exception.
            trans.user = None
            td.s.flush()
        trans.user = self.user.dbuser
        self.discount_policy = DiscountPolicyPlugin.policies.get(
            trans.discount_policy, None)
        if update_discount:
            for line in trans.lines:
                self._apply_discount(line)
        self.dl = [tline(l.id) for l in trans.lines] \
            + [payment.pline(i) for i in trans.payments]
        self.s.set(self.dl)
        self.ml = set()
        if _transaction_age_locked(trans):
            self.transaction_locked = [
                "This transaction is locked because it is more than "
                f"{open_transaction_lock_after().days} days old."]
            if open_transaction_lock_message():
                self.transaction_locked.append("")
                self.transaction_locked.append(open_transaction_lock_message())
        self._redraw_note()
        self.close_if_balanced()
        self.repeat = None
        self.update_balance()
        self.prompt = self.defaultprompt
        self.keyguard = (trans.notes != "")
        self.clearbuffer()
        self.cursor_off()
        td.s.flush()
        self._redraw()

    def reload_trans(self):
        """Reload the current transaction

        Used by plugins when they have modified the transaction.
        """
        if self.transid:
            self._loadtrans(self.transid)

    def pagename(self):
        trans = self._gettrans()
        if trans:
            state = "closed" if trans.closed \
                    else "locked" if self.transaction_locked \
                         else "open"
            return f"{self.user.shortname} — Transaction {trans.id} ({state})"
        return self.user.shortname

    def _redraw(self):
        """Updates the screen, scrolling until the cursor is visible."""
        self.s.redraw()
        self.updateheader()

    def _redraw_note(self):
        trans = self._gettrans()
        note = trans.notes if trans else ""
        c = self.win.getyx()
        self.win.clear(0, 0, 1, self.w)
        self.win.drawstr(0, 0, self.w, note, colour=ui.colour_changeline)
        self.win.move(*c)

    def cursor_off(self):
        # Returns the cursor to the buffer line.  Does not redraw (because
        # the caller is almost certainly going to do other things first).
        self.s.cursor = len(self.dl)

    def update_balance(self):
        trans = self._gettrans()
        self.balance = trans.balance if trans else zero
        if self.balance < zero:
            self.current_refund_help_text = refund_help_text()
            for i in RegisterPlugin.instances:
                x = i.override_refund_help_text(self, trans)
                if x:
                    self.current_refund_help_text = x
                    break

    def close_if_balanced(self):
        trans = self._gettrans()
        if trans and not trans.closed \
           and (trans.lines or trans.payments) \
           and trans.total == trans.payments_total:
            # XXX check that there are no pending payments
            if self.hook("close_transaction", trans):
                return
            # Yes, it's balanced!
            trans.closed = True
            trans.discount_policy = None
            self.discount_policy = None
            self.balance = zero
            td.s.flush()
            self._clear_marks()
            # Check how long it has been since the register was
            # created — if it's under a few seconds, do not lock
            if self._autolock and time.time() - self._start_time >= 3.0:
                self.locked = True

    def linekey(self, kb):
        """A line key has been pressed.

        We are passed the keyboard binding.
        """
        # We may be being called back from a stocklinemenu here, so
        # repeat the entry() procedure to make sure we still have the
        # transaction.
        if not self.entry():
            return
        # Look up the modifier from the binding; it's an error if it's unknown
        mod = None
        if kb.modifier:
            if kb.modifier not in modifiers.all:
                log.error("Missing modifier '%s'", kb.modifier)
                ui.infopopup(
                    [f"The modifier '{kb.modifier}' can't be found.  This is "
                     f"a till configuration error."],
                    title="Missing modifier")
                return
            mod = modifiers.all[kb.modifier]

        if self.hook("linekey", kb, mod):
            return

        # Keyboard bindings can refer to a stockline, PLU or modifier
        if kb.stockline:
            self._sell_stockline(kb.stockline, mod)
        elif kb.plu:
            self._sell_plu(kb.plu, mod)
        else:
            self.mod = mod
            self.cursor_off()
            self._redraw()

    def barcode(self, scan):
        """A barcode has been scanned
        """
        if not scan.binding:
            if self.hook("unknown_barcode", scan):
                return
            ui.toast(f"Unrecognised barcode \"{scan.code}\"")
            scan.feedback(False)
            return

        scan.feedback(True)

        b = scan.binding

        # Look up the modifier from the barcode; it's an error if it's unknown
        mod = None
        if b.modifier:
            if b.modifier not in modifiers.all:
                log.error("Missing modifier '%s'", b.modifier)
                ui.infopopup(
                    [f"The modifer '{b.modifier}' needed by barcode "
                     f"\"{b}\" can't be found.  "
                     "This is a till configuration error."],
                    title="Missing modifier")
                return
            mod = modifiers.all[b.modifier]

        if self.hook("barcode", b, mod):
            return

        # Barcodes can refer to a stockline, PLU, stock type or modifier
        if b.stockline:
            self._sell_stockline(b.stockline, mod)
        elif b.plu:
            self._sell_plu(b.plu, mod)
        elif b.stocktype:
            self._sell_stocktype(b.stocktype, mod)
        else:
            self.mod = mod
            self.cursor_off()
            self._redraw()

    def transaction_lock_popup(self):
        """Pop up a message explaining that the current transaction is locked

        This function is part of the public API and may be used by
        plugins.
        """
        ui.infopopup(self.transaction_locked, title="Transaction locked")

    def _read_explicitprice(
            self, buf, department,
            permission_required="override-price"):
        """Code shared between sales made through stocklines and PLUs to check
        whether the user has entered a valid price override.
        """
        explicitprice = strtoamount(buf)
        if explicitprice == zero:
            ui.infopopup(
                [f"You can't override the price of an item to be zero.  "
                 f"You should use the {keyboard.K_WASTE} key instead "
                 f"to say why we're giving this item away."],
                title="Zero price not allowed")
            return
        if not self.user.may(permission_required):
            ui.infopopup(
                [f"You don't have permission to override the price of "
                 f"this item to {tillconfig.fc(explicitprice)}.  Did you "
                 f"mean to press the {keyboard.K_QUANTITY} key "
                 f"to enter a number of items instead?"],
                title="Permission required")
            return
        if department.minprice and explicitprice < department.minprice:
            ui.infopopup(
                [f"Your price of {tillconfig.fc(explicitprice)} per item "
                 f"is too low for {department.description}.  Did you mean "
                 f"to press the {keyboard.K_QUANTITY} key to enter "
                 f"a number of items instead?"],
                title="Price too low")
            return
        if department.maxprice and explicitprice > department.maxprice:
            ui.infopopup(
                [f"Your price of {tillconfig.fc(explicitprice)} per item "
                 f"is too high for {department.description}."],
                title="Price too high")
            return
        log.info("Register: manual price override to %s by %s",
                 explicitprice, self.user.fullname)
        return explicitprice

    @user.permission_required('sell-plu', 'Sell items using a price lookup')
    def _sell_plu(self, plu, mod):
        items = self.qty or 1
        mod = self.mod or mod  # self.mod is an override of the default
        buf = self.buf
        self.clearbuffer()
        self._redraw()

        # If we are repeating a PLU button press, we don't have to do
        # many of the usual checks.  If it's the same PLU again, just
        # increase the number of items
        may_repeat = hasattr(self.repeat, 'plu') \
            and self.repeat.plu == plu.id \
            and self.repeat.mod == mod

        trans = self.get_open_trans()  # Zaps self.repeat
        if not trans:
            return  # Will already be displaying an error.

        # Check for an explicit price
        explicitprice = None
        if buf:
            # If the PLU has no price set, it is treated as an
            # old-style department key and the permission required is
            # "sell-dept".
            if plu.price:
                explicitprice = self._read_explicitprice(buf, plu.department)
            else:
                explicitprice = self._read_explicitprice(
                    buf, plu.department, permission_required="sell-dept")
            if not explicitprice:
                return  # Error popup already in place

        # If we are dealing with a repeat press on the PLU line key, skip
        # all the remaining checks and just increase the number of items
        if may_repeat and len(self.dl) > 0 and \
           self.dl[-1].age() < max_transline_modify_age():
            otl = td.s.get(Transline, self.dl[-1].transline)
            new_items = otl.items + 1 if otl.items >= 0 else otl.items - 1
            if self.hook("sell_plu", trans, plu, new_items, otl):
                return
            otl.items = new_items
            self.dl[-1].update()
            td.s.flush()
            td.s.expire(trans, ['total'])
            self.update_balance()
            self.cursor_off()
            self._redraw()
            return

        # Create the proposed sale object
        sale = ProposedSale(description=plu.description, price=plu.price)

        sale.validate()

        # Pass the proposed sale to the modifier to let it change it
        # or reject it
        if mod:
            try:
                with ui.exception_guard(
                        f"running the '{mod.name}' modifier",
                        suppress_exception=False):
                    try:
                        mod.mod_plu(plu, sale)
                        sale.validate()
                    except modifiers.Incompatible as i:
                        msg = f"The '{mod.name}' modifier can't be used " \
                              f"with the '{plu.description}' price lookup."
                        ui.infopopup([i.msg if i.msg else msg],
                                     title="Incompatible modifier",
                                     colour=ui.colour_error)
                        return
                    except InvalidSale as i:
                        ui.infopopup(
                            [f"The '{mod.name}' modifier left the Proposed "
                             f"Sale object in an invalid state.  This is an "
                             f"error in the till configuration.  The "
                             f"invalid state is: {i.msg}"],
                            title="Till configuration error")
                        return
            except Exception:
                # ui.exception_guard() will already have popped up the error.
                return

        # If we have an explicit price, apply it now
        if explicitprice:
            sale.price = explicitprice

        # If we still don't have a price, we can't continue
        if sale.price is None:
            if self.user.may('sell-dept'):
                msg = f"'{plu.description}' doesn't have a price set.  You " \
                    "must enter a price before choosing the item."
            else:
                msg = "This item doesn't have a price set, and you don't " \
                    "have permission to override it.  You must ask your " \
                    "manager to set a price on the item before you can " \
                    "sell it."
                ui.infopopup([msg], title="Price not set")
            return

        # If the transaction is locked, we can't continue
        if self.transaction_locked:
            self.transaction_lock_popup()
            return

        # If sale.price is negative, make it positive and make the
        # number of items be negative instead
        if sale.price < zero:
            sale.price = -sale.price
            items = -items

        if self.hook("sell_plu", trans, plu, items, None):
            return

        tl = Transline(transaction=trans, items=items, amount=sale.price,
                       department=plu.department, user=self.user.dbuser,
                       transcode='S', text=sale.description,
                       source=tillconfig.terminal_name)
        td.s.add(tl)
        self._apply_discount(tl)
        td.s.flush()
        if explicitprice and plu.price:
            user.log(f"Price override on {plu.logref} to "
                     f"{tillconfig.fc(sale.price)} for transaction "
                     f"line {tl.logref}")
        td.s.refresh(tl, ['time'])  # load time from database
        self.dl.append(tline(tl.id))
        self.repeat = repeatinfo(plu=plu.id, mod=mod)
        td.s.expire(trans, ['total'])
        self._clear_marks()
        self.update_balance()
        self.cursor_off()
        self.prompt = self.defaultprompt
        self._redraw()

    @user.permission_required('sell-stocktype', 'Sell a type of stock')
    def _sell_stocktype(self, stocktype, mod):
        st = stocktype
        mod = self.mod or mod  # self.mod is an override of the default
        items = self.qty or 1

        # Cache the bufferline contents, clear it and redraw - this
        # saves us having to do so explicitly when we bail with an
        # error
        buf = self.buf
        self.clearbuffer()
        self._redraw()

        sale = ProposedSale(
            stocktype=st,
            qty=st.unit.base_units_per_sale_unit,
            description=f"{st} {st.unit.sale_unit_name}",
            price=st.saleprice,
            whole_items=False)

        sale.validate()

        # Pass the proposed sale to the modifier to let it change it
        # or reject it
        if mod:
            try:
                with ui.exception_guard(
                        f"running the '{mod.name}' modifier",
                        suppress_exception=False):
                    try:
                        mod.mod_stocktype(st, sale)
                        sale.validate()
                    except modifiers.Incompatible as i:
                        msg = f"The '{mod.name}' modifier can't be used " \
                            f"with the '{st}' stock type."
                        ui.infopopup([i.msg if i.msg else msg],
                                     title="Incompatible modifier",
                                     colour=ui.colour_error)
                        return
                    except InvalidSale as i:
                        ui.infopopup(
                            [f"The '{mod.name}' modifier left the Proposed "
                             f"Sale object in an invalid state.  This is an "
                             f"error in the till configuration.  The invalid "
                             f"state is: {i.msg}"],
                            title="Till configuration error")
                        return
            except Exception:
                # ui.exception_guard() will already have popped up the error.
                return

        explicitprice = None
        if buf:
            explicitprice = self._read_explicitprice(
                buf, sale.stocktype.department)
            if not explicitprice:
                return  # Error popup already in place

        if not explicitprice:
            if sale.price is None:
                no_saleprice_popup(self.user, sale.stocktype)
                return

        if explicitprice:
            sale.price = explicitprice

        if sale.price < zero:
            log.info("_sell_stocktype: negative price for %s", st.format())
            ui.infopopup(
                [f"{st} has a negative sale price, which is not "
                 f"currently supported."],
                title=f"{st} has negative price")
            return

        total_qty = items * sale.qty
        sell, unallocated, remaining = st.calculate_sale(total_qty)

        if unallocated > 0 or len(sell) == 0:
            log.info("_sell_stocktype: no stock present for %s", st.format())
            ui.infopopup(
                [f"No {st} is available to sell.", "",
                 "Hint: stock already attached to a stock line can only "
                 "be sold through that stock line."],
                title=f"{st} is not in stock")
            return

        # NB get_open_trans() may call _clear() and will zap self.repeat when
        # it creates a new transaction!
        may_repeat = self.repeat and hasattr(self.repeat, 'stocktype_id') \
            and self.repeat.stocktype_id == st.id \
            and self.repeat.mod == mod

        trans = self.get_open_trans()
        if trans is None:
            return  # Will already be displaying an error.

        # If the transaction is locked, we can't continue
        if self.transaction_locked:
            self.transaction_lock_popup()
            return

        # Consider adding on to the previous transaction line if the
        # same stocktype key/barcode has been pressed again.
        repeated = False
        if may_repeat and len(self.dl) > 0 \
           and self.dl[-1].age() < max_transline_modify_age() \
           and len(sell) == 1:
            otl = td.s.get(Transline, self.dl[-1].transline)
            # If the stockref has more than one item, we don't repeat
            # because we are probably at the changeover between two
            # stockitems
            if otl.stockref \
               and otl.stockref[0].stockitem == sell[0][0] \
               and len(otl.stockref) == 1:
                # It's the same stockitem.  Add one item and one qty.
                so = otl.stockref[0]
                orig_stockqty = so.qty / otl.items
                if orig_stockqty == sell[0][1] \
                   and (so.qty + orig_stockqty) < max_quantity:
                    so.qty += orig_stockqty
                    otl.items += 1
                    td.s.flush()
                    td.s.expire(so.stockitem, ['used', 'sold', 'remaining'])
                    log.info("linekey: updated transline %d and stockout %d",
                             otl.id, otl.stockref[0].id)
                    self.dl[-1].update()
                    repeated = True

        if not repeated:
            # Check that the number of items to be sold fits within the
            # qty field of StockOut
            for stockitem, items_to_sell in sell:
                if items_to_sell > max_quantity:
                    unit = stockitem.stocktype.unit
                    ui.infopopup(
                        [f"You can't sell "
                         f"{unit.format_sale_qty(items_to_sell)}"
                         f" of {stockitem.stocktype} in one go."],
                        title="Error")
                    return
            tl = Transline(
                transaction=trans, items=items,
                amount=sale.price,
                department=sale.stocktype.department,
                transcode='S', text=sale.description,
                user=self.user.dbuser,
                source=tillconfig.terminal_name)
            td.s.add(tl)
            for stockitem, items_to_sell in sell:
                so = StockOut(
                    transline=tl, stockitem=stockitem,
                    qty=items_to_sell, removecode_id=sold_removecode_id())
                td.s.add(so)
                td.s.expire(
                    stockitem,
                    ['used', 'sold', 'remaining', 'firstsale', 'lastsale'])
            self._apply_discount(tl)
            td.s.flush()
            if explicitprice:
                logmsg = f"Price override to {tillconfig.fc(sale.price)} " \
                    f"for transaction line {tl.logref} stock item "
                for stockitem, items_to_sell in sell:
                    user.log(logmsg + stockitem.logref)
            td.s.refresh(tl, ['time'])  # load time from database
            self.dl.append(tline(tl.id))

        self.repeat = repeatinfo(stocktype_id=st.id, mod=mod)

        self.prompt = f"{st}: {st.unit.format_stock_qty(remaining)} remaining"
        if remaining < Decimal("0.0"):
            ui.infopopup([
                f"There appears to be {st.unit.format_stock_qty(remaining)} "
                f"of {st} left!  Record a delivery or perform a stock take "
                f"to fix this."],
                title="Warning", dismiss=keyboard.K_USESTOCK)

        # Adding and altering translines changes the total
        td.s.expire(trans, ['total'])
        self._clear_marks()
        self.update_balance()
        self.cursor_off()
        self._redraw()

    @user.permission_required('sell-stock', 'Sell stock from a stockline')
    def _sell_stockline(self, stockline, mod):
        mod = self.mod or mod  # self.mod is an override of the default
        items = self.qty or 1

        # Cache the bufferline contents, clear it and redraw - this
        # saves us having to do so explicitly when we bail with an
        # error
        buf = self.buf
        self.clearbuffer()
        self._redraw()

        st = stockline.sale_stocktype
        # A regular stockline with no stock won't be able to give us a
        # stocktype.  Bail early in this case with a suitable error.
        # Note that we may have to pop up the same error later on if
        # we discover there's no stock on a display stockline.
        if not st:
            log.info("linekey: no stock in use for %s", stockline.name)
            ui.infopopup(
                [f"No stock is registered for {stockline.name}.",
                 f"To tell the till about stock on sale, "
                 f"press the '{keyboard.K_USESTOCK}' button after "
                 f"dismissing this message."],
                title=f"{stockline.name} has no stock")
            return
        sale = ProposedSale(
            stocktype=st,
            qty=st.unit.base_units_per_sale_unit,
            description=f"{st} {st.unit.sale_unit_name}",
            price=st.saleprice,
            whole_items=(stockline.linetype == "display"))

        sale.validate()

        # Pass the proposed sale to the modifier to let it change it
        # or reject it
        if mod:
            try:
                with ui.exception_guard(
                        f"running the '{mod.name}' modifier",
                        suppress_exception=False):
                    try:
                        mod.mod_stockline(stockline, sale)
                        sale.validate()
                    except modifiers.Incompatible as i:
                        msg = f"The '{mod.name}' modifier can't be used " \
                            f"with the '{stockline.name}' stockline."
                        ui.infopopup([i.msg if i.msg else msg],
                                     title="Incompatible modifier",
                                     colour=ui.colour_error)
                        return
                    except InvalidSale as i:
                        ui.infopopup(
                            [f"The '{mod.name}' modifier left the Proposed "
                             f"Sale object in an invalid state.  This is "
                             f"an error in the till configuration.  The "
                             f"invalid state is: {i.msg}"],
                            title="Till configuration error")
                        return
            except Exception:
                # ui.exception_guard() will already have popped up the error.
                return

        explicitprice = None
        if buf:
            explicitprice = self._read_explicitprice(
                buf, sale.stocktype.department)
            if not explicitprice:
                return  # Error popup already in place

        if not explicitprice:
            if sale.price is None:
                no_saleprice_popup(self.user, sale.stocktype)
                return

        if explicitprice:
            sale.price = explicitprice

        if sale.price < zero:
            log.info("_sell_stockline: negative price for %s",
                     sale.stocktype.format())
            ui.infopopup(
                [f"{sale.stocktype} has a negative sale price, which is not "
                 f"currently supported."],
                title=f"{sale.stocktype} has negative price")
            return

        total_qty = items * sale.qty
        sell, unallocated, remaining = stockline.calculate_sale(
            total_qty)

        # This _should_ only be the case with display stocklines.
        if unallocated > 0:
            ui.infopopup(
                [f"There are fewer than {total_qty} items of "
                 f"{stockline.name} on display.  "
                 f"If you have recently put more stock on display you "
                 f"must tell the till about it using the 'Use Stock' "
                 f"button after dismissing this message."],
                title="Not enough stock on display")
            return
        if len(sell) == 0:
            log.info("linekey: no stock in use for %s", stockline.name)
            ui.infopopup(
                [f"No stock is registered for {stockline.name}.",
                 f"To tell the till about stock on sale, "
                 f"press the '{keyboard.K_USESTOCK}' button after "
                 f"dismissing this message."],
                title=f"{stockline.name} has no stock")
            return

        # NB get_open_trans() may call _clear() and will zap self.repeat when
        # it creates a new transaction!
        may_repeat = self.repeat and hasattr(self.repeat, 'stocklineid') \
            and self.repeat.stocklineid == stockline.id \
            and self.repeat.mod == mod

        trans = self.get_open_trans()
        if trans is None:
            return  # Will already be displaying an error.

        # If the transaction is locked, we can't continue
        if self.transaction_locked:
            self.transaction_lock_popup()
            return

        # Consider adding on to the previous transaction line if the
        # same stockline key has been pressed again.
        repeated = False
        if may_repeat and len(self.dl) > 0 \
           and self.dl[-1].age() < max_transline_modify_age() \
           and len(sell) == 1:
            otl = td.s.get(Transline, self.dl[-1].transline)
            # If the stockref has more than one item, we don't repeat
            # because we are probably at the changeover between two
            # stockitems
            if otl.stockref \
               and otl.stockref[0].stockitem == sell[0][0] \
               and len(otl.stockref) == 1:
                # It's the same stockitem.  Add one item and one qty.
                so = otl.stockref[0]
                orig_stockqty = so.qty / otl.items
                if orig_stockqty == sell[0][1] \
                   and (so.qty + orig_stockqty) < max_quantity:
                    so.qty += orig_stockqty
                    otl.items += 1
                    td.s.flush()
                    td.s.expire(so.stockitem, ['used', 'sold', 'remaining'])
                    log.info("linekey: updated transline %d and stockout %d",
                             otl.id, otl.stockref[0].id)
                    self.dl[-1].update()
                    repeated = True

        if stockline.linetype == "regular" and stockline.pullthru:
            # Check first to see whether we may need to record a
            # pullthrough; the lastsale time will change once we start
            # committing StockOut objects to the database.
            item = sell[0][0]
            if td.stock_checkpullthru(item.id, '11:00:00'):
                unit = item.stocktype.unit
                ui.infopopup(
                    [f"According to the till records, {item.stocktype} "
                     f"hasn't been sold or pulled through in the last "
                     f"11 hours.  Would you like to record that you've "
                     f"pulled through "
                     f"{unit.format_sale_qty(stockline.pullthru)}?",
                     "",
                     f"Press '{keyboard.K_WASTE}' if you do, or "
                     f"{keyboard.K_CLEAR} if you don't."],
                    title="Pull through?", colour=ui.colour_input,
                    keymap={
                        keyboard.K_WASTE:
                        (record_pullthru, (item.id, stockline.pullthru),
                         True)})

        if not repeated:
            # Check that the number of items to be sold fits within the
            # qty field of StockOut
            for stockitem, items_to_sell in sell:
                if items_to_sell > max_quantity:
                    ui.infopopup(
                        [f"You can't sell {items_to_sell} "
                         f"{stockitem.stocktype.unit.name}s of "
                         f"{stockitem.stocktype} in one go."],
                        title="Error")
                    return
            tl = Transline(
                transaction=trans, items=items,
                amount=sale.price,
                department=sale.stocktype.department,
                transcode='S', text=sale.description,
                user=self.user.dbuser,
                source=tillconfig.terminal_name)
            td.s.add(tl)
            for stockitem, items_to_sell in sell:
                so = StockOut(
                    transline=tl, stockitem=stockitem,
                    qty=items_to_sell, removecode_id=sold_removecode_id())
                td.s.add(so)
                td.s.expire(
                    stockitem,
                    ['used', 'sold', 'remaining', 'firstsale', 'lastsale'])
            self._apply_discount(tl)
            td.s.flush()
            if explicitprice:
                logmsg = f"Price override to {tillconfig.fc(sale.price)} " \
                    f"for transaction line {tl.logref} stock item "
                for stockitem, items_to_sell in sell:
                    user.log(logmsg + stockitem.logref)
            td.s.refresh(tl, ['time'])  # load time from database
            self.dl.append(tline(tl.id))

        self.repeat = repeatinfo(stocklineid=stockline.id, mod=mod)

        if stockline.linetype == "regular":
            # We are using the last value of so from either the
            # previous for loop, or the handling of may_repeat
            stockitem = so.stockitem
            unit = stockitem.stocktype.unit
            self.prompt = f"{stockline.name}: "\
                f"{unit.format_stock_qty(stockitem.remaining)} "\
                f"of {stockitem.stocktype} remaining"
            if stockitem.remaining < Decimal("0.0"):
                user.log(f"Negative stock level on {stockline.logref}: "
                         f"Item {stockitem.logref} has "
                         f"{unit.format_stock_qty(stockitem.remaining)} "
                         f"remaining")
                ui.infopopup(
                    ["There appears to be {} of {} left!  Please "
                     "check that you're still using stock item {}; if you've "
                     "started using a new item, tell the till about it "
                     "using the '{}' button after dismissing this "
                     "message.".format(
                         unit.format_stock_qty(stockitem.remaining),
                         stockitem.stocktype,
                         stockitem.id,
                         keyboard.K_USESTOCK),
                     "", "If you don't understand this message, you MUST "
                     "call your manager to deal with it."],
                    title="Warning", dismiss=keyboard.K_USESTOCK)
        elif stockline.linetype == "display":
            self.prompt = "{}: {} left on display; {} in stock".format(
                stockline.name, int(remaining[0]), int(remaining[1]))
        elif stockline.linetype == "continuous":
            self.prompt = "{}: {} of {} remaining".format(
                stockline.name, stockline.stocktype.unit.format_stock_qty(
                    remaining),
                stockline.stocktype)
            if remaining < Decimal("0.0"):
                user.log(
                    f"Negative stock level on {stockline.logref}: "
                    f"{stockline.stocktype.unit.format_stock_qty(remaining)} "
                    f"of {stockline.stocktype.logref} remaining")
                ui.infopopup(
                    ["There appears to be {} of {} left!  Please "
                     "check that you're still using {}; if you've "
                     "started using a new type of stock, tell the till "
                     "about it by changing the stock type of the "
                     "'{}' stock line after dismissing this message.".format(
                         stockline.stocktype.unit.format_stock_qty(remaining),
                         stockline.stocktype,
                         stockline.stocktype,
                         stockline.name),
                     "", "If you don't understand this message, you MUST "
                     "call your manager to deal with it."],
                    title="Warning", dismiss=keyboard.K_USESTOCK)

        # Adding and altering translines changes the total
        td.s.expire(trans, ['total'])
        self._clear_marks()
        self.update_balance()
        self.cursor_off()
        self._redraw()

    def deptlines(self, lines):
        """Accept multiple transaction lines from a plugin.

        lines is a list of (dept, text, items, amount) tuples.

        Returns True on success; on failure, returns an error message
        as a string or None if it was a self.entry() error that will
        already have popped up a message.
        """
        if not self.entry():
            return
        self.prompt = self.defaultprompt
        self._clear_marks()
        self.clearbuffer()
        trans = self.get_open_trans()
        if trans is None:
            return "Transaction cannot be started."

        # If the transaction is locked, we can't continue
        if self.transaction_locked:
            return "Transaction is locked"

        for dept, text, items, amount in lines:
            tl = Transline(transaction=trans,
                           department=td.s.get(Department, dept),
                           items=items, amount=amount,
                           transcode='S', text=text, user=self.user.dbuser,
                           source=tillconfig.terminal_name)
            td.s.add(tl)
            self._apply_discount(tl)
            td.s.flush()
            log.info("Register: deptlines: trans=%d,lid=%d,dept=%d,"
                     "price=%f,text=%s", trans.id, tl.id, dept, amount, text)
            self.dl.append(tline(tl.id))
        self.repeat = None
        self.cursor_off()
        td.s.expire(trans, ['total'])
        self.update_balance()
        self._redraw()
        return True

    def get_open_trans(self):
        """Return an open transaction if possible

        If the current transaction is still open, returns it.  If it
        is closed, or there is no current transaction, attempts to
        start a new transaction.  If this is not possible, returns
        None after popping up an error message.
        """
        trans = self._gettrans()
        if trans and not trans.closed:
            return trans
        # Transaction is closed or absent
        self._clear()
        session = Session.current(td.s)
        if session is None:
            log.info("Register: get_open_trans: no session active")
            self._redraw()
            ui.infopopup(["No session is active.",
                          "You must use the Management menu "
                          "to start a session before you "
                          "can sell anything."],
                         title="Error")
            return
        trans = Transaction(session=session)
        td.s.add(trans)
        self.user.dbuser.transaction = trans
        td.s.flush()
        self.transid = trans.id
        self._redraw()
        return trans

    @user.permission_required('drink-in', 'Use the "Drink In" function')
    def drinkinkey(self):
        """The user pressed the 'Drink In' key.

        The 'Drink In' key creates a negative entry in the
        transaction's payments section using its configured payment
        method; the intent is that staff who are offered a drink that
        they don't want to pour immediately can use this key to enable
        the till to add the cost of their drink onto a transaction.
        They can take the money from the till tray or make a note that
        it's in there, and use it later to buy a drink.

        This only works if the configured payment method supports change.
        """
        if self.qty or self.mod:
            ui.infopopup(["You can't enter a quantity or use a modifier key "
                          "before pressing 'Drink In'."], title="Error")
            return
        if not self.buf:
            ui.infopopup(["You must enter an amount before pressing the "
                          "'Drink In' button."], title="Error")
            return
        amount = strtoamount(self.buf)
        trans = self._gettrans()
        if trans is None or trans.closed:
            ui.infopopup(["A Drink 'In' can't be the only item in a "
                          "transaction; it must be added to a transaction "
                          "that is already open."], title="Error")
            return
        self.clearbuffer()
        if self.hook("drinkin", trans, amount):
            return

        pm = td.s.get(PayType, drinkin_payment_method())

        if not pm:
            self._redraw()
            ui.infopopup(["There is no Drink 'In' payment method configured."],
                         title="Error")
            return
        if not pm.active:
            self._redraw()
            ui.infopopup([f"The {pm.description} payment method is not "
                          f"active."], title="Error")
            return
        if not pm.driver.add_payment_supported:
            self._redraw()
            ui.infopopup([f"The {pm.description} payment method doesn't "
                          "support change."], title="Error")
            return
        p = pm.driver.add_payment(
            trans, description="Drink 'In'", amount=-amount)
        self.dl.append(p)
        self._clear_marks()
        self.cursor_off()
        self.update_balance()
        self._redraw()

    def cashkey(self):
        """The CASH/ENTER key was pressed.

        The CASH/ENTER key is used to complete the "no sale" action as
        well as potentially as a payment method key.  It's also used
        to cancel an empty open transaction.
        """
        if self.qty is not None:
            log.info("Register: cash/enter with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before pressing "
                          "Cash/Enter.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        trans = self._gettrans()
        if trans is None or trans.closed:
            if not self.buf:
                log.info("Register: cashkey: NO SALE")
                if self.user.may('nosale'):
                    if self.hook("nosale"):
                        return
                    if tillconfig.cash_drawer:
                        if printer.kickout(tillconfig.cash_drawer):
                            ui.toast("No Sale has been recorded.")
                            # Finally!  We're not lying any more!
                            user.log("No Sale")
                    else:
                        ui.toast("No Sale")
                    if lock_after_nosale():
                        self.locked = True
                        self._redraw()
                else:
                    ui.infopopup(["You don't have permission to use "
                                  "the No Sale function."], title="No Sale")
                return
            log.info("Register: cashkey: current transaction is closed")
            ui.infopopup(["There is no transaction in progress.  If you "
                          "want to perform a 'No Sale' transaction then "
                          "try again without entering an amount."],
                         title="Error")
            self.clearbuffer()
            self._redraw()
            return
        if len(trans.lines) == 0 and len(trans.payments) == 0:
            # Special case: cash key on an empty transaction.
            # Just cancel the transaction silently.
            if self.hook("cancelempty", trans):
                return
            td.s.delete(trans)
            self.transid = None
            td.s.flush()
            self._clear()
            self._redraw()
            return

        if self.hook("cashkey", trans):
            return

        if self._resume_pending_payment():
            return

        # If the balance is zero, there are no marked lines, and the
        # input buffer is empty, then just close the transaction — the
        # most likely case is that all the transaction lines have
        # matching void lines, and payments have matching
        # refunds. This saves us from potentially popping up the
        # payment methods menu, only for the user to have to make a
        # redundant choice.
        if self.balance == zero and not self.buf and not self.ml:
            log.info("Register: cashkey: transaction already balanced, closing")
            self.close_if_balanced()
            self.cursor_off()
            self._redraw()
            ui.toast("Transaction closed: nothing to pay")
            return

        # We now consider using the configured default payment method.
        pm = td.s.get(PayType, default_payment_method())
        if pm and not pm.active:
            pm = None

        # If the transaction is an old one (i.e. the "recall
        # transaction" function has been used on it) then require
        # confirmation - one of the most common user errors is to
        # recall a transaction that's being used as a tab, add some
        # lines to it, and then automatically press 'cash'.
        #
        # We do this by opening the payment methods menu.
        if self.keyguard or not pm:
            self._payment_method_menu(
                title="Choose payment method for this transaction")
            return

        self.paymentkey(pm.paytype)

    def _payment_method_menu(self, title="Payment methods"):
        ui.automenu(
            [(m.description, self.paymentkey, (m.paytype,))
             for m in td.s.query(PayType)
             .filter(PayType.mode == 'active')
             .order_by(PayType.order, PayType.paytype)
             .all()],
            title=title, spill="keymenu")

    @user.permission_required("take-payment", "Take a payment")
    def paymentkey(self, paytype_id):
        """Deal with a payment.

        Deal with a keypress that might be a payment key.  We might be
        entered directly rather than through our keypress method, so
        refresh the transaction first.
        """
        # UI sanity checks first
        if self.qty is not None:
            log.info("Register: paymentkey: payment with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.mod is not None:
            log.info("Register: paymentkey: payment with modifier not allowed")
            ui.infopopup(["You can't press a modifier key before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if not self.entry():
            return
        trans = self._gettrans()
        if trans is None or trans.closed:
            log.info("Register: paymentkey: closed or no transaction")
            ui.infopopup(["There is no transaction in progress."],
                         title="Error")
            self.clearbuffer()
            self._redraw()
            return
        paytype = td.s.get(PayType, paytype_id)
        if not paytype:
            log.info("Register: paymentkey: missing payment method")
            ui.infopopup(["This payment method does not exist."], title="Error")
            return
        if paytype.mode != "active":
            log.info("Register: paymentkey: inactive payment method")
            ui.infopopup([f"This payment method is not active. Its mode "
                          f"is '{paytype.mode}'."], title="Error")
            return
        if not paytype.driver.config_valid:
            log.info("Register: paymentkey: payment method invalid config")
            ui.infopopup(["This payment method is not configured correctly.",
                          "",
                          f"The problem is: {paytype.driver.config_problem}"],
                         title="Error")
            self.clearbuffer()
            self._redraw()
            return
        if self.hook("paymentkey", paytype, trans):
            return
        self.prompt = self.defaultprompt
        self.balance = trans.balance
        if self.buf:
            amount = strtoamount(self.buf)
            if self.balance < zero:
                amount = zero - amount  # refund amount
        elif self.ml:
            log.info("Register: paymentkey: amount from marked lines")
            amount = self._total_value_of_marked_translines()
            self._clear_marks()
        else:
            # Exact amount
            log.info("Register: paymentkey: exact amount")
            amount = self.balance
        self.clearbuffer()
        self._redraw()
        if amount == zero:
            log.info("Register: paymentkey: payment of zero")
            # A transaction that has been completely voided will have
            # a balance of zero.  Simply close it here rather than
            # attempting a zero payment.
            if self.balance == zero:
                self.close_if_balanced()
                self.cursor_off()
                self._redraw()
                return
            ui.infopopup([f"You can't pay {tillconfig.fc(zero)}!",
                          'If you meant "exact amount" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'], title="Error")
            return
        # We have a non-zero amount and we're happy to proceed.  Pass
        # to the payment method.
        if self.hook("start_payment", paytype, trans, amount, self.balance):
            return
        paytype.driver.start_payment(self, trans.id, amount, self.balance)

    # XXX the add_payments / payments_update API isn't sufficient for
    # Square Terminal, where a single pending payment may become
    # multiple completed payments. Reconsider this!

    def add_payments(self, transid, payments):
        """Payments have been added to a transaction.

        Called by a payment method when payments have been added to a
        transaction.  NB it might not be the current transaction if
        the payment method completed in the background!  Multiple
        payments might have been added, eg. for change.
        """
        if not self.entry():
            return
        if transid != self.transid:
            return
        for p in payments:
            self.dl.append(p)
        self.close_if_balanced()
        self.update_balance()
        self.cursor_off()
        self._redraw()

    def payments_update(self):
        """Called by a payment method when payments have been updated."""
        if not self.entry():
            return
        trans = self._gettrans()
        if not trans or trans.closed:
            return
        # Expire the transaction because the wrong balance may have
        # been cached.
        td.s.expire(trans)
        # Update all the payment lines in our display list
        for d in self.dl:
            if isinstance(d, payment.pline):
                d.update()
        self.update_balance()
        self.close_if_balanced()
        self.cursor_off()
        self._redraw()

    def _resume_pending_payment(self):
        """Check for any pending payments and resume one of them if present

        Returns True if a payment was resumed
        """
        trans = self._gettrans()
        if not trans or trans.closed:
            return

        pending_payments = [p for p in self.dl if isinstance(p, payment.pline)
                            and p.pending]
        if pending_payments:
            p = td.s.get(Payment, pending_payments[0].payment_id,
                         options=[joinedload(Payment.meta)])
            p.paytype.driver.resume_payment(self, p)
            return True
        return False

    def notekey(self, k):
        if self.qty is not None or self.buf:
            log.info("Register: notekey: error popup")
            ui.infopopup(["You can only press a note key when you "
                          "haven't already entered a quantity or amount.",
                          "After dismissing this message, press Clear "
                          "and try again."], title="Error")
            return
        self.buf = str(k.notevalue)
        log.info("Register: notekey %s", k.notevalue)
        return self.paymentkey(k.paymentmethod)

    def numkey(self, n):
        """A number key was pressed."""
        trans = self._gettrans()
        if not self.buf and self.qty == None and trans and trans.closed:
            log.info("Register: numkey on closed transaction; "
                     "clearing display")
            self._clear()
        self.cursor_off()
        if len(self.buf) >= 10:
            self.clearkey()
            log.info("Register: numkey: buffer overflow")
            ui.infopopup(["Numerical values entered here can be at most "
                          "ten digits long.  Please try again."],
                         title="Error")
        else:
            self.buf = self.buf + n
            # Remove leading zeros
            while len(self.buf) > 0 and self.buf[0] == '0':
                self.buf = self.buf[1:]
            if len(self.buf) == 0:
                self.buf = '0'
            # Insert a leading zero if first character is a point
            if self.buf[0] == '.':
                self.buf = "0" + self.buf
            # Check that there's no more than one point
            if self.buf.count('.') > 1:
                log.info("Register: numkey: multiple points")
                ui.infopopup(["You can't have more than one point in "
                              "a number!  Please try again."],
                             title="Error")
                self.buf = ""
            self._redraw()

    def quantkey(self):
        """The Quantity key was pressed."""
        if self.qty is not None:
            log.info("Register: quantkey: already entered")
            ui.infopopup(["You have already entered a quantity.  If "
                          "you want to change it, press Clear after "
                          "dismissing this message."], title="Error")
            return
        if not self.buf:
            q = 0
        else:
            if self.buf.find('.') > 0:
                q = 0
            else:
                q = int(self.buf)
        self.buf = ""
        if q > 0:
            self.qty = q
        else:
            log.info("Register: quantkey: whole number required")
            ui.infopopup(["You must enter a whole number greater than "
                          "zero before pressing Quantity."],
                         title="Error")
        self.cursor_off()
        self._redraw()

    def clearkey(self):
        """The Clear key was pressed."""
        trans = self._gettrans()
        if not self.buf and self.qty == None and trans and trans.closed:
            log.info("Register: clearkey on closed transaction; "
                     "clearing display")
            self._clear()
        else:
            log.info("Register: clearkey on open or null transaction; "
                     "clearing buffer or marks")
            if self.buf or self.qty or self.mod:
                self.clearbuffer()
            elif self.ml:
                self._clear_marks()
            self.cursor_off()
        self._redraw()

    @user.permission_required("print-receipt", "Print a receipt")
    def printkey(self):
        trans = self._gettrans()
        if self.hook("printkey", trans):
            return
        if not trans:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key, or print any transaction "
                          "if you have its number using the option under "
                          "'Manage Till'."], title="Error")
            return
        if not tillconfig.receipt_printer:
            ui.infopopup(["This till does not have a receipt printer."],
                         title="Error")
            return
        log.info("Register: printing transaction %d", trans.id)
        user.log(f"Printed {trans.state} transaction {trans.logref} "
                 f"from register")
        ui.toast("The receipt is being printed.")
        with ui.exception_guard("printing the receipt", title="Printer error"):
            printer.print_receipt(tillconfig.receipt_printer, trans.id)

    def cancelkey(self):
        """The cancel key was pressed.

        This does different things depending on context:

        On a blank page, pops up help about the key

        When marked lines are present, attempts to cancel/void the
        marked lines

        When no line is selected and no marked lines are present,
        attempts to cancel/void the whole transaction

        When a line is selected and no marked lines are present,
        attempts to cancel/void the selected line only (on an open
        transaction only; on a closed transaction pops up info telling
        the user to mark relevant lines first)
        """
        trans = self._gettrans()
        if not trans:
            log.info("Register: cancelkey help message")
            ui.infopopup(
                ["The Cancel key is used for cancelling whole transactions, "
                 "and also for cancelling individual lines in a transaction.",
                 "",
                 "To cancel a whole transaction, just press Cancel.",
                 "",
                 "To cancel individual lines, use the Up and Down keys "
                 "and the Mark key to mark the lines and then press Cancel.",
                 "",
                 "Lines cancelled from a transaction that's still open are "
                 "reversed immediately.",
                 "",
                 "If you are viewing a transaction that has already been "
                 "closed, a new 'void' transaction will be created reversing "
                 "the lines from the closed transaction."],
                title="Help on Cancel",
                colour=ui.colour_info)
            return
        if self.hook("cancelkey", trans):
            return
        closed = trans.closed
        if closed and not self.user.may("void-from-closed-transaction"):
            ui.infopopup(
                ["You don't have permission to void lines from a closed "
                 "transaction."],
                title="Not allowed")
            return
        if not closed and not self.user.may("cancel-line-in-open-transaction"):
            ui.infopopup(
                ["You don't have permission to cancel lines in an open "
                 "transaction, or to delete the whole transaction."],
                title="Not allowed")
            return
        if self.ml:
            ui.infopopup(
                ["Press Cash/Enter to void the marked lines."],
                title="Cancel Marked Lines",
                colour=ui.colour_confirm,
                keymap={
                    keyboard.K_CASH: (self.cancelmarked, None, True)})
            return
        if self.s.cursor >= len(self.dl):
            # The user has not indicated a particular line to cancel.
            # Try to cancel the whole transaction.
            if not closed \
               and (self.keyguard or  # noqa: W504
                    (len(self.dl) > 0 and  # noqa: W504
                     self.dl[0].age() > max_transline_modify_age())):
                log.info("Register: cancelkey kill transaction denied")
                ui.infopopup(
                    ["This transaction is old; you can't cancel it all in "
                     "one go.  Cancel each line separately instead."],
                    title="Cancel Transaction")
                return
            # If there are any pending or non-zero payments, the
            # transaction can't be cancelled.
            if not closed and any(
                    p.pending or p.amount != zero for p in trans.payments):
                ui.infopopup(
                    ["This transaction has (possibly pending) payments, and "
                     "so can't be cancelled. Void lines and then issue a "
                     "refund as required."],
                    title="Cancel Transaction")
                return
            log.info("Register: cancelkey confirm kill "
                     "transaction %d", trans.id)
            ui.infopopup(
                [f"Are you sure you want to {('cancel', 'void')[closed]} all "
                 f"of transaction number {trans.id}?  Press Cash/Enter "
                 f"to confirm, or Clear to go back."],
                title="Confirm Transaction Cancel",
                colour=ui.colour_confirm,
                keymap={
                    keyboard.K_CASH: (self.canceltrans, None, True)})
            return
        # The cursor is on a line.
        if closed:
            ui.infopopup(
                ["Select the lines to void from this transaction by "
                 "using Up/Down and the Mark key, then press Cancel "
                 "again to void them."],
                title="Help on voiding lines from closed transactions",
                colour=ui.colour_info)
            return
        l = self.dl[self.s.cursor]
        if isinstance(l, tline) and not l.voided:
            log.info("Register: cancelline: confirm cancel")
            ui.infopopup(["Are you sure you want to cancel this line? "
                          "Press Cash/Enter to confirm."],
                         title="Confirm Cancel",
                         colour=ui.colour_confirm,
                         keymap={
                             keyboard.K_CASH: (self.cancelline, (l,), True)})
        elif isinstance(l, tline) and l.voided:
            ui.infopopup(["This line has already been voided.  You can't "
                          "cancel it unless you cancel the line that voids "
                          "it first."],
                         title="Line already voided")
        else:
            # It must be a pline. The transaction is definitely still
            # open at this point. Cancel the payment if the payment
            # type supports it.  (A permission check may be carried
            # out by the cancel_payment() method of the payment
            # method; if it fails, we assume an error box will have
            # been popped up.)
            log.info("Register: cancelline: cancel payment")
            p = td.s.get(Payment, l.payment_id)
            if p.paytype.driver.cancel_supported:
                p.paytype.driver.cancel_payment(self, l)
                self.cursor_off()
            else:
                ui.infopopup(["You can't cancel this type of payment.  "
                              "Cancel the whole transaction instead."],
                             title="Cancel")

    def cancelmarked(self):
        """Cancel marked lines from a transaction.

        The transaction may be open or closed; if it is open then
        delete or void the lines; if it is closed then create a new
        transaction voiding the marked lines.

        We repeat the permission checks here because we may be called
        from the Manage Transaction menu as well as from the cancel
        key code.
        """
        if not self.entry():
            return
        tl = list(self.ml)
        trans = self._gettrans()
        if self.hook("cancelmarked", trans):
            return
        if trans.closed:
            if not self.user.may("void-from-closed-transaction"):
                ui.infopopup(
                    ["You don't have permission to void lines from a closed "
                     "transaction."],
                    title="Not allowed")
                return
            self._clear()
            trans = self.get_open_trans()
            if not trans:
                return
            log.info("Register: cancelmarked %s; new trans=%d",
                     str(tl), trans.id)
            self._void_lines(tl)
            self.cursor_off()
            self.update_balance()
            self._redraw()
            if payment_method_menu_after_void():
                self._payment_method_menu(
                    title="Choose refund type, or press Clear "
                    "to add more items")
        else:
            if not self.user.may("cancel-line-in-open-transaction"):
                ui.infopopup(
                    ["You don't have permission to cancel lines in an open "
                     "transaction."],
                    title="Not allowed")
                return
            can_delete = all(l.age() <= max_transline_modify_age() for l in tl)
            voids = []
            for l in tl:
                if can_delete:
                    self._delete_line(l)
                else:
                    voids.append(l)
            self._void_lines(voids)
            if len(self.dl) == 0:
                # The last transaction line was deleted, so also
                # delete the transaction.
                self.canceltrans()
                return
            self._clear_marks()
            self.cursor_off()
            self.update_balance()
            self._redraw()

    def canceltrans(self):
        """Cancel the whole transaction"""
        if not self.entry():
            return
        trans = self._gettrans()
        if self.hook("canceltrans", trans):
            return
        if trans.closed:
            log.info("Register: cancel closed transaction %d", trans.id)
            tl = self.dl
            self._clear()
            trans = self.get_open_trans()
            if not trans:
                return
            self._void_lines([l for l in tl if isinstance(l, tline)])
            self.cursor_off()
            self.update_balance()
            self._redraw()
            if payment_method_menu_after_void():
                self._payment_method_menu(
                    title="Choose refund type, or press Clear "
                    "to add more items")
        else:
            # Delete this transaction and everything to do with it
            tn = trans.id
            if any(p.pending or p.amount != zero for p in trans.payments):
                ui.infopopup(["Cannot delete transaction with pending "
                              "or non-zero payments."],
                             title="Error")
                return
            log.info("Register: cancel open transaction %d" % tn)
            # Payment, Transline and StockOut objects should be deleted
            # implicitly in cascade
            td.s.delete(trans)
            self.transid = None
            td.s.flush()
            self._clear()
            self._redraw()
            ui.infopopup(
                [f"Transaction number {tn} has been cancelled."],
                title="Transaction Cancelled",
                dismiss=keyboard.K_CASH)

    def cancelline(self, l):
        if not self.entry():
            return
        if not self.hook("cancelline", l):
            if l.age() < max_transline_modify_age():
                self._delete_line(l)
            else:
                self._void_lines([l])
        if len(self.dl) == 0:
            # The last transaction line was deleted, so also
            # delete the transaction.
            self.canceltrans()
            return
        self.cursor_off()
        self.update_balance()
        self._redraw()

    def _delete_line(self, l):
        """Delete a line from the current transaction

        l is a tline object"""
        trans = self._gettrans()
        tl = td.s.get(Transline, l.transline)
        assert tl.transaction == trans
        voided_line = tl.voids
        td.s.delete(tl)
        td.s.flush()
        del self.dl[self.dl.index(l)]
        if voided_line:
            # This line may have been voiding a line in the current
            # transaction.  Search through and update the line if
            # found.
            for tl in self.dl:
                if hasattr(tl, "transline") and tl.transline == voided_line.id:
                    tl.update()
        td.s.expire(trans, ['total'])

    def _void_lines(self, ll):
        """Void some transaction lines

        Add lines reversing the supplied transaction lines to the
        current transaction.  ll is a list of tline objects, but the
        transaction lines may not be in the current transaction.

        The caller is responsible for ensuring that the current
        transaction is open, updating the balance and redrawing.
        """
        log.debug("_void_lines %s", ll)
        if not ll:
            return
        trans = self._gettrans()
        tll = [td.s.get(Transline, l.transline) for l in ll]
        voidlines = [
            transline.void(trans, self.user.dbuser, tillconfig.terminal_name)
            for transline in tll]
        voidlines = [x for x in voidlines if x]
        td.s.add_all(voidlines)
        td.s.flush()  # get transline IDs, fill in voided_by
        for ntl in voidlines:
            self._apply_discount(ntl)
            self.dl.append(tline(ntl.id))
        for l in ll:
            l.update()
        td.s.flush()

    def cancelpayment(self, p):
        if not self.entry():
            return
        if self.hook("cancelpayment", p):
            return
        trans = self._gettrans()
        payment = td.s.get(Payment, p.payment_id)
        assert payment.transaction == trans
        td.s.delete(payment)
        td.s.flush()
        td.s.expire(trans, ['total'])
        del self.dl[self.dl.index(p)]
        if len(self.dl) == 0:
            # The last line was deleted, so also delete the
            # transaction.
            self.canceltrans()
            return
        self.cursor_off()
        self.update_balance()
        self._redraw()

    def markkey(self):
        """The Mark key was pressed.

        If there's no line currently selected, pops up a help box.

        If a payment line is selected, pops up an error box.

        If a non-voided transaction line is selected, toggles the
        selection status of that line and updates the prompt.
        """
        if self.hook("markkey"):
            return
        trans = self._gettrans()
        if self.s.cursor >= len(self.dl):
            ui.infopopup(
                ["Use the Up/Down keys to choose a line, and press Mark "
                 "to select or deselect that line.  Selected lines are "
                 "shown in blue.", "",
                 "You can mark several lines and then perform an operation "
                 "on all of them by pressing Manage Transaction."],
                title="Mark key help")
            return
        l = self.dl[self.s.cursor]
        if isinstance(l, tline) and not l.voided:
            if l in self.ml:
                self.ml.remove(l)
            else:
                self.ml.add(l)
            l.update_mark(self.ml)
            if self.ml:
                if trans.closed:
                    self.prompt = ""
                else:
                    self.prompt = "Press Clear to remove all the marks.  " \
                                  "Pressing a payment key now will use the " \
                                  "marked lines " \
                                  "total instead of the whole outstanding " \
                                  "amount.  "
                self.prompt += "Press Cancel to void the marked lines.  " \
                               "Press Manage Transaction for other options."
            else:
                self.prompt = self.defaultprompt
            self.s.drawdl()
        else:
            ui.infopopup(
                ["You can only mark non-voided transaction lines.  "
                 "You can't mark payments or voided transaction lines."],
                title="Mark error")
            return

    def _total_value_of_marked_translines(self):
        if not self.ml:
            return zero
        return td.s.query(func.sum(Transline.items * Transline.amount)).\
            select_from(Transline).\
            filter(Transline.id.in_([x.transline for x in self.ml])).\
            scalar()

    def clear_and_lock_register(self):
        # We set the user's current transaction to None and dismiss
        # the current register page, most likely returning to the lock
        # screen on the next time around the event loop.
        self.user.dbuser = td.s.get(User, self.user.userid)
        self.user.dbuser.transaction = None
        td.s.flush()
        self.deselect()

    def recalltrans(self, transid):
        # We refresh the user object as if in enter() here, but don't
        # bother with the full works because we're replacing the current
        # transaction anyway!
        self.user.dbuser = td.s.get(User, self.user.userid)
        self._clear()
        self._redraw()
        if transid:
            log.info("Register: recalltrans %d", transid)
            trans = td.s.get(Transaction, transid)
            if not trans:
                ui.infopopup([f"Transaction {transid} does not exist."],
                             title="Error")
                return
            # Leave a message if the transaction belonged to another
            # user.
            user = td.s.query(User).filter(User.transaction == trans).first()
            if user:
                user.transaction = None
                user.message = \
                    f"Your transaction {trans.id} "\
                    f"({trans.notes or 'no notes'}) was taken over "\
                    f"by {self.user.fullname} " \
                    f"using the Recall Transaction function."
            self._loadtrans(trans.id)
            self.keyguard = True
            self.close_if_balanced()
            if not trans.closed:
                message = trans.meta.get(transaction_message_key)
                if message:
                    ui.infopopup(
                        [message.value], title="Note", colour=ui.colour_info)
                age = trans.age
                if not self.transaction_locked \
                   and open_transaction_warn_after() \
                   and age > open_transaction_warn_after():
                    ui.infopopup(
                        [f"This transaction is {age.days} days old.  Please "
                         "arrange for it to be paid soon."],
                        title="Warning")
                if self.transaction_locked:
                    self.transaction_lock_popup()
            self.hook("recalltrans_loaded", trans)
        self.cursor_off()
        self.update_balance()
        self._redraw()
        self._resume_pending_payment()

    @user.permission_required("recall-trans", "Change to a different "
                              "transaction")
    def recalltranskey(self):
        if self.hook("recalltranskey"):
            return
        sc = Session.current(td.s)
        if sc is None:
            log.info("Register: recalltrans: no session")
            ui.infopopup(["There is no session in progress.  You can "
                          "only recall transactions that belong to the "
                          "current session."], title="Error")
            return
        log.info("recalltrans")
        trans = self._gettrans()
        if trans and not trans.closed and not trans.notes:
            ui.infopopup(
                ["Recalling another transaction will hide the current one "
                 "away.  You must set a note on the current transaction first "
                 "using 'Manage Transaction' option 4 or 5 so that you will "
                 "be able to find it again."],
                title="Transaction note required")
            return
        transactions = td.s.query(Transaction)\
                           .filter(Transaction.session == sc)\
                           .options(undefer(Transaction.age))\
                           .options(undefer(Transaction.total))\
                           .options(joinedload(Transaction.user))\
                           .order_by(Transaction.closed == True)\
                           .order_by(desc(Transaction.id))\
                           .all()
        f = ui.tableformatter(' r l r l l ')
        sl = [(f(x.id, ('open', 'closed')[x.closed],
                 tillconfig.fc(x.total),
                 x.user.shortname if x.user else "", x.notes,
                 colour=colour_locked if _transaction_age_locked(x) else None),
               self.recalltrans, (x.id,)) for x in transactions]
        if trans and not trans.closed:
            firstline = ("Save current transaction and lock register",
                         self.clear_and_lock_register, None)
        else:
            firstline = ("Start a new transaction", self.recalltrans, (None,))
        ui.menu([firstline] + sl,
                title="Recall Transaction",
                blurb="Select a transaction and press Cash/Enter.",
                colour=ui.colour_input)

    @user.permission_required("defer-trans", "Defer a transaction to a "
                              "later session")
    def defertrans(self):
        if not self.entry():
            return
        trans = self._gettrans()
        if not trans:
            return
        if trans.closed:
            ui.infopopup([f"Transaction {trans.id} has been closed, and "
                          "cannot now be deferred."], title="Error")
            return
        if not trans.notes:
            ui.infopopup(
                ["This transaction doesn't have a note set.  You can't defer "
                 "it until you have set one using 'Manage Transaction' "
                 "option 4 or 5 so that we know who the transaction belongs "
                 "to in the next session."],
                title="Error")
            return

        if self.hook("defertrans", trans):
            return

        # 1. Check the sum of non-deferrable payments.  If it's
        # negative, the transaction can't be deferred (because the
        # user would have to put cash _in_ to the register to defer
        # successfully).
        nds = zero
        ndps = []
        for p in trans.payments:
            if not p.paytype.driver.deferrable:
                nds = nds + p.amount
                ndps.append(p)

        if nds < zero:
            ui.infopopup(
                ["This transaction can't be deferred because it has "
                 "non-deferrable payments that sum to less than zero."],
                title="Error")
            return

        # 2. If non-deferrable payments sum to anything other than
        # zero, check that there is a payment method configured that
        # supports both change and refunds; we will need it later.
        defer_pm = td.s.get(PayType, defer_payment_method())
        if not defer_pm or not defer_pm.active:
            defer_pm = None

        if nds:
            if not defer_pm:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  There is no "
                     "payment method configured for this, so it "
                     "cannot be done now."],
                    title="Error")
                return
            # The payment method must support negative payments, and
            # the noninteractive add_payment() method.
            if not defer_pm.driver.refund_supported \
               or not defer_pm.driver.add_payment_supported:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  The defer payment "
                     "method does not support this."],
                    title="Error")
                return

        # 3. Any non-deferrable payments are moved to a new transaction.
        ptrans = None
        if ndps:
            ptrans = Transaction(
                session=trans.session,
                notes=f"Payments from deferred transaction {trans.id}")
            td.s.add(ptrans)
            for p in ndps:
                p.transaction = ptrans

            # 4. If the new transaction doesn't balance (i.e. it has a
            # positive balance), a refund is made using the defer
            # payment method and a receipt is printed out stating that
            # the refund should be used towards the deferred
            # transaction.  A popup note is left in the deferred
            # transaction's metadata explaining that there should be
            # cash to use towards paying it

            if nds != zero:
                if not tillconfig.receipt_printer:
                    ui.infopopup(
                        ["The till needs to print a ticket to wrap the "
                         "money for this part-paid transaction, but it "
                         "doesn't have a receipt printer.",
                         "",
                         "Use a till with a receipt printer to defer "
                         "this transaction."],
                        title="Error - no printer")
                    td.s.rollback()
                    return
                user.log(f"Deferred transaction {trans.logref} which was "
                         f"part-paid by {tillconfig.fc(nds)}")
                defer_pm.driver.add_payment(ptrans, "Deferred", zero - nds)
                trans.set_meta(
                    transaction_message_key,
                    f"This transaction was part-paid when it was deferred on "
                    f"{trans.session.date} by {self.user.fullname}.  There "
                    f"should be {tillconfig.fc(nds)} {defer_pm.description} "
                    f"set aside to be used towards this transaction "
                    f"when you are ready to accept the final payment from "
                    f"the customer.")
                try:
                    printer.print_deferred_payment_wrapper(
                        tillconfig.receipt_printer,
                        trans, defer_pm, nds, self.user.fullname)
                    printer.kickout(tillconfig.cash_drawer)
                except Exception as e:
                    ui.infopopup(
                        ["There was an error printing the deferred payment "
                         "wrapper. Ensure the printer is working and "
                         "try again.",
                         "",
                         f"The error was: {e}"],
                        title="Error")
                    td.s.rollback()
                    return

        transid = trans.id
        trans.session = None
        td.s.flush()

        # 5. If there's a new transaction, it's closed and loaded;
        # otherwise the register is cleared.
        if ptrans:
            ptrans.closed = True
            td.s.flush()
            self._loadtrans(ptrans.id)
        else:
            self._clear()
            self._redraw()

        message = [f"Transaction {transid} has been deferred to the next "
                   "session.  Make sure you keep a note of the "
                   "transaction number and the name of the person "
                   "responsible for paying it!"]
        if nds:
            message = message \
                + ["", f"{tillconfig.fc(nds)} had been paid towards this "
                   "transaction. You must remove this amount from the "
                   "till and set it aside to be used to pay off the "
                   "transaction in a later session.",
                   "",
                   f"Wrap the {defer_pm.description} in the deferred "
                   "transaction receipt that has just been printed."]
        ui.infopopup(
            message,
            title="Transaction defer confirmed",
            colour=ui.colour_confirm,
            dismiss=keyboard.K_CLEAR if nds else keyboard.K_CASH)

    def _check_session_and_open_transaction(self):
        # For transaction merging
        if not self.entry():
            return False, False
        sc = Session.current(td.s)
        if not sc:
            ui.infopopup(["There is no session active."], title="Error")
            return False, False
        trans = self._gettrans()
        if not trans:
            ui.infopopup(["There is no current transaction."], title="Error")
            return False, False
        if trans.closed:
            ui.infopopup(["The current transaction is closed and can't "
                          "be merged with another transaction."],
                         title="Error")
            return False, False
        return sc, trans

    @user.permission_required("merge-trans", "Merge two transactions")
    def mergetransmenu(self):
        sc, trans = self._check_session_and_open_transaction()
        if not sc:
            return
        if self.hook("mergetrans", trans):
            return
        # XXX it would be sensible to order by descending transaction
        # ID (i.e. most recent transaction first), but we've been
        # doing it the other way long enough that changing would upset
        # people!  Consult first, and possibly make it configurable.
        tl = td.s.query(Transaction)\
                 .filter(Transaction.session == sc)\
                 .filter(Transaction.closed == False)\
                 .options(undefer(Transaction.age))\
                 .options(undefer(Transaction.total))\
                 .options(joinedload(Transaction.user))\
                 .order_by(Transaction.id)\
                 .all()
        f = ui.tableformatter(' r r l l ')
        sl = [(f(x.id, tillconfig.fc(x.total),
                 x.user.shortname if x.user else "", x.notes or "",
                 colour=colour_locked if _transaction_age_locked(x) else None),
               self._mergetrans, (x.id,)) for x in tl if x.id != self.transid]
        ui.menu(sl,
                title="Merge with transaction",
                blurb="Select a transaction to merge this one into, "
                "and press Cash/Enter.",
                colour=ui.colour_input)

    def _mergetrans(self, othertransid):
        sc, trans = self._check_session_and_open_transaction()
        if not sc:
            return
        othertrans = td.s.get(Transaction, othertransid)
        if len(trans.payments) > 0 and not allow_mergetrans_with_payments():
            ui.infopopup(
                ["Some payments have already been entered against "
                 f"transaction {trans.id}, so it can't be merged with "
                 "another transaction."],
                title="Error")
            return
        for p in trans.payments:
            if not p.paytype.driver.mergeable:
                ui.infopopup(
                    [f"Transaction {trans.id} has one or more payments that "
                     "can't be merged with another transaction."],
                    title="Error")
                return
        if othertrans.closed:
            ui.infopopup(
                [f"Transaction {othertrans.id} has been closed, so we can't "
                 "merge this transaction into it."],
                title="Error")
            return
        if _transaction_age_locked(othertrans):
            message = [
                f"Transaction {othertrans.id} ({othertrans.notes}) is "
                f"locked because it is more than "
                f"{open_transaction_lock_after().days} days old."]
            if open_transaction_lock_message():
                message.append("")
                message.append(open_transaction_lock_message())
            ui.infopopup(message, title="Other transaction locked")
            return
        if self.hook("mergetrans_finish", trans, othertrans):
            return
        # Leave a message if the other transaction belonged to another
        # user.
        user = td.s.query(User).filter(User.transaction == othertrans).first()
        if user:
            user.transaction = None
            user.message = \
                f"Your transaction {othertrans.id} " \
                f"({othertrans.notes or 'no notes'}) was taken over " \
                f"by {self.user.fullname} when they merged another " \
                f"transaction into it."
        for line in list(trans.lines):
            line.transaction = othertrans
        for p in list(trans.payments):
            p.transaction = othertrans
        td.s.delete(trans)
        td.s.flush()
        td.s.expire(othertrans)
        self._loadtrans(othertrans.id, update_discount=True)

    def _splittrans(self, notes):
        if not self.entry():
            return
        if not self.ml:
            return
        trans = self._gettrans()
        # Create a new transaction with the supplied notes
        nt = Transaction(session=trans.session, notes=notes,
                         discount_policy=trans.discount_policy)
        td.s.add(nt)
        for l in self.ml:
            # Where a transaction line voids other transaction lines
            # in the same transaction, we want to drag the other
            # transaction lines along too.  This prevents the voided
            # lines being in an open transaction (and so being subject
            # to their value changing as discounts are applied) while
            # the line that voids them is in a closed transaction and
            # thus immutable.
            tlid = l.transline
            while tlid:
                t = td.s.get(Transline, tlid)
                if t.transaction != trans:
                    break
                t.transaction = nt
                tlid = t.voids.id if t.voids else None
        td.s.flush()
        td.s.expire(trans, ['total'])
        self._loadtrans(trans.id)
        # If the current transaction already has a note (i.e. pressing
        # the "Recall Trans" button would give the list of
        # transactions rather than a prompt to name the current
        # transaction) then offer a shortcut to the new transaction
        if trans.notes:
            ui.infopopup(
                ["The selected lines were moved to a new transaction, "
                 "number {num}, called '{note}'.  Press {recall} to go "
                 "to the new transaction now, or {clear} to stay on the "
                 "current transaction.".format(
                     num=nt.id, note=nt.notes,
                     recall=keyboard.K_RECALLTRANS,
                     clear=keyboard.K_CLEAR)],
                title="Transaction split", colour=ui.colour_info,
                dismiss=keyboard.K_CLEAR, keymap={
                    keyboard.K_RECALLTRANS: (self.recalltrans, (nt.id,),
                                             True)})
        else:
            ui.infopopup(
                [f"The selected lines were moved to a new transaction, "
                 f"number {nt.id}, called '{nt.notes}'.  You can find it "
                 f"using the {keyboard.K_RECALLTRANS} button."],
                title="Transaction split", colour=ui.colour_info,
                dismiss=keyboard.K_CASH)

    def settransnote(self, notes):
        if not self.entry():
            return
        trans = self._gettrans()
        if not trans or trans.closed:
            return
        # Truncate note to fit in field in model
        trans.notes = notes[:60]
        user.log(f"Set the note on {trans.logref} to '{trans.notes}'")
        self._redraw_note()

    def _apply_discount(self, tline):
        tline.amount = tline.original_amount
        tline.discount = zero
        tline.discount_name = None
        if tline.items > 0:
            if self.discount_policy:
                discount, discount_name = \
                    self.discount_policy.discount_for(tline)
                tline.amount = tline.amount - discount
                tline.discount = discount
                tline.discount_name = discount_name if discount else None
        else:
            # Lines with negative numbers of items usually void earlier
            # transaction lines.  Copy the amount, discount and discount
            # name from the earlier transaction line to ensure that
            # the original discount is reversed.
            if tline.voids:
                tline.amount = tline.voids.amount
                tline.discount = tline.voids.discount
                tline.discount_name = tline.voids.discount_name

    def _apply_discount_policy(self, policy):
        trans = self._gettrans()
        if not trans:
            return
        if trans.closed:
            ui.infopopup(["The transaction is already closed."], title="Error")
            return
        # Check permissions for new policy
        if policy and policy.permission_required \
           and not self.user.may(policy.permission_required[0]):
            ui.infopopup(
                ["You do not have the '{}' permission that is required "
                 "to apply this type of discount.".format(
                     policy.permission_required[0])],
                title="Not allowed")
            return
        trans.discount_policy = policy.policy_name if policy else None
        self.discount_policy = policy
        for tline in trans.lines:
            self._apply_discount(tline)
        td.s.flush()
        if policy:
            user.log(f"Set the discount on {trans.logref} "
                     f"to '{policy.policy_name}'")
        else:
            user.log(f"Removed the discount on {trans.logref}")
        # Since everything is changing, just reload the whole transaction
        self._loadtrans(trans.id)

    @user.permission_required('apply-discount',
                              'Apply a discount to a transaction')
    def _discount_menu(self):
        if self.hook("apply_discount_menu"):
            return
        menu = [("No discount", self._apply_discount_policy, (None,))] \
            + [(x.policy_name, self._apply_discount_policy, (x,))
               for x in DiscountPolicyPlugin.policies.values()]
        ui.automenu(menu, title="Apply Discount")

    def _start_payment_search(self, paytype_id):
        paytype = td.s.get(PayType, paytype_id)
        paytype.driver.search(self.recalltrans)

    def _payment_search_menu(self):
        ui.automenu(
            [(m.description, self._start_payment_search, (m.paytype,))
             for m in td.s.query(PayType)
             .filter(PayType.mode == 'active')
             .order_by(PayType.order, PayType.paytype)
             .all()],
            title="Payment search",
            blurb="What type of payment are you searching for?",
            spill="keymenu")

    def search_menu(self):
        if self.hook("search_menu"):
            return
        menu = [
            ("1", "Recall a transaction by number", recalltranspopup, (self,)),
            ("2", "Search for an item in the transaction",
             transline_search_popup, (self.recalltrans,)),
            ("3", "Search for a payment", self._payment_search_menu, None),
        ]
        ui.keymenu(menu, title="Search for a transaction")

    def managetranskey(self):
        trans = self._gettrans()
        if self.hook("managetrans", trans):
            return
        if self.ml:
            marked_total = tillconfig.fc(
                self._total_value_of_marked_translines())
            menu = [
                ("1", "Void the marked lines", self.cancelmarked, None),
            ]
            if trans and not trans.closed:
                menu += [("3", "Split the marked lines out "
                          "into a separate transaction",
                          splittrans, (marked_total, self._splittrans)),
                         ("6", "Choose payment method",
                          self._payment_method_menu, None)]
            ui.keymenu(
                menu, title="Marked line options",
                blurb=["", "The value of the marked lines is {}".format(
                    marked_total)])
            return
        if trans and not trans.closed:
            menu = [
                ("1", "Defer transaction to next session",
                 self.defertrans, None),
                ("3", "Merge this transaction with another "
                 "open transaction", self.mergetransmenu, None),
                ("4", "Set this transaction's note to '{}'".format(
                    self.user.fullname),
                 self.settransnote, (self.user.fullname,)),
                ("5", "Change this transaction's notes "
                 "(free text entry)",
                 edittransnotes, (trans.id, self.settransnote)),
                ("6", "Choose payment method",
                 self._payment_method_menu, None),
            ]
        else:
            menu = []
        menu.append(("7", "Add a custom transaction line",
                     addtransline, (self.deptlines,)))
        menu.append(("8", "Search for a transaction", self.search_menu, None))
        if trans and not trans.closed and DiscountPolicyPlugin.policies:
            menu.append(("9", "Apply a discount", self._discount_menu, None))

        ui.keymenu(menu, title="Transaction options")

    def entry(self):
        """Check for valid transaction.

        This function is called at all entry points to the register
        code except the __init__ code.  It checks to see whether the
        current transaction is still valid; if it isn't it pops up an
        appropriate message and clears the register.

        Returns True if the current transaction is valid, or False if
        it isn't.  If False is returned, this function may have popped
        up a dialog box.
        """
        # Fetch the current user database object.  We don't recreate
        # the user.database_user object because that's unlikely to
        # change often; we're just interested in the transaction and
        # register fields.  The fetch from the database has probably
        # already been done in hotkeypress() - here we are fetching
        # from the sqlalchemy session's map
        self.user.dbuser = td.s.get(User, self.user.userid)

        # This check has already been done in hotkeypress().  We
        # repeat it here because it is possible we may not have been
        # entered in response to a keypress - a timer event, for
        # example.
        if self.user.dbuser.register_id != tillconfig.register_id:
            # If the register in the database isn't us, lock immediately
            self.deselect()
            return False

        # If there is a message queued for the user, display it.  It
        # probably explains where their transaction has gone to!
        if self.user.dbuser.message:
            ui.infopopup([self.user.dbuser.message],
                         title="Transaction information")
            self._clear()
            self._redraw()
            self.user.dbuser.message = None
            td.s.flush()
            return False

        if self.transid and not self.user.dbuser.transaction:
            # Someone has taken our transaction without leaving a
            # message.  How rude!  Give them a default message.
            ui.infopopup(["Your transaction has gone away."],
                         title="Transaction gone")
            self._clear()
            self._redraw()
            td.s.flush()
            return False

        # At this point, self.transid and self.user.dbuser.transaction
        # should either both be None or both refer to the current
        # transaction.
        self.transid = self.user.dbuser.transaction.id \
            if self.user.dbuser.transaction else None
        self._update_timeout()
        return True

    def entry_noninteractive(self):
        """Check for valid transaction

        This function is called to check whether the current
        transaction is still valid, in contexts where the user may not
        be standing in front of the register (eg. when a card payment
        dialog is checking payment state based on a timer).

        If this returns False, the caller should clean up and then
        call the deselect() method.
        """
        self.user.dbuser = td.s.get(User, self.user.userid)
        if self.user.dbuser.register_id != tillconfig.register_id:
            # User has logged in somewhere else
            return False
        if self.transid and not self.user.dbuser.transaction:
            # Transaction has been taken by another user
            return False
        if self.transid and self.transid != self.user.dbuser.transaction.id:
            # This _should_ never happen but would be very bad if it did!
            return False
        return True

    def _notify_user_register(self, userid_string):
        # This is called whenever a user_register notification is sent
        # by the database, which will happen whenever a user's transid
        # or register column is changed. If the userid_string
        # corresponds to our user, run entry_noninteractive() to check
        # that the user hasn't moved to another register and that
        # their transaction hasn't been taken over by someone else.
        if not self.selected:
            return
        log.debug(f"{self=} got user_register for {userid_string}")
        try:
            userid = int(userid_string)
        except Exception:
            return
        if userid == self.user.userid:
            with td.orm_session():
                if not self.entry_noninteractive():
                    self.deselect()

    def hook(self, action, *args, **kwargs):
        """Check with plugins before performing an action

        If any plugin returns True from its hook method, don't perform
        the action.
        """
        for i in RegisterPlugin.instances:
            method = getattr(i, "hook_" + action, None)
            if method and method(self, *args, **kwargs):
                return True

    @staticmethod
    def _add_linemenu_query_options(q):
        return q.options(joinedload(KeyboardBinding.stockline))\
                .options(joinedload(KeyboardBinding.stockline)
                         .joinedload(StockLine.stockonsale)
                         .undefer(StockItem.used)
                         .undefer(StockItem.remaining))\
                .options(joinedload(KeyboardBinding.stockline)
                         .joinedload(StockLine.stockonsale)
                         .joinedload(StockItem.stocktype))\
                .options(joinedload(KeyboardBinding.stockline)
                         .joinedload(StockLine.stocktype))\
                .options(joinedload(KeyboardBinding.plu))

    def keypress(self, k):
        # This is our main entry point.  We will have a new database session.
        # Update the transaction object before we do anything else!
        if self.locked:
            # When we are locked, the only operation that's permitted
            # is printing the current transaction if it is closed.
            # All other keypresses are ignored.
            trans = self._gettrans()
            if trans and trans.closed and k == keyboard.K_PRINT:
                self.printkey()
            return
        if not self.entry():
            return
        for i in RegisterPlugin.instances:
            if i.keypress(self, k):
                return
        if hasattr(k, 'code'):
            return self.barcode(k)
        if hasattr(k, 'line'):
            linekeys.linemenu(
                k, self.linekey, allow_stocklines=True,
                allow_plus=True, allow_mods=True,
                add_query_options=self._add_linemenu_query_options,
                suppress_modifier_display=self.mod)
            return
        self.repeat = None
        if hasattr(k, 'notevalue'):
            return self.notekey(k)
        elif hasattr(k, 'paymentmethod'):
            return self.paymentkey(k.paymentmethod)
        elif k in keyboard.numberkeys:
            return self.numkey(k)
        keys = {
            keyboard.K_CASH: self.cashkey,
            keyboard.K_DRINKIN: self.drinkinkey,
            keyboard.K_QUANTITY: self.quantkey,
            keyboard.K_CLEAR: self.clearkey,
            keyboard.K_CANCEL: self.cancelkey,
            keyboard.K_PRINT: self.printkey,
            keyboard.K_RECALLTRANS: self.recalltranskey,
            keyboard.K_MANAGETRANS: self.managetranskey,
            keyboard.K_MARK: self.markkey,
        }
        if k in keys:
            return keys[k]()
        if k in self.hotkeys:
            return self.hotkeys[k]()
        ui.beep()

    def hotkeypress(self, k):
        # Fetch the current user from the database.  We don't recreate
        # the user.database_user object because that's unlikely to
        # change often; we're just interested in the transaction and
        # register fields.
        self.user.dbuser = td.s.get(
            User, self.user.userid,
            options=[joinedload(User.transaction)])

        # Check that the user hasn't moved to another terminal.  If
        # they have, lock immediately.
        if self.user.dbuser.register_id != tillconfig.register_id:
            self.deselect()
            return super().hotkeypress(k)

        if self._autolock and k == self._autolock and not self.locked \
           and self.s.focused:
            # Intercept the 'Lock' keypress and handle it ourselves.
            # Do this only if our scrollable has the focus.
            self.locked = True
            self._redraw()
        else:
            super().hotkeypress(k)

    def select(self, u):
        # Called when the appropriate user token is presented
        self.user = u  # Permissions might have changed!
        self.user.dbuser.register_id = tillconfig.register_id
        td.s.flush()
        if self.locked:
            self.locked = False
            self._redraw()
        super().select()
        log.info("Existing page selected for %s", self.user.fullname)
        self.entry()

    def deselect(self):
        # We might be able to delete ourselves completely after
        # deselection if none of the popups has unsaved data.  When we
        # are recreated we can reload the current transaction from the
        # database.
        focus = ui.basicwin._focus  # naughty!
        self.unsaved_data = None
        while focus != self.s:
            unsaved_data = getattr(focus, 'unsaved_data', None)
            log.debug("deselect: checking %s: unsaved_data=%s",
                      focus, unsaved_data)
            if unsaved_data:
                log.info("Page for %s deselected; unsaved data (%s) so just "
                         "hiding the page", self.user.fullname, unsaved_data)
                self.unsaved_data = unsaved_data
                return super().deselect()
            focus = focus.parent
        log.info("Page for %s deselected with no unsaved data: deleting self",
                 self.user.fullname)
        super().deselect()
        self.dismiss()
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None
        if self._notify_user_register_listener:
            self._notify_user_register_listener.cancel()
            self._notify_user_register_listener = None

    def alarm(self):
        # The timeout has passed.  If the scrollable has the input
        # focus (i.e. there are no popups on top of us) we can
        # deselect.
        self._timeout_handle = None
        if self.s.focused:
            self.deselect()


def handle_login(u, *args, **kwargs):
    """Login handler for the register.

    Used in the configuration file to specify what happens when a user
    logs in.
    """
    for p in ui.basicpage._pagelist:
        if isinstance(p, page) and p.user.userid == u.userid:
            p.select(u)
            return p
    return page(u, *args, **kwargs)
