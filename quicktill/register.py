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
import textwrap
import math
from . import td, ui, keyboard, printer
import quicktill.stocktype
from . import linekeys
from . import modifiers
from . import payment
from . import user
import logging
import datetime
import time
log = logging.getLogger(__name__)
from . import foodorder
from .models import Transline, Transaction, Session, StockOut, Transline, penny
from .models import Payment, zero, User, Department, desc, RemoveCode
from .models import StockType
from sqlalchemy.sql import func
from decimal import Decimal
from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.orm import subqueryload, subqueryload_all
from sqlalchemy.orm import joinedload, joinedload_all
from sqlalchemy.orm import undefer
import uuid

max_transline_modify_age = datetime.timedelta(minutes=1)

# Permissions checked for explicitly in this module
user.action_descriptions['override-price'] = "Override the sale price of an item"
user.action_descriptions['nosale'] = "Open the cash drawer with no payment"
user.action_descriptions['suppress-refund-help-text'] = (
    "Don't show the refund help text")
user.action_descriptions['cancel-line-in-open-transaction'] = (
    "Delete or reverse a line in an open transaction")
user.action_descriptions['void-from-closed-transaction'] = (
    "Create a transaction voiding lines from a closed transaction")
user.action_descriptions['sell-dept'] = (
    "Sell items using a department key")

# Whenever the register is started it generates a new unique ID for
# itself.  This is used to distinguish register instances that are
# running at the same time, so they can coordinate moving transactions
# and users between registers.
register_instance = str(uuid.uuid4())

class bufferline(ui.lrline):
    """The last line on the register display

    This is used as the very last line on the register display - a
    special case.  It always consists of two lines: a blank line, and
    then a line showing the prompt or the contents of the input buffer
    at the left, and if appropriate the balance of the transaction on
    the right.
    """
    def __init__(self, reg):
        ui.lrline.__init__(self)
        self.colour = ui.colour_default
        self.cursor_colour = ui.colour_default
        self.reg = reg

    def display(self, width):
        if self.reg.qty is not None:
            m = "{} of ".format(self.reg.qty)
        else:
            m = ""
        if self.reg.mod is not None:
            m = m + "{} ".format(self.reg.mod.name)
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
                self.ltext = (
                    "This transaction has a negative balance, so a "
                    "refund is due.  Press the appropriate payment key "
                    "to issue a refund of that type.  If you are replacing "
                    "items for a customer you can enter the replacement "
                    "items now; the till will show the difference in price "
                    "between the original and replacement items.")
        if self.reg.ml:
            self.rtext = "{} {}".format(
                "Marked lines total",
                tillconfig.fc(self.reg._total_value_of_marked_translines()))
        else:
            log.debug("bal %s", repr(tillconfig.fc(self.reg.balance)))
            self.rtext = "{} {}".format(
                "Amount to pay" if self.reg.balance >= zero else "Refund amount",
                tillconfig.fc(self.reg.balance)) \
                if self.reg.balance != zero else ""
        # Add the expected blank line
        l = [''] + ui.lrline.display(self, width)
        self.cursor = (cursorx, len(l) - 1)
        return l

class tline(ui.lrline):
    """A transaction line

    This corresponds to a transaction line in the database.
    """
    def __init__(self, transline):
        ui.lrline.__init__(self)
        self.transline = transline
        self.marked = False
        self.update()

    def update(self):
        tl = td.s.query(Transline).get(self.transline)
        self.transtime = tl.time
        if tl.voided_by_id:
            self.voided = True
            self.ltext = "(Voided) " + tl.description
        else:
            self.voided = False
            self.ltext = tl.description
        self.rtext = tl.regtotal(tillconfig.currency)
        self.update_colour()

    def update_colour(self):
        if self.marked:
            self.colour = ui.colour_cancelline
        else:
            if self.voided:
                self.colour = ui.colour_error
            else:
                self.colour = ui.colour_default
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
        trans = td.s.query(Transaction).get(transid)
        ui.dismisspopup.__init__(
            self, 5, 60, title="Notes for transaction {}".format(trans.id),
            colour=ui.colour_input)
        notes = trans.notes
        self.notesfield = ui.editfield(2, 2, 56, f=notes, flen=60, keymap={
            keyboard.K_CASH: (self.enter, None)})
        self.notesfield.focus()

    def enter(self):
        notes = self.notesfield.f
        self.dismiss()
        self.func(notes)

class splittrans(user.permission_checked,ui.dismisspopup):
    """A popup to allow marked lines to be split into a different transaction."""
    permission_required = ("split-trans", "Split a transaction into two parts")

    def __init__(self, total, func):
        ui.dismisspopup.__init__(
            self, 8, 64, title="Move marked lines to new transaction",
            colour=ui.colour_input)
        self._func = func
        self.addstr(2, 2, "Total value of marked lines: {}".format(total))
        self.addstr(4, 2, "Notes for the new transaction containing "
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
        ui.dismisspopup.__init__(
            self, 9, 70, title="Add a custom transaction line",
            colour=ui.colour_input)
        self.addstr(2, 2, " Department:")
        self.addstr(3, 2, "Description:")
        self.deptfield = ui.modellistfield(
            2, 15, 20, Department,
            lambda q: q.order_by(Department.id),
            d=lambda x: x.description,
            keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.descfield = ui.editfield(3, 15, 53, flen=300)
        self.itemsfield = ui.editfield(4, 15, 5, validate=ui.validate_int)
        self.addstr(4, 21, "items @ {}".format(tillconfig.currency))
        self.amountfield = ui.editfield(4, 29 + len(tillconfig.currency), 8,
                                        validate=ui.validate_positive_float)
        self.addstr(4, 38 + len(tillconfig.currency), '=')
        self.itemsfield.sethook = self.calculate_total
        self.amountfield.sethook = self.calculate_total
        self.addbutton = ui.buttonfield(
            6, 25, 20, "Add transaction line",
            keymap={
                keyboard.K_CASH: (self.enter,None)})
        ui.map_fieldlist(
            [self.deptfield, self.descfield, self.itemsfield,
             self.amountfield, self.addbutton])
        self.deptfield.focus()

    def calculate_total(self):
        self.addstr(4, 40 + len(tillconfig.currency), ' ' * 15)
        try:
            items = int(self.itemsfield.f)
            amount = Decimal(self.amountfield.f)
            if items == 0:
                raise Exception("Zero items not permitted")
        except:
            return
        self.addstr(4, 40 + len(tillconfig.currency),
                    tillconfig.fc(items * amount))
    def enter(self):
        dept = self.deptfield.read()
        if dept is None:
            return ui.infopopup(["You must specify a department."],
                                title="Error")
        text = self.descfield.f if self.descfield.f else dept.description
        try:
            items = int(self.itemsfield.f)
            amount = Decimal(self.amountfield.f)
        except:
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
        "recall-any-trans", "Recall any transaction, even from previous sessions")
    def __init__(self, reg):
        self._reg = reg
        ui.dismisspopup.__init__(self, 5, 34, title="Recall Transaction", colour=ui.colour_input)
        self.addstr(2, 2, "Transaction number:")
        self.transfield = ui.editfield(2, 22, 10, validate=ui.validate_int, keymap={
            keyboard.K_CASH: (self.enterkey, None)})
        self.transfield.focus()

    def enterkey(self):
        self.dismiss()
        try:
            transid = int(self.transfield.read())
        except:
            return
        self._reg.recalltrans(transid)

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
    if user.may('override-price') and user.may('reprice-stock'):
        ist = stocktype
        ui.infopopup(
            ["No sale price has been set for {}.  You can enter a price "
             "before pressing the line key to set the price just this once, "
             "or you can press {} now to set the price permanently.".format(
                 ist.format(),
                 keyboard.K_MANAGESTOCK.keycap)],
            title="Unpriced item found", keymap={
                keyboard.K_MANAGESTOCK: (
                    lambda: quicktill.stocktype.reprice_stocktype(ist),
                    None, True)})
    elif user.may('override-price'):
        ui.infopopup(
            ["No sale price has been set for {}.  You can enter a price "
             "before pressing the line key to set the price just this once.".\
             format(ist.format())],
            title="Unpriced item found")
    else:
        ui.infopopup(
            ["No sale price has been set for {}.  You must ask a manager "
             "to set a price for it before you can sell it.".format(
                 ist.format())],
            title="Unpriced item found")

def record_pullthru(stockid, qty):
    td.s.add(StockOut(stockid=stockid, qty=qty, removecode_id='pullthru'))
    td.s.flush()

class repeatinfo(object):
    """Information for repeat keypresses."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class _update_timeout_scrollable(ui.scrollable):
    """A scrollable that calls _update_timeout() on its parent when it
    receives the input focus.
    """
    def focus(self):
        super(_update_timeout_scrollable, self).focus()
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
        self.transid = None
        self.user = user
        log.info("Page created for %s", self.user.fullname)
        ui.basicpage.__init__(self)
        self._autolock = autolock
        self.locked = False
        self._timeout = timeout
        self._timeout_handle = None # Used to cancel timeout
        self._update_timeout()
        self.h = self.h - 1 # XXX hack to avoid drawing into bottom
                            # right-hand cell; is this still
                            # necessary?
        self.hotkeys = hotkeys
        self.defaultprompt = "Ready"
        # Set user's current register to be us
        self.user.dbuser.register = register_instance
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

    def _gettrans(self):
        """Obtain the Transaction object for the current transaction

        Queries the database if the Transaction has not been loaded,
        otherwise loads it from the database session's identity map.

        If there is no current transaction (self.transid is None or the
        referenced transaction doesn't exist) returns None.
        """
        if self.transid:
            return td.s.query(Transaction).get(self.transid)

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
        self.buf = "" # Input buffer
        self.qty = None # Quantity (integer)
        self.mod = None # Modifier (modkey object)

    def _clear(self):
        """Reset the page.

        Reset the page to having no current transaction and nothing in
        the input buffer.  Note that this does not cause a redraw;
        various functions may want to fiddle with the state (for
        example loading a previous transaction) before requesting a
        redraw.
        """
        self.dl = [] # Display list
        if hasattr(self, 's'):
            self.s.set(self.dl) # Tell the scrollable about the new display list
        self.ml = set() # Set of marked tlines
        self.transid = None # Current transaction
        self.user.dbuser.transaction = None
        self.repeat = None # If dept/line button pressed, update this transline
        self.keyguard = False
        self.clearbuffer()
        self.balance = zero # Balance of current transaction
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

    def _loadtrans(self, transid):
        """Load a transaction, overwriting all our existing state.
        """
        log.debug("Register: loadtrans %s", transid)
        # Reload the transaction and its related objects
        trans = td.s.query(Transaction).\
                filter_by(id=transid).\
                options(subqueryload_all('payments')).\
                options(joinedload('lines.user')).\
                options(undefer('total')).\
                one()
        self.transid = trans.id
        if trans.user:
            # There is a unique constraint on User.trans_id - if
            # another user has this transaction, remove it from them
            # before claiming it for the current user otherwise we
            # will receive an integrity exception.
            trans.user = None
            td.s.flush()
        trans.user = self.user.dbuser
        self.dl = [tline(l.id) for l in trans.lines] \
                  + [payment.pline(i) for i in trans.payments]
        self.s.set(self.dl)
        self.ml = set()
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

    def pagename(self):
        trans = self._gettrans()
        if trans:
            return "{0} - Transaction {1} ({2})".format(
                self.user.shortname, trans.id,
                ("open", "closed")[trans.closed])
        return self.user.shortname

    def _redraw(self):
        """Updates the screen, scrolling until the cursor is visible."""
        self.s.redraw()
        self.updateheader()

    def _redraw_note(self):
        trans = self._gettrans()
        note = trans.notes if trans else ""
        note = note + " " * (self.w - len(note))
        c = self.win.getyx()
        self.addstr(0, 0, note, ui.colour_changeline)
        self.win.move(*c)

    def cursor_off(self):
        # Returns the cursor to the buffer line.  Does not redraw (because
        # the caller is almost certainly going to do other things first).
        self.s.cursor = len(self.dl)

    def update_balance(self):
        trans = self._gettrans()
        self.balance = trans.balance if trans else zero

    def close_if_balanced(self):
        trans = self._gettrans()
        if (trans and not trans.closed and (
                trans.lines or trans.payments)
            and trans.total == trans.payments_total):
            # Yes, it's balanced!
            trans.closed = True
            td.s.flush()
            self._clear_marks()
            if self._autolock:
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
                    ["The modifer '{}' can't be found.  This is a till "
                     "configuration error.".format(kb.modifier)],
                    title="Missing modifier")
                return
            mod = modifiers.all[kb.modifier]

        # Keyboard bindings can refer to a stockline, PLU or modifier
        if kb.stockline:
            self._sell_stockline(kb, mod)
        elif kb.plu:
            self._sell_plu(kb, mod)
        else:
            self.mod = mod
            self.cursor_off()
            self._redraw()

    def _read_explicitprice(
            self, buf, department,
            permission_required="override-price"):
        """Code shared between sales made through stocklines and PLUs to check
        whether the user has entered a valid price override.
        """
        explicitprice = strtoamount(buf)
        if explicitprice == zero:
            ui.infopopup(
                ["You can't override the price of an item to be zero.  "
                 "You should use the {} key instead to say why we're "
                 "giving this item away.".format(
                     keyboard.K_WASTE.keycap)],
                title="Zero price not allowed")
            return
        if not self.user.may(permission_required):
            ui.infopopup(
                ["You don't have permission to override the price of "
                 "this item to {}.  Did you mean to press the {} key "
                 "to enter a number of items instead?".format(
                     tillconfig.fc(explicitprice),
                     keyboard.K_QUANTITY.keycap)],
                title="Permission required")
            return
        if department.minprice and explicitprice < department.minprice:
            ui.infopopup(
                ["Your price of {} per item is too low for {}.  "
                 "Did you mean to press the {} key to enter a number "
                 "of items instead?".format(
                     tillconfig.fc(explicitprice),
                     department.description,
                     keyboard.K_QUANTITY.keycap)],
                title="Price too low")
            return
        if department.maxprice and explicitprice > department.maxprice:
            ui.infopopup(
                ["Your price of {} per item is too high for {}.".format(
                    tillconfig.fc(explicitprice),
                    department.description)],
                title="Price too high")
            return
        log.info("Register: manual price override to %s by %s",
                 explicitprice, self.user.fullname)
        return explicitprice

    @user.permission_required('sell-plu', 'Sell items using a price lookup')
    def _sell_plu(self, kb, mod):
        plu = kb.plu

        items = self.qty or 1
        mod = self.mod or mod # self.mod is an override of the default
        buf = self.buf
        self.clearbuffer()
        self._redraw()

        # If we are repeating a PLU button press, we don't have to do
        # many of the usual checks.  If it's the same PLU again, just
        # increase the number of items
        may_repeat = hasattr(self.repeat, 'plu') \
                     and self.repeat.plu == plu.id \
                     and self.repeat.mod == mod

        trans = self.get_open_trans() # Zaps self.repeat
        if not trans:
            return # Will already be displaying an error.

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
                return # Error popup already in place

        # If we are dealing with a repeat press on the PLU line key, skip
        # all the remaining checks and just increase the number of items
        if may_repeat and len(self.dl) > 0 and \
           self.dl[-1].age() < max_transline_modify_age:
            otl = td.s.query(Transline).get(self.dl[-1].transline)
            otl.items = otl.items + 1
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

        # Pass the proposed sale to the modifier to let it change it or reject it
        if mod:
            try:
                with ui.exception_guard(
                        "running the '{}' modifier".format(mod.name),
                        suppress_exception=False):
                    try:
                        mod.mod_plu(plu, sale)
                        sale.validate()
                    except modifiers.Incompatible as i:
                        msg = "The '{}' modifier can't be used with " \
                              "the '{}' price lookup." \
                              .format(mod.name, plu.description)
                        ui.infopopup([i.msg if i.msg else msg],
                                     title="Incompatible modifier",
                                     colour=ui.colour_error)
                        return
                    except InvalidSale as i:
                        ui.infopopup(
                            ["The '{}' modifier left the Proposed Sale object "
                             "in an invalid state.  This is an error in the "
                             "till configuration.  The invalid state is: {}"
                             .format(mod.name, i.msg)],
                            title="Till configuration error")
                        return
            except Exception as e:
                # ui.exception_guard() will already have popped up the error.
                return

        # If we have an explicit price, apply it now
        if explicitprice:
            sale.price = explicitprice

        # If we still don't have a price, we can't continue
        if sale.price is None:
            if self.user.may('sell-dept'):
                msg = "'{}' doesn't have a price set.  You must enter a " \
                      "price before choosing the item.".format(plu.description)
            else:
                msg = "This item doesn't have a price set, and you don't have " \
                      "permission to override it.  You must ask your manager " \
                      "to set a price on the item before you can sell it."
                ui.infopopup([msg], title="Price not set")
            return

        tl = Transline(transaction=trans, items=items, amount=sale.price,
                       department=plu.department, user=self.user.dbuser,
                       transcode='S', text=sale.description)
        td.s.add(tl)
        td.s.flush()
        td.s.refresh(tl, ['time']) # load time from database
        self.dl.append(tline(tl.id))
        self.repeat = repeatinfo(plu=plu.id, mod=mod)
        td.s.expire(trans, ['total'])
        self._clear_marks()
        self.update_balance()
        self.cursor_off()
        self._redraw()

    @user.permission_required('sell-stock', 'Sell stock from a stockline')
    def _sell_stockline(self, kb, mod):
        stockline = kb.stockline
        mod = self.mod or mod # self.mod is an override of the default
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
                ["No stock is registered for {}.".format(stockline.name),
                 "To tell the till about stock on sale, "
                 "press the '{}' button after "
                 "dismissing this message.".format(keyboard.K_USESTOCK.keycap)],
                title="{} has no stock".format(stockline.name))
            return
        sale = ProposedSale(
            stocktype=st,
            qty=st.saleprice_units,
            description=st.format() + (
                " {}".format(st.unit.name) if st.saleprice_units == 1 else ""),
            price=st.saleprice,
            whole_items=(stockline.linetype == "display"))

        sale.validate()

        # Pass the proposed sale to the modifier to let it change it or reject it
        if mod:
            try:
                with ui.exception_guard(
                        "running the '{}' modifier".format(mod.name),
                        suppress_exception=False):
                    try:
                        mod.mod_stockline(stockline, sale)
                        sale.validate()
                    except modifiers.Incompatible as i:
                        msg = "The '{}' modifier can't be used with " \
                              "the '{}' stockline." \
                              .format(mod.name, stockline.name)
                        ui.infopopup([i.msg if i.msg else msg],
                                     title="Incompatible modifier",
                                     colour=ui.colour_error)
                        return
                    except InvalidSale as i:
                        ui.infopopup(
                            ["The '{}' modifier left the Proposed Sale object "
                             "in an invalid state.  This is an error in the "
                             "till configuration.  The invalid state is: {}"
                             .format(mod.name, i.msg)],
                            title="Till configuration error")
                        return
            except Exception as e:
                # ui.exception_guard() will already have popped up the error.
                return

        explicitprice = None
        if buf:
            explicitprice = self._read_explicitprice(
                buf, sale.stocktype.department)
            if not explicitprice:
                return # Error popup already in place

        if not explicitprice:
            if sale.price is None:
                no_saleprice_popup(self.user, sale.stocktype)
                return

        if explicitprice:
            sale.price = explicitprice

        total_qty = items * sale.qty
        sell, unallocated, remaining = stockline.calculate_sale(
            total_qty)

        # This _should_ only be the case with display stocklines.
        if unallocated > 0:
            ui.infopopup(
                ["There are fewer than {} items of {} on display.  "
                 "If you have recently put more stock on display you "
                 "must tell the till about it using the 'Use Stock' "
                 "button after dismissing this message.".format(
                        total_qty, stockline.name)],
                title="Not enough stock on display")
            return
        if len(sell) == 0:
            log.info("linekey: no stock in use for %s", stockline.name)
            ui.infopopup(
                ["No stock is registered for {}.".format(stockline.name),
                 "To tell the till about stock on sale, "
                 "press the '{}' button after "
                 "dismissing this message.".format(keyboard.K_USESTOCK.keycap)],
                title="{} has no stock".format(stockline.name))
            return

        # NB get_open_trans() may call _clear() and will zap self.repeat when
        # it creates a new transaction!
        may_repeat = self.repeat and hasattr(self.repeat, 'stocklineid') \
                     and self.repeat.stocklineid == stockline.id \
                     and self.repeat.mod == mod

        trans = self.get_open_trans()
        if trans is None:
            return # Will already be displaying an error.

        # Consider adding on to the previous transaction line if the
        # same stockline key has been pressed again.
        repeated = False
        if may_repeat and len(self.dl) > 0 \
           and self.dl[-1].age() < max_transline_modify_age \
           and len(sell) == 1:
            otl = td.s.query(Transline).get(self.dl[-1].transline)
            # If the stockref has more than one item, we don't repeat
            # because we are probably at the changeover between two
            # stockitems
            if otl.stockref \
               and otl.stockref[0].stockitem == sell[0][0] \
               and len(otl.stockref) == 1:
                # It's the same stockitem.  Add one item and one qty.
                so = otl.stockref[0]
                orig_stockqty = so.qty / otl.items
                if orig_stockqty == sell[0][1]:
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
                ui.infopopup(
                    ["According to the till records, {} hasn't been "
                     "sold or pulled through in the last 11 hours.  "
                     "Would you like to record that you've pulled "
                     "through {} {}s?".format(
                         item.stocktype.format(),
                         stockline.pullthru,
                         item.stocktype.unit.name),
                     "",
                     "Press '{}' if you do, or {} if you don't.".format(
                         keyboard.K_WASTE.keycap,
                         keyboard.K_CLEAR.keycap)],
                    title="Pull through?", colour=ui.colour_input,
                    keymap={
                        keyboard.K_WASTE:
                        (record_pullthru, (item.id, stockline.pullthru),
                         True)})

        if not repeated:
            tl = Transline(
                transaction=trans, items=items,
                amount=sale.price,
                department=sale.stocktype.department,
                transcode='S', text=sale.description,
                user=self.user.dbuser)
            td.s.add(tl)
            for stockitem, items_to_sell in sell:
                so = StockOut(
                    transline=tl, stockitem=stockitem,
                    qty=items_to_sell, removecode_id='sold')
                td.s.add(so)
                td.s.expire(
                    stockitem,
                    ['used', 'sold', 'remaining', 'firstsale', 'lastsale'])
            td.s.flush()
            td.s.refresh(tl, ['time']) # load time from database
            self.dl.append(tline(tl.id))

        self.repeat = repeatinfo(stocklineid=stockline.id, mod=mod)

        if stockline.linetype == "regular":
            # We are using the last value of so from either the
            # previous for loop, or the handling of may_repeat
            stockitem = so.stockitem
            self.prompt = "{}: {} {}s of {} remaining".format(
                stockline.name, stockitem.remaining,
                stockitem.stocktype.unit.name, stockitem.stocktype.format())
            if stockitem.remaining < Decimal("0.0"):
                ui.infopopup([
                    "There appears to be {} {}s of {} left!  Please "
                    "check that you're still using stock item {}; if you've "
                    "started using a new item, tell the till about it "
                    "using the '{}' button after dismissing this "
                    "message.".format(
                        stockitem.remaining,
                        stockitem.stocktype.unit.name,
                        stockitem.stocktype.format(),
                        stockitem.id,
                        keyboard.K_USESTOCK.keycap),
                    "", "If you don't understand this message, you MUST "
                    "call your manager to deal with it."],
                             title="Warning", dismiss=keyboard.K_USESTOCK)
        elif stockline.linetype == "display":
            self.prompt = "{}: {} left on display; {} in stock".format(
                stockline.name, int(remaining[0]), int(remaining[1]))
        elif stockline.linetype == "continuous":
            self.prompt = "{}: {} {}s of {} remaining".format(
                stockline.name, remaining, stockline.stocktype.unit.name,
                stockline.stocktype.format())
            if remaining < Decimal("0.0"):
                ui.infopopup([
                    "There appears to be {} {}s of {} left!  Please "
                    "check that you're still using {}; if you've "
                    "started using a new type of stock, tell the till "
                    "about it by changing the stock type of the "
                    "'{}' stock line after dismissing this message.".format(
                        remaining,
                        stockline.stocktype.unit.name,
                        stockline.stocktype.format(),
                        stockline.stocktype.format(),
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
        """Accept multiple transaction lines from an external source.

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
        for dept, text, items, amount in lines:
            tl = Transline(transaction=trans, dept_id=dept,
                           items=items, amount=amount,
                           transcode='S', text=text, user=self.user.dbuser)
            td.s.add(tl)
            td.s.flush()
            log.info("Register: deptlines: trans=%d,lid=%d,dept=%d,"
                     "price=%f,text=%s"%(trans.id, tl.id, dept, amount, text))
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
        transaction's payments section using the default payment
        method; the intent is that staff who are offered a drink that
        they don't want to pour immediately can use this key to enable
        the till to add the cost of their drink onto a transaction.
        They can take the cash from the till tray or make a note that
        it's in there, and use it later to buy a drink.

        This only works if the default payment method supports change.
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
        if len(tillconfig.payment_methods) < 1:
            self._redraw()
            ui.infopopup(["There are no payment methods configured."],
                         title="Error")
            return
        pm = tillconfig.payment_methods[0]
        if not pm.change_given:
            self._redraw()
            ui.infopopup(["The %s payment method doesn't support change."%
                          pm.description], title="Error")
            return
        p = pm.add_change(trans, description="Drink 'In'", amount=-amount)
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
                    ui.toast("No Sale has been recorded.")
                    printer.kickout()
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
            td.s.delete(trans)
            self.transid = None
            td.s.flush()
            self._clear()
            self._redraw()
            return

        # We now consider using the default payment method.  This is only
        # possible if there is one!
        if len(tillconfig.payment_methods) < 1:
            ui.infopopup(["There are no payment methods configured."],
                         title="Error")
            return
        pm = tillconfig.payment_methods[0]

        # If any of the transaction's existing payments are pending,
        # pop up a menu allowing them to be resumed.
        ml = [(p.description(), p.resume, (self,))
              for p in self.dl
              if hasattr(p, 'is_pending')
              and p.is_pending()]
        log.debug("Pending payments: %s", ml)
        if ml:
            ui.menu(
                ml, blurb="This transaction has one or more pending payments."
                "  Choose a payment to resume from this list.  If you would "
                "like to add a new payment, dismiss this menu and then "
                "press Manage Transaction, choose option 6, then choose "
                "the type of payment to take.",
                title="Resume pending payment")
            return
        # If the transaction is an old one (i.e. the "recall
        # transaction" function has been used on it) then require
        # confirmation - one of the most common user errors is to
        # recall a transaction that's being used as a tab, add some
        # lines to it, and then automatically press 'cash'.
        #
        # We do this by opening the payment methods menu.
        if self.keyguard:
            self._payment_method_menu(title="Choose payment method for this transaction")
            return
        self.paymentkey(pm)

    def _payment_method_menu(self, title="Payment methods"):
        ui.automenu([(m.description, self.paymentkey, (m,))
                     for m in tillconfig.payment_methods],
                    title=title, spill="keymenu")

    @user.permission_required("take-payment", "Take a payment")
    def paymentkey(self, method):
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
        self.prompt = self.defaultprompt
        self.balance = trans.balance
        if self.buf:
            amount = strtoamount(self.buf)
            if self.balance < zero:
                amount = zero - amount # refund amount
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
            ui.infopopup(["You can't pay {}!".format(tillconfig.fc(zero)),
                          'If you meant "exact amount" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'], title="Error")
            return
        # We have a non-zero amount and we're happy to proceed.  Pass
        # to the payment method.
        method.start_payment(self, trans.id, amount, self.balance)

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
        if (not self.buf and self.qty == None and
            trans and trans.closed):
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
        if (not self.buf and self.qty == None and
            trans and trans.closed):
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
        if not trans:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key, or print any transaction "
                          "if you have its number using the option under "
                          "'Manage Till'."], title="Error")
            return
        log.info("Register: printing transaction %d", trans.id)
        ui.toast("The receipt is being printed.")
        printer.print_receipt(trans.id)

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
            if not closed and (
                    self.keyguard or 
                    (len(self.dl) > 0 and
                     self.dl[0].age() > max_transline_modify_age)):
                log.info("Register: cancelkey kill transaction denied")
                ui.infopopup(
                    ["This transaction is old; you can't cancel it all in "
                     "one go.  Cancel each line separately instead."],
                    title="Cancel Transaction")
                return
            log.info("Register: cancelkey confirm kill "
                     "transaction %d", trans.id)
            ui.infopopup(["Are you sure you want to {} all of "
                          "transaction number {}?  Press Cash/Enter "
                          "to confirm, or Clear to go back.".format(
                              ("cancel", "void")[closed], trans.id)],
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
            log.info("Register: cancelline: can't cancel payments")
            ui.infopopup(["You can't cancel payments.  Cancel the whole "
                          "transaction instead."],title="Cancel")

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
            self._payment_method_menu(
                title="Choose refund type, or press Clear to add more items")
        else:
            if not self.user.may("cancel-line-in-open-transaction"):
                ui.infopopup(
                    ["You don't have permission to cancel lines in an open "
                     "transaction."],
                    title="Not allowed")
                return
            can_delete = all(l.age() <= max_transline_modify_age for l in tl)
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
        if trans.closed:
            log.info("Register: cancel closed transaction %d", trans.id)
            tl = self.dl
            self._clear()
            trans = self.get_open_trans()
            if not trans:
                return
            self._void_lines([ l for l in tl if isinstance(l, tline) ])
            self.cursor_off()
            self.update_balance()
            self._redraw()
            self._payment_method_menu(
                title="Choose refund type, or press Clear to add more items")
        else:
            # Delete this transaction and everything to do with it
            tn = trans.id
            log.info("Register: cancel open transaction %d" % tn)
            payments = trans.payments_total
            # Payment, Transline and StockOut objects should be deleted
            # implicitly in cascade
            td.s.delete(trans)
            self.transid = None
            td.s.flush()
            if payments > zero:
                printer.kickout()
                refundtext = "{} had already been put in the " \
                             "cash drawer.".format(tillconfig.fc(payments))
            else:
                refundtext = ""
            self._clear()
            self._redraw()
            ui.infopopup(
                ["Transaction number {} has been cancelled.  {}".format(
                    tn, refundtext)],
                title="Transaction Cancelled",
                dismiss=keyboard.K_CASH)

    def cancelline(self, l):
        if not self.entry():
            return
        if l.age() < max_transline_modify_age:
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
        tl = td.s.query(Transline).get(l.transline)
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
                if tl.transline == voided_line.id:
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
        tll = [ td.s.query(Transline).get(l.transline) for l in ll ]
        voidlines = [ transline.void(trans, self.user.dbuser)
                      for transline in tll ]
        voidlines = [ x for x in voidlines if x ]
        td.s.add_all(voidlines)
        td.s.flush() # get transline IDs, fill in voided_by
        for ntl in voidlines:
            self.dl.append(tline(ntl.id))
        for l in ll:
            l.update()

    def markkey(self):
        """The Mark key was pressed.

        If there's no line currently selected, pops up a help box.

        If a payment line is selected, pops up an error box.

        If a non-voided transaction line is selected, toggles the
        selection status of that line and updates the prompt.
        """
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
        self.user.dbuser = td.s.query(User).get(self.user.userid)
        self.user.dbuser.transaction = None
        td.s.flush()
        self.deselect()

    def recalltrans(self, transid):
        # We refresh the user object as if in enter() here, but don't
        # bother with the full works because we're replacing the current
        # transaction anyway!
        self.user.dbuser = td.s.query(User).get(self.user.userid)
        self._clear()
        self._redraw()
        if transid:
            log.info("Register: recalltrans %d", transid)
            trans = td.s.query(Transaction).get(transid)
            if not trans:
                ui.infopopup(["Transaction {} does not exist.".format(transid)],
                             title="Error")
                return
            # Leave a message if the transaction belonged to another
            # user.
            user = td.s.query(User).filter(User.transaction == trans).first()
            if user:
                user.transaction = None
                user.message = "Your transaction {} ({}) was taken over by {} " \
                               "using the Recall Transaction function.".format(
                                   trans.id, trans.notes or "no notes",
                                   self.user.fullname)
            self._loadtrans(trans.id)
            self.keyguard = True
            self.close_if_balanced()
            if not trans.closed:
                age = trans.age
                if age > datetime.timedelta(days=2):
                    ui.infopopup(["This transaction is {} days old.  Please "
                                  "arrange for it to be paid soon.".format(age.days)],
                                 title="Warning")
        self.cursor_off()
        self.update_balance()
        self._redraw()

    @user.permission_required("recall-trans", "Change to a different "
                              "transaction")
    def recalltranskey(self):
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
        transactions = td.s.query(Transaction).\
                       filter(Transaction.session == sc).\
                       options(td.undefer('total')).\
                       options(td.joinedload('user')).\
                       order_by(Transaction.closed == True).\
                       order_by(desc(Transaction.id)).\
                       all()
        f = ui.tableformatter(' r l r l l ')
        sl = [(f(x.id, ('open', 'closed')[x.closed],
                 tillconfig.fc(x.total),
                 x.user.shortname if x.user else "", x.notes),
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
            ui.infopopup(["Transaction {} has been closed, and cannot now "
                          "be deferred.".format(trans.id)], title="Error")
            return
        amount = trans.payments_total
        if amount != zero:
            # Check that there is a default payment method
            if len(tillconfig.payment_methods) < 1:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  There is no default "
                     "payment method so this can't be done now."],
                    title="Error")
                return
            pm = tillconfig.payment_methods[0]
            # The payment method must support both change and refunds
            if not pm.change_given or not pm.refund_supported:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  The default payment "
                     "method does not support this."],
                    title="Error")
                return
            # Refund the amount paid so far and ask the user to set it aside
            # XXX consider printing out a ticket on the receipt printer
            # to be stored with the money.
            pm.add_change(trans, "Deferred", zero - amount)
            printer.kickout()
        transid = trans.id
        trans.session = None
        td.s.flush()
        self._clear()
        self._redraw()
        message = ["Transaction {} has been deferred to the next "
                   "session.  Make sure you keep a note of the "
                   "transaction number and the name of the person "
                   "responsible for paying it!".format(transid)]
        if amount:
            message = message \
                      + ["", "{} had been paid towards this transaction. "
                         "You must remove this amount from the till and "
                         "set it aside to be used to pay off the "
                         "transaction in a later session.".format(
                             tillconfig.fc(amount))]
        ui.infopopup(message,
                     title="Transaction defer confirmed",
                     colour=ui.colour_confirm, dismiss=keyboard.K_CASH)

    @user.permission_required("convert-to-free-drinks",
                              "Convert a transaction to free drinks")
    def freedrinktrans(self):
        """Convert the current transaction to free drinks."""
        if not self.entry():
            return
        trans = self._gettrans()
        if not trans:
            ui.infopopup(["There is no current transaction."],
                         title="Error")
            return
        if trans.closed:
            ui.infopopup(["The transaction is already closed."],
                         title="Error")
            return
        if len(trans.payments) > 0:
            ui.infopopup(["This transaction has already had payments entered "
                          "against it, so cannot be converted to free drinks."],
                         title="Error")
            return
        if not trans.notes or "free" not in trans.notes.lower():
            ui.infopopup(
                ["The transaction notes must include the word 'free' "
                 "before the transaction can be converted to free drinks.",
                 "", "This is a protective measure to try to ensure you don't "
                 "convert the wrong transaction.  Conversion of a transaction "
                 "to free drinks cannot be reversed."],
                title="Transaction not labelled for free drinks")
            return
        freebie = td.s.query(RemoveCode).get('freebie')
        if not freebie:
            ui.infopopup(["The database does not include a 'free drink' "
                          "waste code."], title="Error")
            return
        for l in trans.lines:
            for sr in l.stockref:
                sr.removecode = freebie
                sr.transline = None
        # Flush the changes to the database now, so that the stockout
        # objects are not deleted in the cascade from deleting the
        # transaction
        td.s.flush()
        td.s.refresh(trans) # remove references to stockout objects
        td.s.delete(trans)
        td.s.flush()
        self._clear()
        self._redraw()
        ui.infopopup(["Transaction has been converted to free drinks."],
                     title="Free drinks", colour=ui.colour_confirm,
                     dismiss=keyboard.K_CASH)

    def _check_session_and_open_transaction(self):
        # For transaction merging
        if not self.entry():
            return False
        sc = Session.current(td.s)
        if not sc:
            ui.infopopup(["There is no session active."], title="Error")
            return False
        trans = self._gettrans()
        if not trans:
            ui.infopopup(["There is no current transaction."], title="Error")
            return False
        if trans.closed:
            ui.infopopup(["The current transaction is closed and can't "
                          "be merged with another transaction."],
                         title="Error")
            return False
        return sc

    @user.permission_required("merge-trans", "Merge two transactions")
    def mergetransmenu(self):
        sc = self._check_session_and_open_transaction()
        if not sc:
            return
        tl = [t for t in sc.transactions if not t.closed]
        f = ui.tableformatter(' r r l ')
        sl = [(f(x.id, tillconfig.fc(x.total), x.notes or ""),
               self._mergetrans, (x.id,)) for x in tl if x.id != self.transid]
        ui.menu(sl,
                title="Merge with transaction",
                blurb="Select a transaction to merge this one into, "
                "and press Cash/Enter.",
                colour=ui.colour_input)

    def _mergetrans(self, othertransid):
        sc = self._check_session_and_open_transaction()
        if not sc:
            return
        trans = self._gettrans()
        othertrans = td.s.query(Transaction).get(othertransid)
        if len(trans.payments) > 0:
            ui.infopopup(
                ["Some payments have already been entered against "
                 "transaction {}, so it can't be merged with another "
                 "transaction.".format(trans.id)],
                title="Error")
            return
        if othertrans.closed:
            ui.infopopup(
                ["Transaction {} has been closed, so we can't "
                 "merge this transaction into it.".format(othertrans.id)],
                title="Error")
            return
        # Leave a message if the other transaction belonged to another
        # user.
        user = td.s.query(User).filter(User.transaction == othertrans).first()
        if user:
            user.transaction = None
            user.message = "Your transaction {} ({}) was taken over by {} " \
                           "when they merged another transaction into it." \
                           .format(
                               othertrans.id, othertrans.notes or "no notes",
                               self.user.fullname)
        for line in list(trans.lines):
            line.transaction = othertrans
        td.s.delete(trans)
        td.s.flush()
        td.s.expire(othertrans)
        self._loadtrans(othertrans.id)

    def _splittrans(self, notes):
        if not self.entry():
            return
        if not self.ml:
            return
        trans = self._gettrans()
        # Create a new transaction with the supplied notes
        nt = Transaction(session=trans.session, notes=notes)
        td.s.add(nt)
        for l in self.ml:
            t = td.s.query(Transline).get(l.transline)
            t.transaction = nt
            del self.dl[self.dl.index(l)]
        td.s.flush()
        td.s.expire(trans, ['total'])
        self._clear_marks()
        self.cursor_off()
        self.update_balance()
        self._redraw()
        ui.infopopup(["The selected lines were moved to a new transaction, "
                      "number {}, called '{}'.  You can find it using the "
                      "Recall Trans button.".format(nt.id, nt.notes)],
                     title="Transaction split", colour=ui.colour_info,
                     dismiss=keyboard.K_CASH)

    def settransnote(self, notes):
        if not self.entry():
            return
        trans = self._gettrans()
        if not trans or trans.closed:
            return
        trans.notes = notes
        self._redraw_note()

    def managetranskey(self):
        trans = self._gettrans()
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
                ("2", "Convert transaction to free drinks",
                 self.freedrinktrans, None),
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
        menu.append(("8", "Recall a transaction by number",
                     recalltranspopup, (self,)))
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
        self.user.dbuser = td.s.query(User).get(self.user.userid)

        # This check has already been done in hotkeypress().  We
        # repeat it here because it is possible we may not have been
        # entered in response to a keypress - a timer event, for
        # example.
        if self.user.dbuser.register != register_instance:
            # If the register in the database isn't us, lock immediately
            self.deselect()
            return False

        # If there is a message queued for the user, display it.  It
        # probably explains where their transaction has gone to!
        if self.user.dbuser.message:
            ui.infopopup([self.user.dbuser.message],
                         title="Transaction information")
            self._clear()
            self.user.dbuser.message = None
            td.s.flush()
            return False

        if self.transid and not self.user.dbuser.transaction:
            # Someone has taken our transaction without leaving a
            # message.  How rude!  Give them a default message.
            ui.infopopup(["Your transaction has gone away."],
                         title="Transaction gone")
            self._clear()
            td.s.flush()
            return False

        # At this point, self.transid and self.user.dbuser.transaction
        # should either both be None or both refer to the current
        # transaction.
        self.transid = self.user.dbuser.transaction.id \
                       if self.user.dbuser.transaction \
                          else None
        self._update_timeout()
        return True

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
        if hasattr(k, 'line'):
            def add_query_options(q):
                return q.options(joinedload('stockline'))\
                        .options(joinedload('stockline.stockonsale'))\
                        .options(joinedload('stockline.stockonsale.stocktype'))\
                        .options(joinedload('stockline.stocktype'))\
                        .options(joinedload('plu'))\
                        .options(undefer('stockline.stockonsale.used'))\
                        .options(undefer('stockline.stockonsale.remaining'))
            linekeys.linemenu(k, self.linekey, allow_stocklines=True,
                              allow_plus=True, allow_mods=True,
                              add_query_options=add_query_options)
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
        if k == keyboard.K_FOODORDER:
            trans = self.get_open_trans()
            if not trans:
                return
            return foodorder.popup(self.deptlines, transid=trans.id)
        if k == keyboard.K_FOODMESSAGE:
            return foodorder.message()
        ui.beep()

    def hotkeypress(self, k):
        # Fetch the current user from the database.  We don't recreate
        # the user.database_user object because that's unlikely to
        # change often; we're just interested in the transaction and
        # register fields.
        self.user.dbuser = td.s.query(User)\
                               .options(joinedload('transaction'))\
                               .get(self.user.userid)

        # Check that the user hasn't moved to another terminal.  If
        # they have, lock immediately.
        if self.user.dbuser.register != register_instance:
            self.deselect()
            return super(page, self).hotkeypress(k)

        if self._autolock and k == self._autolock and not self.locked \
           and self.s.focused:
            # Intercept the 'Lock' keypress and handle it ourselves.
            # Do this only if our scrollable has the focus.
            self.locked = True
            self._redraw()
        else:
            super(page, self).hotkeypress(k)

    def select(self, u):
        # Called when the appropriate user token is presented
        self.user = u # Permissions might have changed!
        self.user.dbuser.register = register_instance
        td.s.flush()
        if self.locked:
            self.locked = False
            self._redraw()
        ui.basicpage.select(self)
        log.info("Existing page selected for %s", self.user.fullname)
        self.entry()

    def deselect(self):
        # We might be able to delete ourselves completely after
        # deselection if none of the popups has unsaved data.  When we
        # are recreated we can reload the current transaction from the
        # database.
        focus = ui.basicwin._focus # naughty!
        self.unsaved_data = None
        while focus != self.s:
            unsaved_data = getattr(focus, 'unsaved_data', None)
            log.debug("deselect: checking %s: unsaved_data=%s",
                      focus, unsaved_data)
            if unsaved_data:
                log.info("Page for %s deselected; unsaved data (%s) so just "
                         "hiding the page", self.user.fullname, unsaved_data)
                self.unsaved_data = unsaved_data
                return ui.basicpage.deselect(self)
            focus = focus.parent
        log.info("Page for %s deselected with no unsaved data: deleting self",
                 self.user.fullname)
        ui.basicpage.deselect(self)
        self.dismiss()
        if self._timeout_handle:
            self._timeout_handle.cancel()
            self._timeout_handle = None

    def alarm(self):
        # The timeout has passed.  If the scrollable has the input
        # focus (i.e. there are no popups on top of us) we can
        # deselect.
        self._timeout_handle = None
        if self.s.focused:
            self.deselect()

def handle_usertoken(t, *args, **kwargs):
    """User token handler for the register.

    Used in the configuration file to specify what happens when a user
    token is handled by the default hotkey handler.
    """
    u = user.user_from_token(t)
    if u is None:
        return
    for p in ui.basicpage._pagelist:
        if isinstance(p, page) and p.user.userid == u.userid:
            p.select(u)
            return p
    return page(u, *args, **kwargs)
