"""
Cash register page.  Allows transaction entry, voiding of lines.

"""

# A brief word about how redrawing the screen works:
#
# There are four main areas to worry about: the screen header, the
# transaction note, the display list and the "buffer" line.
#
# The screen header shows the page header, a summary of the other
# pages, and the clock.  It needs updating whenever the current
# transaction changes: from none to present, from present to none, or
# from open to closed.  It is updated by calling self.updateheader();
# this calls pagesummary() for all pages.
#
# The transaction note shows whatever note is set for the current
# transaction.  It is updated by calling self.update_note().
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

from __future__ import unicode_literals
from . import tillconfig
import curses,textwrap
from . import td,ui,keyboard,printer
from . import stock,stocklines,stocktype
from . import payment
from . import user
import logging
import datetime
log=logging.getLogger(__name__)
from . import foodorder
from .models import Transline,Transaction,Session,StockOut,Transline,penny
from .models import Payment,zero,User,Department,desc,RemoveCode
from decimal import Decimal
from sqlalchemy.orm.exc import ObjectDeletedError
from sqlalchemy.orm import subqueryload,subqueryload_all
from sqlalchemy.orm import joinedload,joinedload_all
from sqlalchemy.orm import undefer
import uuid

max_transline_modify_age=datetime.timedelta(minutes=1)

# Permissions checked for explicitly in this module
user.action_descriptions['override-price']="Override the sale price of an item"
user.action_descriptions['nosale']="Open the cash drawer with no payment"
user.action_descriptions['suppress-refund-help-text']=(
    "Don't show the refund help text")

# Whenever the register is started it generates a new unique ID for
# itself.  This is used to distinguish register instances that are
# running at the same time, so they can coordinate moving transactions
# and users between registers.
register_instance=str(uuid.uuid4())

class bufferline(ui.lrline):
    """
    Used as the very last line on the register display - a special
    case.  Always consists of two lines; a blank line, and then a line
    showing the prompt or the contents of the input buffer at the
    left, and if appropriate the balance of the transaction on the
    right.

    """
    def __init__(self,reg):
        ui.lrline.__init__(self)
        self.cursor_colour=self.colour
        self.reg=reg
    def display(self,width):
        if self.reg.qty is not None: m="{} of ".format(self.reg.qty)
        else: m=""
        if self.reg.mod is not None: m=m+"{} ".format(self.reg.mod.keycap)
        if self.reg.buf is not None: m=m+self.reg.buf
        if len(m)>0:
            self.ltext=m
            cursorx=len(m)
        else:
            self.ltext="Locked" if self.reg.locked else self.reg.prompt
            cursorx=0
            if self.reg.balance<zero and not self.reg.user.has_permission(
                'suppress-refund-help-text'):
                self.ltext=(
                    "This transaction has a negative balance, so a "
                    "refund is due.  Press the appropriate payment key "
                    "to issue a refund of that type.  If you are replacing "
                    "items for a customer you can enter the replacement "
                    "items now; the till will show the difference in price "
                    "between the original and replacement items.")
        self.rtext="{} {}".format(
            "Amount to pay" if self.reg.balance>=zero else "Refund amount",
            tillconfig.fc(self.reg.balance)) if self.reg.balance!=zero else ""
        # Add the expected blank line
        l=['']+ui.lrline.display(self,width)
        self.cursor=(cursorx,len(l)-1)
        return l

class tline(ui.lrline):
    """
    A transaction line; corresponds to a transaction line in the database.

    """
    def __init__(self,transline):
        ui.lrline.__init__(self)
        self.transline=transline
        self.update()
    def update(self):
        tl=td.s.query(Transline).get(self.transline)
        self.transtime=tl.time
        self.ltext=tl.description
        self.rtext=tl.regtotal(tillconfig.currency)
    def age(self):
        return datetime.datetime.now() - self.transtime
    def update_mark(self,ml):
        if self.transline in ml:
            self.colour=curses.color_pair(ui.colour_cancelline)
        else:
            self.colour=curses.color_pair(0)
        self.cursor_colour=self.colour|curses.A_REVERSE

class edittransnotes(ui.dismisspopup):
    """A popup to allow a transaction's notes to be edited."""
    def __init__(self,trans,func):
        td.s.add(trans)
        self.transid=trans.id
        self.func=func
        ui.dismisspopup.__init__(
            self,5,60,title="Notes for transaction {}".format(trans.id),
            colour=ui.colour_input)
        notes=trans.notes if trans.notes else ''
        self.notesfield=ui.editfield(2,2,56,f=notes,flen=60,keymap={
                keyboard.K_CASH:(self.enter,None)})
        self.notesfield.focus()
    def enter(self):
        notes=self.notesfield.f
        self.dismiss()
        self.func(notes)

def strtoamount(s):
    if s.find('.')>=0:
        return Decimal(s).quantize(penny)
    return int(s)*penny

def no_saleprice_popup(user,item):
    """
    Pop up an appropriate error message for an item of stock with a
    missing sale price.  Offer to let the user set it if they have the
    appropriate permissions.

    """
    if user.has_permission('override-price') and \
            user.has_permission('reprice-stock'):
        ist=item.stocktype
        ui.infopopup(
            ["No sale price has been set for {}.  You can enter a price "
             "before pressing the line key to set the price just this once, "
             "or you can press {} now to set the price permanently.".format(
                    item.stocktype.format(),
                    keyboard.K_MANAGESTOCK.keycap)],
            title="Unpriced item found",keymap={
                keyboard.K_MANAGESTOCK: (
                    lambda:stocktype.reprice_stocktype(ist),
                    None,True)})
    elif user.has_permission('override-price'):
        ui.infopopup(
            ["No sale price has been set for {}.  You can enter a price "
             "before pressing the line key to set the price just this once.".\
                 format(item.stocktype.format())],
            title="Unpriced item found")
    else:
        ui.infopopup(
            ["No sale price has been set for {}.  You must ask a manager "
             "to set a price for it before you can sell it.".format(
                    item.stocktype.format())],
            title="Unpriced item found")

def record_pullthru(stockid,qty):
    td.s.add(StockOut(stockid=stockid,qty=qty,removecode_id='pullthru'))
    td.s.flush()

class repeatinfo(object):
    """
    Information for repeat keypresses.

    """
    def __init__(self,**kwargs):
        for k,v in kwargs.iteritems():
            setattr(self,k,v)

class page(ui.basicpage):
    def __init__(self,user,hotkeys,autolock=None):
        # trans and name needed for "pagename" which is called in basicpage.__init__()
        self.trans=None # models.Transaction object
        self.user=user
        log.info("Page created for %s",self.user.fullname)
        ui.basicpage.__init__(self)
        self._autolock=autolock
        self.locked=False
        self.h=self.h-1 # XXX hack to avoid drawing into bottom right-hand cell
        self.hotkeys=hotkeys
        self.defaultprompt="Ready"
        # Set user's current register to be us
        self.user.dbuser.register=register_instance
        # Save user's current transaction because it is unset by clear()
        candidate_trans=self.user.dbuser.transaction
        self._clear()
        self.s=ui.scrollable(1,0,self.w,self.h-1,self.dl,
                             lastline=bufferline(self))
        self.s.focus()
        if candidate_trans is not None:
            session=Session.current(td.s)
            if candidate_trans.session==session:
                # It's a transaction in the current session - load it
                self._loadtrans(candidate_trans)
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
                self.user.dbuser.message=None
        td.s.flush()
        self._redraw()
    def clearbuffer(self):
        """
        Clear user input from the buffer.  Doesn't reset the prompt or
        current balance.

        """
        self.buf="" # Input buffer
        self.qty=None # Quantity (integer)
        self.mod=None # Modifier (modkey object)
    def _clear(self):
        """
        Reset this page to having no current transaction and nothing
        in the input buffer.  Note that this does not cause a redraw;
        various functions may want to fiddle with the state (for example
        loading a previous transaction) before requesting a redraw.

        """
        self.dl=[] # Display list
        if hasattr(self,'s'):
            self.s.set(self.dl) # Tell the scrollable about the new display list
        self.ml=set() # Marked transactions set
        self.trans=None # Current transaction
        self.user.dbuser.transaction=None
        self.repeat=None # If dept/line button pressed, update this transline
        self.keyguard=False
        self.clearbuffer()
        self.balance=zero # Balance of current transaction
        self.prompt=self.defaultprompt
        self.update_note()
        td.s.flush()
    def _loadtrans(self,trans):
        """
        Load a transaction, overwriting all our existing state.  The
        transaction object is assumed already to be mapped.

        """
        log.debug("Register: loadtrans %s",trans)
        # Reload the transaction and its related objects
        trans=td.s.query(Transaction).\
               filter_by(id=trans.id).\
               options(subqueryload_all('payments')).\
               options(joinedload_all('lines.stockref.stockitem.stocktype')).\
               options(joinedload('lines.user')).\
               options(undefer('total')).\
               one()
        self.trans=trans
        self.user.dbuser.transaction=trans
        self.dl=[tline(l.id) for l in trans.lines]+\
            [payment.pline(i) for i in trans.payments]
        self.s.set(self.dl)
        self.ml=set()
        self.update_note()
        self.close_if_balanced()
        self.repeat=None
        self.update_balance()
        self.prompt=self.defaultprompt
        self.keyguard=False
        self.clearbuffer()
        self.cursor_off()
        td.s.flush()
        self._redraw()
    def pagename(self):
        if self.trans is None: return self.user.shortname
        try:
            td.s.add(self.trans)
            return "{0} - Transaction {1} ({2})".format(
                self.user.shortname,self.trans.id,
                ("open","closed")[self.trans.closed])
        except ObjectDeletedError:
            return self.user.shortname
    def pagesummary(self):
        if self.trans is None: return ""
        try:
            td.s.add(self.trans)
            if self.trans.closed: return ""
            return "{0}:{1}".format(self.user.shortname,self.trans.id)
        except ObjectDeletedError:
            # NB the ObjectDeletedError won't happen during the add(),
            # it'll happen on the first database access to refresh the
            # object.
            return ""
    def _redraw(self):
        """
        Updates the screen, scrolling until the cursor is visible.

        """
        self.s.redraw()
        self.updateheader()
    def update_note(self):
        note=self.trans.notes if self.trans is not None else None
        if note is None: note=""
        note=note+" "*(self.w-len(note))
        c=self.win.getyx()
        self.win.addstr(0,0,note,ui.curses.color_pair(ui.colour_changeline))
        self.win.move(*c)
    def cursor_off(self):
        # Returns the cursor to the buffer line.  Does not redraw (because
        # the caller is almost certainly going to do other things first).
        self.s.cursor=len(self.dl)
    def update_balance(self):
        if self.trans:
            self.balance=self.trans.balance
        else: self.balance=zero
    def close_if_balanced(self):
        if (self.trans and not self.trans.closed and (
                self.trans.lines or self.trans.payments)
            and self.trans.total==self.trans.payments_total):
            self.trans.closed=True
            td.s.flush()
            if self._autolock: self.locked=True
    @user.permission_required('sell-stock','Sell stock from a stockline')
    def linekey(self,kb): # We are passed the keyboard binding
        # We may be being called back from a stocklinemenu here, so
        # repeat the entry() procedure to make sure we still have the
        # transaction.
        if not self.entry(): return
        td.s.add(kb)
        stockline=kb.stockline
        # Size of unit of stock to sell, eg. 1.0 or 0.5
        stockqty=kb.qty if stockline.linetype!="display" else 1

        # Note that stockqty is separate from self.qty which is the
        # number of these units that we sell.
        items=self.qty or 1

        # Cache the bufferline contents, clear it and redraw - this
        # saves us having to do so explicitly when we bail with an
        # error
        mod=self.mod
        buf=self.buf
        self.clearbuffer()
        self._redraw()

        # Work out what we need to do to sell this many items.  At
        # this point we don't care what stockqty is; if we're counting
        # individual items on a "display" stockline then it will be 1,
        # and if we're on a "regular" stockline it won't affect the
        # result.
        sell,unallocated,stockremain=stocklines.calculate_sale(
            stockline.id,items)

        if stockline.linetype=="display" and unallocated>0:
            ui.infopopup(
                ["There are fewer than {} items of {} on display.  "
                 "If you have recently put more stock on display you "
                 "must tell the till about it using the 'Use Stock' "
                 "button after dismissing this message.".format(
                        items,stockline.name)],
                title="Not enough stock on display")
            return
        if len(sell)==0:
            log.info("linekey: no stock in use for %s",stockline.name)
            ui.infopopup(["No stock is registered for {}.".format(
                        stockline.name),
                          "To tell the till about stock on sale, "
                          "press the '{}' button after "
                          "dismissing this message.".format(
                        keyboard.K_USESTOCK.keycap)],
                         title="{} has no stock".format(stockline.name))
            return
        # All of the items are guaranteed to be in the same
        # department, so we only need to look at the first one.
        department=sell[0][0].stocktype.department

        # Modifier processing.  Modifiers alter the stockqty,
        # overriding the qty from the keyboard binding.  Modifiers are
        # restricted to work on particular unit types and regular
        # stocklines only.
        if mod:
            if stockline.linetype!='regular':
                ui.infopopup(["You can only use modifiers with regular "
                              "stocklines; they don't work with lines "
                              "on display."],title="Error")
                return
            # Check that all the items in the sale list have
            # compatible unit types.
            for item,qty in sell:
                if item.stockunit.unit.id not in mod.unittypes:
                    ui.infopopup(
                        ["You can't use the '{}' modifier with stock that's "
                         "sold in {}s.".format(
                                mod.keycap,item.stockunit.unit.name)],
                        title="Incompatible modifier")
                    self.clearbuffer()
                    self._redraw()
                    return
            stockqty=mod.qty

        # Work out what price we're supposed to be selling it for.  If
        # any of the stocktypes don't have a price, a price override
        # is necessary.  (Multiple stocktypes may be involved if the
        # line is a "display" line.)
        explicitprice=None
        if buf:
            explicitprice=strtoamount(buf)
            if explicitprice==zero:
                ui.infopopup(
                    ["You can't override the price of an item to be zero.  "
                     "You should use the {} key instead to say why we're "
                     "giving this item away.".format(
                            keyboard.K_WASTE.keycap)],
                    title="Zero price not allowed")
                return
            if not self.user.has_permission('override-price'):
                ui.infopopup(
                    ["You don't have permission to override the price of "
                     "this item to {}.  Did you mean to press the {} key "
                     "to enter a number of items instead?".format(
                            tillconfig.fc(explicitprice),
                            keyboard.K_QUANTITY.keycap)],
                    title="Permission required")
                return
            # If it's a "regular" stockline then the user has entered
            # the price for stockqty of this item.  We want the price
            # for 1 of this item.
            if stockline.linetype=="regular":
                explicitprice=explicitprice/stockqty
            if department.minprice and explicitprice<department.minprice:
                ui.infopopup(
                    ["Your price of {} per item is too low for {}.  "
                     "Did you mean to press the {} key to enter a number "
                     "of items instead?".format(
                            tillconfig.fc(explicitprice),
                            department.description,
                            keyboard.K_QUANTITY.keycap)],
                    title="Price too low")
                return
            if department.maxprice and explicitprice>department.maxprice:
                ui.infopopup(
                    ["Your price of {} per item is too high for {}.".format(
                            tillconfig.fc(explicitprice),
                            department.description)],
                    title="Price too high")
                return
            log.info("Register: linekey: manual price override to %s by %s",
                     explicitprice,self.user.fullname)

        # If we don't have a price override, check all the items to
        # make sure their stocktype has a sale price set.
        if not explicitprice:
            for item,qty in sell:
                if not item.stocktype.saleprice:
                    no_saleprice_popup(self.user,item)
                    return

        # At this point we have a list of (stockitem,amount) that
        # corresponds to the quantity requested.  We can go ahead and
        # add them to the transaction.
        trans=self.gettrans()
        if trans is None: return # Will already be displaying an error.

        # NB gettrans() may call _clear() and will zap self.repeat when
        # it creates a new transaction!

        may_repeat=self.repeat and hasattr(self.repeat,'stocklineid') and \
            self.repeat.stocklineid==stockline.id and \
            self.repeat.qty==kb.qty
        self.repeat=repeatinfo(stocklineid=stockline.id,qty=kb.qty)

        if stockline.linetype=="regular" and stockline.pullthru:
            # Check first to see whether we may need to record a pullthrough.
            item=sell[0][0]
            if td.stock_checkpullthru(item.id,'11:00:00'):
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
                    title="Pull through?",colour=ui.colour_input,
                    keymap={
                        keyboard.K_WASTE:
                            (record_pullthru,(item.id,stockline.pullthru),
                             True)})

        # By this point we're committed to trying to sell the items.
        for stockitem,items_to_sell in sell:
            # If we may_repeat then the user has pressed the same line
            # key again.  If the stock number matches the most recent
            # transline then we can add to it instead of creating a
            # new one.  Pressing a key again only ever adds 1 to the
            # number of items - anything else would be horribly
            # confusing!  Eg. 4 qty half-cider half-cider sells five
            # halves of cider, i.e. 2.5 pints.  We ignore both
            # items_to_sell and stockqty in this case.
            if may_repeat and len(self.dl)>0 and \
                    self.dl[-1].age()<max_transline_modify_age:
                transline=td.s.query(Transline).get(self.dl[-1].transline)
                if transline.stockref and \
                        transline.stockref.stockitem==stockitem:
                    # Yes, we can update the transline and stockout
                    # record in-place.
                    orig_stockqty=transline.stockref.qty/transline.items
                    transline.items=transline.items+1
                    transline.stockref.qty=orig_stockqty*transline.items
                    td.s.flush()
                    td.s.expire(stockitem,['used','sold','remaining'])
                    log.info("linekey: updated transline %d and stockout %d",
                             transline.id,transline.stockref.id)
                    self.dl[-1].update()
                    continue # on to the next item in the sell list

            # On a regular line, items_to_sell will always be 'items'
            # as calculated above from self.qty or 1, and the quantity
            # to be recorded against the stockitem is
            # items_to_sell*stockqty.

            # On a display line, items_to_sell will be an integer
            # and stockqty will always be 1.

            unitprice=(explicitprice*stockqty).quantize(penny) \
                if explicitprice else \
                tillconfig.pricepolicy(stockitem,stockqty).quantize(penny)
            transline=Transline(
                transaction=self.trans,items=items_to_sell,amount=unitprice,
                department=stockitem.stocktype.department,
                transcode='S',user=self.user.dbuser)
            td.s.add(transline)
            stockout=StockOut(
                transline=transline,stockitem=stockitem,
                qty=stockqty*items_to_sell,removecode_id='sold')
            td.s.add(stockout)
            td.s.flush()
            td.s.expire(stockitem,['used','sold','remaining','firstsale','lastsale'])
            td.s.refresh(transline,['time']) # load time from database
            self.dl.append(tline(transline.id))
            log.info(
                "linekey: trans=%d,lid=%d,sn=%d,items=%d,qty=%s",
                self.trans.id,transline.id,stockitem.id,items_to_sell,
                stockqty)

        if stockline.linetype=="regular":
            # We are using the last value of stockitem from the previous
            # for loop
            self.prompt="{}: {} {}s of {} remaining".format(
                stockline.name,stockitem.remaining,
                stockitem.stocktype.unit.name,stockitem.stocktype.format())
            if stockitem.remaining<Decimal("0.0"):
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
                    "","If you don't understand this message, you MUST "
                    "call your manager to deal with it."],
                             title="Warning",dismiss=keyboard.K_USESTOCK)
        elif stockline.linetype=="display":
            self.prompt="{}: {} left on display; {} in stock".format(
                stockline.name,stockremain[0],int(stockremain[1]))
        # Adding and altering translines changes the total
        td.s.expire(self.trans,['total'])
        self.update_balance()
        self.cursor_off()
        self._redraw()
    @user.permission_required("sell-dept","Sell items using a department key")
    def deptkey(self,dept): # we are passed the department number
        if self.repeat and hasattr(self.repeat,'dept') and \
                self.repeat.dept==dept \
                and self.dl[-1].age()<max_transline_modify_age:
            # Increase the number of items of the most recent entry
            tl=td.s.query(Transline).get(self.dl[-1].transline)
            # The transline must be for the correct department and
            # have no stockref
            if tl.dept_id==dept and not tl.stockref:
                log.info("deptkey: adding to transline %d",tl.id)
                tl.items=tl.items+1
                td.s.flush()
                self.dl[-1].update()
                td.s.expire(self.trans,['total'])
                self.update_balance()
                self.cursor_off()
                self._redraw()
                return
        if not self.buf:
            log.info("Register: deptkey: no amount entered")
            ui.infopopup(["You must enter the amount before pressing "
                          "a department button.  Please try again.","",
                          "Optionally you may enter a quantity, press "
                          "the 'Quantity' button, and then enter the "
                          "price of a single item before pressing the "
                          "department button."],title="Error")
            return
        price=strtoamount(self.buf)
        if self.mod:
            ui.infopopup(["You can't use the '{}' modifier with a "
                          "department button.".format(self.mod.keycap)],
                         title="Error")
            return
        items=self.qty or 1
        department=td.s.query(Department).get(dept)
        if not department:
            ui.infopopup(["Department {} does not exist!".format(dept)],
                         title="Configuration error")
            return
        self.prompt=self.defaultprompt
        self.clearbuffer()
        self.cursor_off()
        priceproblem=tillconfig.deptkeycheck(department,price)
        if priceproblem:
            self._redraw()
            if not isinstance(priceproblem,list):
                priceproblem=[priceproblem]
            ui.infopopup(priceproblem,title="Error")
            return
        if department.minprice and price<department.minprice:
            self._redraw()
            ui.infopopup(["The minimum price for {} is {}.".format(
                        department.description,
                        tillconfig.fc(department.minprice))],
                         title="Price too low")
            return
        if department.maxprice and price>department.maxprice:
            self._redraw()
            ui.infopopup(["The maximum price for {} is {}.".format(
                        department.description,
                        tillconfig.fc(department.maxprice))],
                         title="Price too high")
            return
        trans=self.gettrans()
        if trans is None: return
        tl=Transline(transaction=trans,dept_id=dept,items=items,amount=price,
                     transcode='S',user=self.user.dbuser)
        td.s.add(tl)
        td.s.flush()
        td.s.expire(tl,['time'])
        log.info("deptkey: trans=%d,lid=%d,dept=%d,items=%d,"
                 "price=%f",trans.id,tl.id,dept,items,price)
        self.dl.append(tline(tl.id))
        td.s.expire(self.trans,['total'])
        self.update_balance()
        self.cursor_off()
        self._redraw()
        self.repeat=repeatinfo(dept=dept)
    def deptlines(self,lines):
        """Accept multiple transaction lines from an external source.

        lines is a list of (dept,text,amount) tuples; text may be None
        if the department name is to be used.

        Returns True on success; on failure, returns an error message
        as a string or None if it was a self.entry() error that will
        already have popped up a message.

        """
        if not self.entry(): return
        self.prompt=self.defaultprompt
        self.clearbuffer()
        trans=self.gettrans()
        if trans is None: return "Transaction cannot be started."
        for dept,text,amount in lines:
            tl=Transline(transaction=trans,dept_id=dept,items=1,amount=amount,
                         transcode='S',text=text,user=self.user.dbuser)
            td.s.add(tl)
            td.s.flush()
            log.info("Register: deptlines: trans=%d,lid=%d,dept=%d,"
                     "price=%f,text=%s"%(trans.id,tl.id,dept,amount,text))
            self.dl.append(tline(tl.id))
        self.repeat=None
        self.cursor_off()
        td.s.expire(self.trans,['total'])
        self.update_balance()
        self._redraw()
        return True
    def gettrans(self):
        if self.trans:
            if not self.trans.closed:
                return self.trans
        self._clear()
        session=Session.current(td.s)
        if session is None:
            log.info("Register: gettrans: no session active")
            ui.infopopup(["No session is active.",
                          "You must use the Management menu "
                          "to start a session before you "
                          "can sell anything."],
                         title="Error")
        else:
            self.trans=Transaction(session=session)
            td.s.add(self.trans)
            self.user.dbuser.transaction=self.trans
            td.s.flush()
        self._redraw()
        return self.trans
    @user.permission_required('drink-in','Use the "Drink In" function')
    def drinkinkey(self):
        """
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
                          "before pressing 'Drink In'."],title="Error")
            return
        if not self.buf:
            ui.infopopup(["You must enter an amount before pressing the "
                          "'Drink In' button."],title="Error")
            return
        amount=strtoamount(self.buf)
        if self.trans is None or self.trans.closed:
            ui.infopopup(["A Drink 'In' can't be the only item in a "
                          "transaction; it must be added to a transaction "
                          "that is already open."],title="Error")
            return
        self.clearbuffer()
        if len(tillconfig.payment_methods)<1:
            self._redraw()
            ui.infopopup(["There are no payment methods configured."],
                         title="Error")
            return
        pm=tillconfig.payment_methods[0]
        if not pm.change_given:
            self._redraw()
            ui.infopopup(["The %s payment method doesn't support change."%
                          pm.description],title="Error")
            return
        p=pm.add_change(self.trans,description="Drink 'In'",amount=-amount)
        self.dl.append(p)
        self.cursor_off()
        self.update_balance()
        self._redraw()
    def cashkey(self):
        """
        The CASH/ENTER key is used to complete the "void" action and
        "no sale" action as well as potentially as a payment method
        key.  Check for those first.

        """
        if self.ml!=set():
            return self.cancelmarked()
        if self.qty is not None:
            log.info("Register: cash/enter with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before pressing "
                          "Cash/Enter.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.trans is None or self.trans.closed:
            if not self.buf:
                log.info("Register: cashkey: NO SALE")
                if self.user.has_permission('nosale'):
                    ui.infopopup(["No Sale has been recorded."],
                                 title="No Sale",colour=2)
                    printer.kickout()
                else:
                    ui.infopopup(["You don't have permission to use "
                                  "the No Sale function."],title="No Sale")
                return
            log.info("Register: cashkey: current transaction is closed")
            ui.infopopup(["There is no transaction in progress.  If you "
                          "want to perform a 'No Sale' transaction then "
                          "try again without entering an amount."],
                         title="Error")
            self.clearbuffer()
            self._redraw()
            return
        if len(self.trans.lines)==0 and len(self.trans.payments)==0:
            # Special case: cash key on an empty transaction.
            # Just cancel the transaction silently.
            td.s.delete(self.trans)
            self.trans=None
            td.s.flush()
            self._clear()
            self._redraw()
            return
        # We now consider using the default payment method.  This is only
        # possible if there is one!
        if len(tillconfig.payment_methods)<1:
            ui.infopopup(["There are no payment methods configured."],
                          title="Error")
            return
        pm=tillconfig.payment_methods[0]
        # If the transaction is an old one (i.e. the "recall
        # transaction" function has been used on it) then require
        # confirmation - one of the most common user errors is to
        # recall a transaction that's being used as a tab, add some
        # lines to it, and then automatically press 'cash'.
        if self.keyguard:
            ui.infopopup(["Are you sure you want to close this transaction?  "
                          "If you are then press "
                          "Cash/Enter again.  If you pressed Cash/Enter by "
                          "mistake then press Clear now to go back."],
                         title="Confirm transaction close",
                         colour=ui.colour_confirm,keymap={
                keyboard.K_CASH:(self.paymentkey,(pm,),True)})
            return
        self.paymentkey(pm)
    def payment_method_menu(self,title="Payment methods"):
        possible_keys=[
            keyboard.K_ONE, keyboard.K_TWO, keyboard.K_THREE,
            keyboard.K_FOUR, keyboard.K_FIVE, keyboard.K_SIX,
            keyboard.K_SEVEN, keyboard.K_EIGHT, keyboard.K_NINE,
            keyboard.K_ZERO, keyboard.K_ZEROZERO, keyboard.K_POINT]
        ui.keymenu([(possible_keys.pop(0),m.description,self.paymentkey,(m,))
                    for m in tillconfig.payment_methods],
                   title=title)
    @user.permission_required("take-payment","Take a payment")
    def paymentkey(self,method):
        """
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
        if not self.entry(): return
        if self.trans is None or self.trans.closed:
            log.info("Register: paymentkey: closed or no transaction")
            ui.infopopup(["There is no transaction in progress."],
                         title="Error")
            self.clearbuffer()
            self._redraw()
            return
        self.prompt=self.defaultprompt
        self.balance=self.trans.balance
        if self.buf:
            amount=strtoamount(self.buf)
            if self.balance<zero:
                amount=zero-amount # refund amount
        else:
            # Exact amount
            log.info("Register: paymentkey: exact amount")
            amount=self.balance
        self.clearbuffer()
        self._redraw()
        if amount==zero:
            log.info("Register: paymentkey: payment of zero")
            # A transaction that has been completely voided will have
            # a balance of zero.  Simply close it here rather than
            # attempting a zero payment.
            if self.balance==zero:
                self.close_if_balanced()
                self.cursor_off()
                self._redraw()
                return
            ui.infopopup(["You can't pay {}!".format(tillconfig.fc(zero)),
                          'If you meant "exact amount" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
            return
        # We have a non-zero amount and we're happy to proceed.  Pass
        # to the payment method.
        method.start_payment(self,self.trans,amount,self.balance)
    def add_payments(self,trans,payments):
        """
        Called by a payment method when payments have been added to a
        transaction.  NB it might not be the current transaction if
        the payment method completed in the background!  Multiple
        payments might have been added, eg. for change.

        """
        if not self.entry(): return
        if trans!=self.trans: return # XXX merge because pm might have done td.s.merge()
        for p in payments:
            self.dl.append(p)
        self.close_if_balanced()
        self.update_balance()
        self.cursor_off()
        self._redraw()
    def payments_update(self):
        """
        Called by a payment method when payments have been updated.

        """
        if not self.entry(): return
        if not self.trans or self.trans.closed: return
        # Expire the transaction because the wrong balance may have
        # been cached.
        td.s.expire(self.trans)
        # Update all the payment lines in our display list
        for d in self.dl:
            if isinstance(d,payment.pline): d.update()
        self.update_balance()
        self.close_if_balanced()
        self.cursor_off()
        self._redraw()
    def notekey(self,k):
        if self.qty is not None or self.buf:
            log.info("Register: notekey: error popup")
            ui.infopopup(["You can only press a note key when you "
                          "haven't already entered a quantity or amount.",
                          "After dismissing this message, press Clear "
                          "and try again."],title="Error")
            return
        self.buf=str(k.notevalue)
        log.info("Register: notekey %s"%k.notevalue)
        return self.paymentkey(k.paymentmethod)
    def numkey(self,n):
        if (not self.buf and self.qty==None and
            self.trans is not None and self.trans.closed):
            log.info("Register: numkey on closed transaction; "
                     "clearing display")
            self._clear()
        self.cursor_off()
        if len(self.buf)>=10:
            self.clearkey()
            log.info("Register: numkey: buffer overflow")
            ui.infopopup(["Numerical values entered here can be at most "
                          "ten digits long.  Please try again."],
                         title="Error",colour=1)
        else:
            self.buf=self.buf+n
            # Remove leading zeros
            while len(self.buf)>0 and self.buf[0]=='0':
                self.buf=self.buf[1:]
            if len(self.buf)==0: self.buf='0'
            # Insert a leading zero if first character is a point
            if self.buf[0]=='.': self.buf="0"+self.buf
            # Check that there's no more than one point
            if self.buf.count('.')>1:
                log.info("Register: numkey: multiple points")
                ui.infopopup(["You can't have more than one point in "
                              "a number!  Please try again."],
                             title="Error")
                self.buf=""
            self._redraw()
    def quantkey(self):
        if self.qty is not None:
            log.info("Register: quantkey: already entered")
            ui.infopopup(["You have already entered a quantity.  If "
                          "you want to change it, press Clear after "
                          "dismissing this message."],title="Error")
            return
        if not self.buf: q=0
        else:
            if self.buf.find('.')>0: q=0
            else:
                q=int(self.buf)
        self.buf=""
        if q>0:
            self.qty=q
        else:
            log.info("Register: quantkey: whole number required")
            ui.infopopup(["You must enter a whole number greater than "
                          "zero before pressing Quantity."],
                         title="Error")
        self.cursor_off()
        self._redraw()
    def modkey(self,k):
        self.mod=k
        self.cursor_off()
        self._redraw()
    def clearkey(self):
        if (not self.buf and self.qty==None and
            self.trans is not None and self.trans.closed):
            log.info("Register: clearkey on closed transaction; "
                     "clearing display")
            self._clear()
        else:
            log.info("Register: clearkey on open or null transaction; "
                     "clearing buffer")
            self.cursor_off()
            self.clearbuffer()
        self._redraw()
    @user.permission_required("print-receipt","Print a receipt")
    def printkey(self):
        if self.trans is None:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key, or print any transaction "
                          "if you have its number using the option under "
                          "'Manage Till'."],title="Error")
            return
        log.info("Register: printing transaction %d"%self.trans.id)
        printer.print_receipt(self.trans.id)
        ui.infopopup(["The receipt is being printed."],title="Printing",
                     dismiss=keyboard.K_CASH,colour=ui.colour_info)
    def cancelkey(self):
        if self.trans is None:
            log.info("Register: cancelkey help message")
            ui.infopopup([
                "The Cancel key is used for cancelling whole "
                "transactions, and also for cancelling individual lines "
                "in a transaction.  To cancel a whole transaction, just "
                "press Cancel.  (If you are viewing a transaction that "
                "has already been closed, a new 'void' transaction will "
                "be created with all the lines from the closed "
                "transaction.)","",
                "To cancel individual lines, use the Up and Down keys "
                "to select the line and then press Cancel.  Lines "
                "cancelled from a transaction that's still open are "
                "reversed immediately.  If you're looking at a closed "
                "transaction, you must select the lines you're "
                "interested in and then press Cash/Enter to void them."],
                         title="Help on Cancel")
        else:
            if self.s.cursor>=len(self.dl):
                closed=self.trans.closed
                if not closed and (
                    self.keyguard or 
                    (len(self.dl)>0 and
                     self.dl[0].age()>max_transline_modify_age)):
                    log.info("Register: cancelkey kill transaction denied")
                    ui.infopopup(["This transaction is old; you can't "
                                  "cancel it all in "
                                  "one go.  Cancel each line separately "
                                  "instead."],
                                 title="Cancel Transaction")
                else:
                    log.info("Register: cancelkey confirm kill "
                             "transaction %d"%self.trans.id)
                    ui.infopopup(["Are you sure you want to %s all of "
                                  "transaction number %d?  Press Cash/Enter "
                                  "to confirm, or Clear to go back."%(
                        ("cancel","void")[closed],self.trans.id)],
                                 title="Confirm Transaction Cancel",
                                 keymap={
                        keyboard.K_CASH: (self.canceltrans,None,True)})
            else:
                self.cancelline()
    def canceltrans(self):
        if not self.entry(): return
        # Yes, they really want to do it.  But is it open or closed?
        if self.trans.closed:
            log.info("Register: cancel closed transaction %d"%self.trans.id)
            # Select all lines
            for i in range(0,len(self.dl)):
                self.markline(i)
            # Create new 'void' transaction
            self.cancelmarked()
        else:
            # Delete this transaction and everything to do with it
            tn=self.trans.id
            log.info("Register: cancel open transaction %d"%tn)
            payments=self.trans.payments_total
            for p in self.trans.payments: td.s.delete(p)
            for l in self.trans.lines: td.s.delete(l)
            # stockout objects should be deleted implicitly in cascade
            td.s.delete(self.trans)
            self.trans=None
            td.s.flush()
            if payments>zero:
                printer.kickout()
                refundtext="%s had already been put in the cash drawer."%(
                    tillconfig.fc(payments))
            else: refundtext=""
            self._clear()
            self._redraw()
            ui.infopopup(["Transaction number %d has been cancelled.  %s"%(
                tn,refundtext)],title="Transaction Cancelled",
                         dismiss=keyboard.K_CASH)
    def markline(self,line):
        l=self.dl[line]
        if isinstance(l,tline):
            transline=l.transline
            self.ml.add(transline)
            l.update_mark(self.ml)
            self.s.drawdl()
    def cancelline(self,force=False):
        if not self.entry(): return
        if self.trans.closed:
            l=self.dl[self.s.cursor]
            if not isinstance(l,tline):
                ui.infopopup(["You can't void payments from closed "
                              "transactions."],title="Error")
                return
            if self.ml==set():
                ui.infopopup(
                    ["Use the Up and Down keys and the Cancel key "
                     "to select lines from this transaction that "
                     "you want to void, and then press Cash/Enter "
                     "to create a new transaction that voids these "
                     "lines.  If you don't want to cancel lines from "
                     "this transaction, press Clear after dismissing "
                     "this message."],
                    title="Help on voiding lines from closed transactions")
            self.prompt="Press Cash/Enter to void the blue lines"
            self.markline(self.s.cursor)
        else:
            l=self.dl[self.s.cursor]
            if isinstance(l,tline):
                transline=l.transline
                if force:
                    if l.age()<max_transline_modify_age:
                        log.info("Register: cancelline: delete "
                                 "transline %d"%transline)
                        tl=td.s.query(Transline).get(transline)
                        td.s.delete(tl)
                        td.s.flush()
                        del self.dl[self.s.cursor]
                        td.s.expire(self.trans,['total'])
                        self.cursor_off()
                        self.update_balance()
                        if len(self.dl)==0:
                            # The last transaction line was deleted, so also
                            # delete the transaction.
                            self.canceltrans()
                        self._redraw()
                    else:
                        log.info("Register: cancelline: reverse "
                                 "transline %d"%transline)
                        self.voidline(transline)
                        self.cursor_off()
                        self.update_balance()
                        self._redraw()
                else:
                    log.info("Register: cancelline: confirm cancel")
                    ui.infopopup(["Are you sure you want to cancel this line? "
                                  "Press Cash/Enter to confirm."],
                                 title="Confirm Cancel",keymap={
                        keyboard.K_CASH: (self.cancelline,(True,),True)})
            else:
                log.info("Register: cancelline: can't cancel payments")
                ui.infopopup(["You can't cancel payments.  Cancel the whole "
                              "transaction instead."],title="Cancel")
    def voidline(self,tl):
        """
        Add a line reversing the supplied transaction line to the
        current transaction.  tl is a Transline id.

        The caller is responsible for updating the balance and
        redrawing.

        """
        trans=self.gettrans()
        transline=td.s.query(Transline).get(tl)
        if transline.stockref is not None:
            stockout=transline.stockref
            ntl=Transline(
                transaction=trans,items=-transline.items,
                amount=transline.amount,department=transline.department,
                transcode='V',user=self.user.dbuser)
            td.s.add(ntl)
            nso=StockOut(
                transline=ntl,
                stockitem=stockout.stockitem,qty=-stockout.qty,
                removecode=stockout.removecode)
            td.s.add(nso)
            td.s.flush()
        else:
            ntl=Transline(
                transaction=trans,items=-transline.items,
                amount=transline.amount,department=transline.department,
                transcode='V',text=transline.text,user=self.user.dbuser)
            td.s.add(ntl)
            td.s.flush()
        self.dl.append(tline(ntl.id))
    def cancelmarked(self):
        tl=list(self.ml)
        self._clear()
        trans=self.gettrans()
        if trans is None: return
        log.info("Register: cancelmarked %s; new trans=%d"%(str(tl),trans.id))
        for i in tl:
            self.voidline(i)
        self.cursor_off()
        self.update_balance()
        self._redraw()
        self.payment_method_menu(title="Choose refund type, or press Clear to "
                                 "add more items")
    def recalltrans(self,trans):
        # We refresh the user object as if in enter() here, but don't
        # bother with the full works because we're replacing the current
        # transaction anyway!
        self.user.dbuser=td.s.query(User).get(self.user.userid)
        self._clear()
        # All other active pages pagesummary() methods will be called
        # during a redraw.  This will get them to add their
        # currently-loaded transactions to the identity map, meaning
        # we'll get the right one when we query.
        self._redraw()
        if trans is not None:
            log.info("Register: recalltrans %d",trans)
            trans=td.s.query(Transaction).get(trans)
            # Leave a message if the transaction belonged to another
            # user.
            user=td.s.query(User).filter(User.transaction==trans).first()
            if user:
                user.transaction=None
                user.message="Your transaction {} ({}) was taken over by {} " \
                    "using the Recall Transaction function.".format(
                        trans.id,trans.notes or "no notes",self.user.fullname)
            self._loadtrans(trans)
            self.keyguard=True
            self.close_if_balanced()
            if not self.trans.closed:
                age=self.trans.age
                if age>2:
                    ui.infopopup(["This transaction is %d days old.  Please "
                                  "arrange for it to be paid soon."%age],
                                 title="Warning")
        self.cursor_off()
        self.update_balance()
        self._redraw()
    @user.permission_required("recall-trans","Change to a different "
                              "transaction")
    def recalltranskey(self):
        sc=Session.current(td.s)
        if sc is None:
            log.info("Register: recalltrans: no session")
            ui.infopopup(["There is no session in progress.  You can "
                          "only recall transactions that belong to the "
                          "current session."],title="Error")
            return
        log.info("recalltrans")
        if (tillconfig.allow_tabs is False and self.keyguard is False and
            not (self.trans is None or self.trans.closed)):
            ui.infopopup(["We do not run tabs.  Food and drink must "
                          "be paid for at the time it is ordered."],
                         title="Error")
            return
        transactions=td.s.query(Transaction).\
            filter(Transaction.session==sc).\
            options(td.undefer('total')).\
            options(td.joinedload('user')).\
            order_by(Transaction.closed==True).\
            order_by(desc(Transaction.id)).\
            all()
        f=ui.tableformatter(' r l r l l ')
        sl=[(f(x.id,('open','closed')[x.closed],
               tillconfig.fc(x.total),
               x.user.shortname if x.user else "",x.notes),
             self.recalltrans,(x.id,)) for x in transactions]
        ui.menu([('New Transaction',self.recalltrans,(None,))]+sl,
                title="Recall Transaction",
                blurb="Select a transaction and press Cash/Enter.",
                colour=ui.colour_input)
    @user.permission_required("defer-trans","Defer a transaction to a "
                              "later session")
    def defertrans(self):
        if not self.entry(): return
        if not self.trans: return
        if self.trans.closed:
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be deferred."%trans.id],title="Error")
            return
        amount=self.trans.payments_total
        if amount!=zero:
            # Check that there is a default payment method
            if len(tillconfig.payment_methods)<1:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  There is no default "
                     "payment method so this can't be done now."],
                    title="Error")
                return
            pm=tillconfig.payment_methods[0]
            # The payment method must support both change and refunds
            if not pm.change_given or not pm.refund_supported:
                ui.infopopup(
                    ["This transaction is part-paid; to defer it "
                     "we must refund the part-payment.  The default payment "
                     "method does not support this."],
                    title="Error")
                return
            # Refund the amount paid so far and ask the user to set it aside
            pm.add_change(self.trans,"Deferred",zero-amount)
            printer.kickout()
        transid=self.trans.id
        self.trans.session=None
        td.s.flush()
        self._clear()
        self._redraw()
        message=["Transaction {} has been deferred to the next "
                 "session.  Make sure you keep a note of the "
                 "transaction number and the name of the person "
                 "responsible for paying it!".format(transid)]
        if amount:
            message=message+["","{} had been paid towards this transaction. "
                             "You must remove this amount from the till and "
                             "set it aside to be used to pay off the "
                             "transaction in a later session.".format(
                    tillconfig.fc(amount))]
        ui.infopopup(message,
                     title="Transaction defer confirmed",
                     colour=ui.colour_confirm,dismiss=keyboard.K_CASH)
    @user.permission_required("convert-to-free-drinks",
                              "Convert a transaction to free drinks")
    def freedrinktrans(self):
        """
        Convert the current transaction to free drinks.

        """
        if not self.entry(): return
        if not self.trans:
            ui.infopopup(["There is no current transaction."],
                         title="Error")
            return
        if self.trans.closed:
            ui.infopopup(["The transaction is already closed."],
                         title="Error")
            return
        if len(self.trans.payments)>0:
            ui.infopopup(["This transaction has already had payments entered "
                          "against it, so cannot be converted to free drinks."],
                         title="Error")
            return
        if not self.trans.notes or "free" not in self.trans.notes.lower():
            ui.infopopup(
                ["The transaction notes must include the word 'free' "
                 "before the transaction can be converted to free drinks.",
                 "","This is a protective measure to try to ensure you don't "
                 "convert the wrong transaction.  Conversion of a transaction "
                 "to free drinks cannot be reversed."],
                title="Transaction not labelled for free drinks")
            return
        freebie=td.s.query(RemoveCode).get('freebie')
        if not freebie:
            ui.infopopup(["The database does not include a 'free drink' "
                          "waste code."],title="Error")
            return
        for l in self.trans.lines:
            sr=l.stockref
            if sr:
                sr.removecode=freebie
                sr.transline=None
        td.s.flush()
        td.s.refresh(self.trans) # remove references to stockout objects
        for l in self.trans.lines: td.s.delete(l)
        td.s.delete(self.trans)
        self.trans=None
        td.s.flush()
        self._clear()
        self._redraw()
        ui.infopopup(["Transaction has been converted to free drinks."],
                     title="Free drinks",colour=ui.colour_confirm,
                     dismiss=keyboard.K_CASH)
    def _check_session_and_open_transaction(self):
        # For transaction merging
        if not self.entry(): return False
        sc=Session.current(td.s)
        if not sc:
            ui.infopopup(["There is no session active."],title="Error")
            return False
        if not self.trans:
            ui.infopopup(["There is no current transaction."],title="Error")
            return False
        if self.trans.closed:
            ui.infopopup(["The current transaction is closed and can't "
                          "be merged with another transaction."],
                         title="Error")
            return False
        return sc
    @user.permission_required("merge-trans","Merge two transactions")
    def mergetransmenu(self):
        sc=self._check_session_and_open_transaction()
        if not sc: return
        tl=[t for t in sc.transactions if not t.closed]
        f=ui.tableformatter(' r r l ')
        sl=[(f(x.id,tillconfig.fc(x.total),x.notes or ""),
            self._mergetrans,(x.id,)) for x in tl if x!=self.trans]
        ui.menu(sl,
                title="Merge with transaction",
                blurb="Select a transaction to merge this one into, "
                "and press Cash/Enter.",
                colour=ui.colour_input)
    def _mergetrans(self,othertransid):
        sc=self._check_session_and_open_transaction()
        if not sc: return
        othertrans=td.s.query(Transaction).get(othertransid)
        if len(self.trans.payments)>0:
            ui.infopopup(["Some payments have already been entered against "
                          "transaction {}, so it can't be merged with another "
                          "transaction.".format(self.trans.id)],
                         title="Error")
            return
        if othertrans.closed:
            ui.infopopup(["Transaction %d has been closed, so we can't "
                          "merge this transaction into it."%othertrans.id],
                         title="Error")
            return
        for line in self.trans.lines:
            line.transid=othertrans.id
        td.s.flush()
        # At this point the ORM still believes the translines belong
        # to the original transaction, and will attempt to set their transid
        # fields to NULL when we delete it.  Refresh here!
        # XXX is it possible to get the ORM to update this automatically?
        td.s.refresh(self.trans)
        td.s.delete(self.trans)
        td.s.flush()
        td.s.expire(othertrans)
        self._loadtrans(othertrans)
    def settransnote(self,notes):
        if not self.entry(): return
        if not self.trans or self.trans.closed: return
        if notes=="": notes=None
        self.trans.notes=notes
        self.update_note()
    def managetranskey(self):
        if self.trans is None or self.trans.closed:
            ui.infopopup(["You can only modify an open transaction."],
                         title="Error")
            return
        menu=[
            (keyboard.K_ONE,"Defer transaction to next session",
             self.defertrans,None),
            (keyboard.K_TWO,"Convert transaction to free drinks",
             self.freedrinktrans,None),
            (keyboard.K_THREE,"Merge this transaction with another "
             "open transaction",self.mergetransmenu,None),
            (keyboard.K_FOUR,"Set this transaction's note to '{}'".format(
                    self.user.fullname),
             self.settransnote,(self.user.fullname,)),
            (keyboard.K_FIVE,"Change this transaction's notes "
             "(free text entry)",
             edittransnotes,(self.trans,self.settransnote)),
            (keyboard.K_SIX,"Choose payment method",
             self.payment_method_menu,None),
            ]
        ui.keymenu(menu,title="Transaction %d"%self.trans.id)
    def entry(self):
        """
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
        self.user.dbuser=td.s.query(User).get(self.user.userid)

        # This check has already been done in hotkeypress().  We
        # repeat it here because it is possible we may not have been
        # entered in response to a keypress - a timer event, for
        # example.
        if self.user.dbuser.register!=register_instance:
            # If the register in the database isn't us, lock immediately
            self.deselect()
            return False

        # If there is a message queued for the user, display it.  It
        # probably explains where their transaction has gone to!
        if self.user.dbuser.message:
            ui.infopopup([self.user.dbuser.message],
                         title="Transaction information")
            self._clear()
            self.user.dbuser.message=None
            td.s.flush()
            return False

        if self.trans and not self.user.dbuser.transaction:
            # Someone has taken our transaction without leaving a
            # message.  How rude!  Give them a default message.
            ui.infopopup(["Your transaction has gone away."],
                         title="Transaction gone")
            self._clear()
            td.s.flush()
            return False

        # At this point, self.trans and self.user.dbuser.transaction
        # should either both be None or both be the current
        # transaction.  self.trans may be detached from the current
        # sqlalchemy session.  Replace it with the one from
        # self.user.dbuser.transaction
        self.trans=self.user.dbuser.transaction
        return True
    def keypress(self,k):
        # This is our main entry point.  We will have a new database session.
        # Update the transaction object before we do anything else!
        if self.locked:
            # When we are locked, the only operation that's permitted
            # is printing the current transaction if it is closed.
            # All other keypresses are ignored.
            if self.trans: td.s.add(self.trans)
            if self.trans and self.trans.closed and k==keyboard.K_PRINT:
                self.printkey()
            return
        if not self.entry(): return
        if hasattr(k,'line'):
            stocklines.linemenu(k,self.linekey)
            return
        elif hasattr(k,'department'):
            return self.deptkey(k.department)
        self.repeat=None
        if hasattr(k,'notevalue'):
            return self.notekey(k)
        elif hasattr(k,'paymentmethod'):
            return self.paymentkey(k.paymentmethod)
        elif k in keyboard.numberkeys:
            return self.numkey(k.keycap)
        keys={
            keyboard.K_CASH: self.cashkey,
            keyboard.K_DRINKIN: self.drinkinkey,
            keyboard.K_QUANTITY: self.quantkey,
            keyboard.K_CLEAR: self.clearkey,
            keyboard.K_CANCEL: self.cancelkey,
            keyboard.K_PRINT: self.printkey,
            keyboard.K_RECALLTRANS: self.recalltranskey,
            keyboard.K_MANAGETRANS: self.managetranskey,
            }
        if k in keys: return keys[k]()
        if k in self.hotkeys: return self.hotkeys[k]()
        if hasattr(k,'qty') and hasattr(k,'unittypes'):
            return self.modkey(k)
        if k==keyboard.K_FOODORDER:
            trans=self.gettrans()
            if trans is None: return
            return foodorder.popup(self.deptlines,transid=trans.id)
        if k==keyboard.K_CANCELFOOD or k==keyboard.K_FOODMESSAGE:
            return foodorder.message()
        curses.beep()
    def hotkeypress(self,k):
        # Fetch the current user from the database.  We don't recreate
        # the user.database_user object because that's unlikely to
        # change often; we're just interested in the transaction and
        # register fields.
        self.user.dbuser=td.s.query(User).get(self.user.userid)

        # Check that the user hasn't moved to another terminal.  If
        # they have, lock immediately.  Continue with hotkey
        # processing, because the keypress might be a user token that
        # will need to be dealt with.
        if self.user.dbuser.register!=register_instance:
            self.deselect()
            return super(page,self).hotkeypress(k)

        if self._autolock and k==self._autolock and not self.locked \
                and self.s.focused:
            # Intercept the 'Lock' keypress and handle it ourselves.
            # Do this only if our scrollable has the focus.
            self.locked=True
            self._redraw()
        else:
            super(page,self).hotkeypress(k)
    def select(self,u):
        # Called when the appropriate user token is presented
        self.user=u # Permissions might have changed!
        self.user.dbuser.register=register_instance
        td.s.flush()
        if self.locked:
            self.locked=False
            self._redraw()
        ui.basicpage.select(self)
        log.info("Existing page selected for %s",self.user.fullname)
        self.entry()
    def deselect(self):
        # We might be able to delete ourselves completely after
        # deselection if none of the popups has unsaved data.  When we
        # are recreated we can reload the current transaction from the
        # database.
        focus=ui.basicwin._focus # naughty!
        self.unsaved_data=None
        while focus!=self.s:
            unsaved_data=getattr(focus,'unsaved_data',None)
            log.debug("deselect: checking %s: unsaved_data=%s",focus,unsaved_data)
            if unsaved_data:
                log.info("Page for %s deselected; unsaved data (%s) so just "
                         "hiding the page",self.user.fullname,unsaved_data)
                self.unsaved_data=unsaved_data
                return ui.basicpage.deselect(self)
            focus=focus.parent
        log.info("Page for %s deselected with no unsaved data: deleting self",
                 self.user.fullname)
        ui.basicpage.deselect(self)
        self.dismiss()

def handle_usertoken(t,*args,**kwargs):
    """
    Called when a usertoken has been handled by the default hotkey
    handler.

    """
    u=user.user_from_token(t)
    if u is None: return # Should already have popped up a dialog box
    for p in ui.basicpage._pagelist:
        if isinstance(p,page) and p.user.userid==u.userid:
            p.select(u)
            return p
    return page(u,*args,**kwargs)
