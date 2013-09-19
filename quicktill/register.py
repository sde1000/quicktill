"""Cash register page.  Allows transaction entry, voiding of lines.
Also supports function keys to go to various popups: price lookup, management,
etc."""

# A brief word about how redrawing the screen works:
#
# There are three main areas to worry about: the screen header, the
# "buffer" line, and the display list.
#
# The screen header shows the page header, a summary of the other
# pages, and the clock.  It needs updating whenever the current
# transaction changes: from none to present, from present to none, or
# from open to closed.  It is updated by calling ui.updateheader();
# this calls pagesummary() for all pages.
#
# The "buffer" line shows either a prompt or the input buffer at the
# left, and the balance of the current transaction at the right.  It
# is implemented as a notional "last entry" in the display list, and
# will only be redrawn when the display list is redrawn.  Whenever the
# transaction balance, prompt, or buffer contents change, the buffer
# line must be updated by calling self.update_bufferline().  This will
# not update the line on the screen; that won't happen until you call
# redraw().
#
# The display list is a list of line() objects, that correspond to
# lines in a transaction.  When a transaction line is modified you
# must call the update() method of the corresponding line object.  The
# display list is redrawn in one of two ways: 1) Call redraw().  This
# scrolls to the current cursor position.  2) Call self.s.drawdl().  No
# scrolling is performed.  After you append an item to the display
# list, you should call cursor_off() before calling redraw() to make
# sure that we scroll to the end of the list.

from . import magcard,tillconfig
import curses,textwrap
from . import td,ui,keyboard,printer
from . import stock,stocklines
import logging
import datetime
log=logging.getLogger()
from . import foodorder
from . import btcmerch
from .models import Transline,Transaction,Session,StockOut,Transline,penny
from .models import Payment,zero
from decimal import Decimal

max_transline_modify_age=datetime.timedelta(minutes=1)

class transnotify:
    def __init__(self):
        self.nl=[]
    def register(self,page):
        self.nl.append(page)
    def announce(self,pagename,transid):
        """Announce a page has taken control of a particular transaction
        number. If the number is 0 (special case) then all pages should
        clear themselves; this is used for global operations like
        ending a session."""
        for i in self.nl: i.tnotify(pagename,transid)

class bufferline(ui.lrline):
    """
    Used as the very last line on the register display - a special
    case.  Always consists of two lines; a blank line, and then a line
    showing the prompt or the contents of the input buffer at the
    left, and if appropriate the balance of the transaction on the
    right.

    """
    def __init__(self):
        ui.lrline.__init__(self)
        self.cursor_colour=self.colour
        self.cursorx=0
    def update_buffer(self,prompt,qty,mod,buf,balance):
        if qty is not None: m="%d of "%qty
        else: m=""
        if mod is not None: m="%s%s "%(m,mod)
        if buf is not None: m="%s%s"%(m,buf)
        if len(m)>0:
            self.ltext=m
            self.cursorx=len(m)
        else:
            self.ltext=prompt
            self.cursorx=0
        self.rtext="%s %s"%("Amount to pay" if balance>=0.0 else "Change",
                            tillconfig.fc(balance)) if balance else ""
    def display(self,width):
        # Add the expected blank line
        l=['']+ui.lrline.display(self,width)
        self.cursor=(self.cursorx,len(l)-1)
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

# Used for payments etc.
class rline(ui.lrline):
    def __init__(self,text,attr):
        ui.lrline.__init__(self,"",text,curses.color_pair(attr))
        # It would be very useful if the payments table had a unique ID
        # per payment so that we could store a reference to it here.
        # Unfortunately it doesn't - this makes cancelling payments
        # rather difficult.

def payline(p):
    """
    Convenience function for creating a payment line; chooses colour
    and fills in description.

    """
    (amount,paytype,desc,ref)=p
    if amount==None: amount=0.0
    colour=ui.colour_cashline
    if amount<0.0: colour=ui.colour_changeline
    if paytype=='CASH':
        return rline('%s %s'%(ref,tillconfig.fc(amount)),colour)
    if ref is None:
        return rline("%s %s"%(desc,tillconfig.fc(amount)),colour)
    return rline("%s %s %s"%(desc,ref,tillconfig.fc(amount)),colour)

class cardpopup(ui.dismisspopup):
    """A window that pops up whenever a card payment is accepted.  It prompts
    for the card receipt number (provided by the credit card terminal) and
    whether there is any cashback on this transaction."""
    def __init__(self,amount,func):
        self.amount=amount
        self.func=func
        ui.dismisspopup.__init__(self,16,44,title="Card payment",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Card payment of %s"%tillconfig.fc(amount))
        if tillconfig.cashback_first:
            cbstart=4
            rnstart=10
        else:
            cbstart=9
            rnstart=4
        self.addstr(rnstart,2,"Please enter the receipt number from the")
        self.addstr(rnstart+1,2,"credit card receipt.")
        self.addstr(rnstart+3,2," Receipt number:")
        self.rnfield=ui.editfield(rnstart+3,19,16)
        self.addstr(cbstart,2,"Is there any cashback?  Enter amount and")
        self.addstr(cbstart+1,2,"press Cash/Enter.  Leave blank and press")
        self.addstr(cbstart+2,2,"Cash/Enter if there is none.")
        self.addstr(cbstart+4,2,"Cashback amount: %s"%tillconfig.currency)
        self.cbfield=ui.editfield(cbstart+4,19+len(tillconfig.currency),6,
                                  validate=ui.validate_float,
                                  keymap={
                keyboard.K_TWENTY: (self.note,(20.0,)),
                keyboard.K_TENNER: (self.note,(10.0,)),
                keyboard.K_FIVER: (self.note,(5.0,))})
        if tillconfig.cashback_first:
            firstfield=self.cbfield
            lastfield=self.rnfield
        else:
            firstfield=self.rnfield
            lastfield=self.cbfield
        ui.map_fieldlist([self.rnfield,self.cbfield])
        firstfield.keymap[keyboard.K_CLEAR]=(self.dismiss,None)
        lastfield.keymap[keyboard.K_CASH]=(self.enter,None)
        firstfield.focus()
    def note(self,size):
        self.cbfield.set("%0.2f"%size)
        self.cbfield.keypress(keyboard.K_CASH)
    def enter(self):
        try:
            cba=Decimal(self.cbfield.f).quantize(penny)
        except:
            cba=zero
        if cba>tillconfig.cashback_limit:
            self.cbfield.set("")
            return ui.infopopup(["Cashback is limited to a maximum of %s per "
                                 "transaction."%tillconfig.fc(
                        tillconfig.cashback_limit)],title="Error")
        total=self.amount+cba
        receiptno=self.rnfield.f
        if receiptno=="":
            return ui.infopopup(["You must enter a receipt number."],
                                title="Error")
        self.dismiss()
        self.func(total,receiptno,cba)

class btcpopup(ui.dismisspopup):
    """
    A window used to accept a Bitcoin payment.

    """
    def __init__(self,func,transid,amount):
        self.func=func
        self.transid=transid
        self.amount=amount
        (mh,mw)=ui.stdwin.getmaxyx()
        self.h=mh
        self.w=mh*2
        self.response={}
        ui.dismisspopup.__init__(
            self,self.h,self.w,
            title="Bitcoin payment - press Cash/Enter to check",
            colour=ui.colour_input,keymap={
                keyboard.K_CASH:(self.refresh,None,False),
                keyboard.K_PRINT:(self.printout,None,False)})
        self.refresh()
    def draw_qrcode(self):
        import qrcode
        q=qrcode.QRCode(border=2)
        q.add_data("bitcoin:%s?amount=%s"%(self.response[u'pay_to_address'],
                                           self.response[u'to_pay']))
        m=q.get_matrix()
        size=len(m)
        # Will it fit using single block characters?
        if size+2<self.h and ((size*2)+2)<self.w:
            # Yes!  Try to center it
            x=(self.w/2)-size
            y=(self.h-size)/2
            for line in m:
                self.addstr(y,x,''.join(["  " if c else u"\u2588\u2588" for c in line]))
                y=y+1
        # Will it fit using half block characters?
        elif (size/2)<self.h and size+2<self.w:
            # Yes.
            x=(self.w-size)/2
            y=(self.h-(size/2))/2
            # We work on two rows at once.
            lt={
                (False,False): u"\u2588", # Full block
                (False,True): u"\u2580", # Upper half block
                (True,False): u"\u2584", # Lower half block
                (True,True): " ", # No block
                }
            while len(m)>0:
                if len(m)>1:
                    row=zip(m[0],m[1])
                else:
                    row=zip(m[0],[True]*len(m[0]))
                m=m[2:]
                self.addstr(y,x,''.join([lt[c] for c in row]))
                y=y+1
        else:
            self.addstr(2,2,
                        "QR code will not fit on this screen.  Press Print.")
    def printout(self):
        if u'to_pay_url' in self.response:
            printer.print_qrcode(self.response)
    def refresh(self):
        try:
            result=tillconfig.btcmerch_api.request_payment(
                "tx%d"%self.transid,"Transaction %d"%self.transid,self.amount)
        except btcmerch.HTTPError as e:
            if e.e.code==409:
                return ui.infopopup(
                    ["Once a request for Bitcoin payment has been made, the "
                     "amount being requested can't be changed.  You have "
                     "previously requested payment for this transaction of "
                     "a different amount.  Please cancel the change and try "
                     "again.  If you can't do this, cancel and re-enter the "
                     "whole transaction."],title="Bitcoin error")
            return ui.infopopup([str(e)],title="Bitcoin error")
        except btcmerch.BTCMerchError as e:
            return ui.infopopup([str(e)],title="Bitcoin error")
        self.response=result
        if u'to_pay_url' in result:
            self.draw_qrcode()
        self.addstr(self.h-1,3,"Received %s of %s BTC so far"%(
                result[u'paid_so_far'],result[u'amount_in_btc']))
        if result['paid']:
            self.dismiss()
            self.func(result[u'amount'],str(result['amount_in_btc']))
            return ui.infopopup(["Bitcoin payment received"],title="Bitcoin",
                                dismiss=keyboard.K_CASH,colour=ui.colour_info)


class edittransnotes(ui.dismisspopup):
    """A popup to allow a transaction's notes to be edited."""
    def __init__(self,trans,func):
        self.trans=trans
        self.func=func
        ui.dismisspopup.__init__(self,5,60,
                                 title="Notes for transaction %d"%trans,
                                 colour=ui.colour_input)
        t=td.s.query(Transaction).get(trans)
        notes=t.notes if t.notes else u''
        self.notesfield=ui.editfield(2,2,56,f=notes,flen=60,keymap={
                keyboard.K_CASH:(self.enter,None)})
        self.notesfield.focus()
    def enter(self):
        notes=self.notesfield.f
        if notes=="": notes=None
        t=td.s.query(Transaction).get(self.trans)
        t.notes=notes
        self.func()
        self.dismiss()

def strtoamount(s):
    if s.find('.')>=0:
        return Decimal(s).quantize(penny)
    return (Decimal(s)/Decimal("100.00")).quantize(penny)

class page(ui.basicpage):
    def __init__(self,panel,name,hotkeys):
        global registry
        ui.basicpage.__init__(self,panel)
        self.h=self.h-1 # XXX hack to avoid drawing into bottom right-hand cell
        self.name=name
        self.defaultprompt="Ready"
        registry.register(self)
        self.bufferline=bufferline()
        self.s=ui.scrollable(1,0,self.w,self.h-1,[],
                             lastline=self.bufferline)
        self.s.focus()
        self.clear()
        self.redraw()
        self.hotkeys=hotkeys
        self.savedfocus=ui.focus # Save this, so that it can be
                                 # restored when we are selected.
    def clearbuffer(self):
        self.buf=None # Input buffer
        self.qty=None # Quantity (integer)
        self.mod=None # Modifier (string)
        self.update_bufferline()
    def clear(self):
        """
        Reset this page to having no current transaction and nothing
        in the input buffer.  Note that this does not cause a redraw;
        various functions may want to fiddle with the state (for example
        loading a previous transaction) before requesting a redraw.

        """
        self.dl=[] # Display list
        self.s.set(self.dl) # Tell the scrollable about the new display list
        self.ml=set() # Marked transactions set
        # than the length of the list then there is no selection.
        self.trans=None # Current transaction
        self.repeat=None # If dept/line button pressed, update this transline
        self.balance=None # Balance of current transaction
        self.prompt=self.defaultprompt
        self.keyguard=False # Require confirmation for 'Cash' or 'Cancel'
        self.clearbuffer()
        self.update_bufferline()
        self.update_note()
    def update_bufferline(self):
        self.bufferline.update_buffer(self.prompt,self.qty,self.mod,self.buf,
                                      self.balance)
    def pagename(self):
        if self.trans is not None:
            ts=" - Transaction %d (%s)"%(self.trans.id,("open","closed")
                                         [self.trans.closed])
        else: ts=""
        return "%s%s"%(self.name,ts)
    def pagesummary(self):
        if self.trans is None: return ""
        elif self.trans.closed: return ""
        else: return "%s:%d"%(self.name[0],self.trans.id)
    def tnotify(self,name,trans):
        "Receive notification that another page has claimed this transaction"
        if trans==0 or (self.name!=name and self.trans and self.trans.id==trans):
            self.clear()
            self.redraw()
    def redraw(self):
        """
        Updates the screen, scrolling until the cursor is visible.

        """
        self.s.redraw()
        ui.updateheader()
    def update_note(self):
        note=self.trans.notes if self.trans is not None else None
        if note is None: note=u""
        note=note+u" "*(self.w-len(note))
        self.win.addstr(0,0,note,ui.curses.color_pair(ui.colour_changeline))
        # Note - moves the cursor
    def cursor_off(self):
        # Returns the cursor to the buffer line.  Does not redraw (because
        # the caller is almost certainly going to do other things first).
        self.s.cursor=len(self.dl)
    def update_balance(self):
        if self.trans:
            self.balance=self.trans.total-self.trans.payments_total
            if self.balance==zero: self.balance=None
        else: self.balance=None
        self.update_bufferline()
        self.redraw()
    def close_if_balanced(self):
        if self.trans and not self.trans.closed:
            if self.trans.total==self.trans.payments_total:
                self.trans.closed=True
                td.s.flush()
    def linekey(self,kb): # We are passed the keyboard binding
        td.s.add(kb)
        name=kb.stockline.name
        qty=kb.qty
        dept=kb.stockline.dept_id
        pullthru=kb.stockline.pullthru
        stocklineid=kb.stockline.id
        capacity=kb.stockline.capacity

        repeat_lid=None
        repeat_stockid=None
        if self.repeat is not None:
            if self.repeat[0]==(stocklineid,qty):
                log.info("Register: linekey: might sell more of lid=%d"%
                         self.repeat[1])
                # We save the line id and stock number, and if we discover
                # that we're selling more of that stock number as the first
                # thing we do then we add to the previous line instead
                repeat_lid=self.repeat[1]
                repeat_stockid=self.repeat[2]
        self.repeat=None
        # buf is a price override.  Consider logging it.
        if self.buf is not None:
            unitprice=strtoamount(self.buf)
            log.info("Register: linekey: manual price override to %s"%(
                unitprice))
        else:
            unitprice=None
        if self.qty is not None: items=self.qty
        else: items=1
        repeatcandidate=False
        checkdept=None
        mod=self.mod
        self.mod=None
        if mod is not None:
            (qty,checkdept)=tillconfig.modkeyinfo.get(mod,(None,None))
        else:
            repeatcandidate=True
        # We redraw because we might bail if there is an error.
        self.clearbuffer()
        self.redraw()
        # Now we know how many we are trying to sell.
        (sell,unallocated,stockremain)=(
            stocklines.calculate_sale(stocklineid,items))
        if capacity is not None and unallocated>0:
            ui.infopopup(
                ["There are fewer than %d items of %s on display.  "
                 "If you have recently put more stock on display you "
                 "must tell the till about it using the 'Use Stock' "
                 "button after dismissing this message."%(
                items,name)],title="Not enough stock on display")
            return
        if len(sell)==0:
            log.info("Register: linekey: no stock in use for %s"%name)
            ui.infopopup(["No stock is registered for %s."%name,
                          "To tell the till about stock on sale, "
                          "press the 'Use Stock' button after "
                          "dismissing this message."],
                         title="%s has no stock"%name)
            return
        # We might have to abort if an invalid modifier key has been used.
        if checkdept is not None:
            for stockitem,items in sell:
                dept=stockitem.stocktype.dept_id
                if dept not in checkdept:
                    ui.infopopup(["You can't use the '%s' modifier with "
                                  "stock in department %d."%(mod,dept)],
                                 title="Error")
                    return
        # At this point we have a list of (stockitem,amount) that corresponds
        # to the quantity requested.  We can go ahead and add them to the
        # transaction.
        trans=self.gettrans()
        if trans is None: return # Will already be displaying an error.
        # By this point we're committed to trying to sell the items.
        for stockitem,items in sell:
            # Check first to see whether we may need to record a pullthrough.
            if pullthru is not None:
                pullthru_required=td.stock_checkpullthru(stockitem.id,'11:00:00')
            else:
                pullthru_required=False
            # If the stock number we're selling now matches repeat_stockid
            # then we may be able to add to the previous transline rather than
            # creating a new one
            if (repeat_stockid==stockitem.id and
                self.dl[-1].age()<max_transline_modify_age):
                lid=repeat_lid
                transline=td.s.query(Transline).get(lid)
                stockout=td.s.query(StockOut).get(transline.stockref)
                # We increase the number of items by 1.
                orig_qty=stockout.qty/transline.items
                transline.items=transline.items+1
                stockout.qty=orig_qty*transline.items
                td.s.flush()
                log.info("Register: linekey: added %d to lid=%d"%
                         (items,lid))
                self.dl[-1].update()
                repeat_stockid=None
                repeat_lid=None
            else:
                if unitprice is None:
                    # Price has not been overridden
                    unitprice=tillconfig.pricepolicy(stockitem,qty).quantize(penny)
                stockout=StockOut(
                    stockitem=stockitem,qty=qty,removecode_id='sold')
                td.s.add(stockout)
                td.s.flush()
                transline=Transline(
                    transaction=self.trans,items=items,amount=unitprice,
                    department=stockitem.stocktype.department,
                    source=self.name,stockref=stockout.id,transcode='S')
                td.s.add(transline)
                td.s.flush()
                stockout.transline=transline
                td.s.flush()
                # Hmm, wonder if there's a better way to make objects
                # refer to each other?
                self.dl.append(tline(transline.id))
                log.info(
                    "Register: linekey: trans=%d,lid=%d,sn=%d,items=%d,qty=%f"
                    %(self.trans.id,transline.id,stockitem.id,items,qty))
            if repeatcandidate: self.repeat=((stocklineid,qty),transline.id,
                                             stockitem.id)
        if stockremain is None:
            # We are using the last value of stockitem from the previous
            # for loop

            self.prompt="%s: %0.1f %ss remaining"%(
                name,stockitem.remaining,stockitem.stocktype.unit.name)
            if stockitem.remaining<0.0 and not pullthru_required:
                ui.infopopup([
                    "There appears to be %0.1f %ss of %s left!  Please "
                    "check that you're still using stock item %d; if you've "
                    "started using a new item, tell the till about it "
                    "using the 'Use Stock' button after dismissing this "
                    "message."%(stockitem.remaining,
                                stockitem.stocktype.unit.name,
                                stockitem.stocktype.format(maxw=40),
                                stockitem.id),
                    "","If you don't understand this message, you MUST "
                    "call your manager to deal with it."],
                             title="Warning",dismiss=keyboard.K_USESTOCK)
        else:
            self.prompt="%s: %d left on display; %d in stock"%(
                name,stockremain[0],stockremain[1])
        self.cursor_off()
        self.update_balance() # Also updates prompt and scrolls
        if pullthru_required:
            ui.infopopup(["According to the till records, %s "
                          "hasn't been "
                          "sold or pulled through in the last 11 hours.  "
                          "Would you like to record that you've pulled "
                          "through %0.1f %ss?  "
                          "Press 'Record Waste' if you do, or Clear if "
                          "you don't."%(
                        stockitem.stocktype.format(),
                        pullthru,stockitem.stocktype.unit.name)],
                         title="Pull through?",colour=ui.colour_input,
                         keymap={
                keyboard.K_WASTE:
                (td.stock_recordwaste,(stockitem.id,'pullthru',pullthru,False),
                 True)})
    def deptkey(self,dept):
        if (self.repeat and self.repeat[0]==dept
            and self.dl[-1].age()<max_transline_modify_age):
            # Increase the quantity of the most recent entry
            log.info("Register: deptkey: adding to lid=%d"%self.repeat[1])
            tl=td.s.query(Transline).get(self.repeat[1])
            tl.items=tl.items+1
            td.s.flush()
            self.dl[-1].update()
            self.update_balance() # Also redraws screen
            return
        if self.buf is None:
            log.info("Register: deptkey: no amount entered")
            ui.infopopup(["You must enter the amount before pressing "
                          "a department button.  Please try again.","",
                          "Optionally you may enter a quantity, press "
                          "the 'Quantity' button, and then enter the "
                          "price of a single item before pressing the "
                          "department button."],title="Error")
            return
        if self.mod is not None:
            ui.infopopup(["You can't use the '%s' modifier with a "
                          "department key."%self.mod],title="Error")
            return
        if self.qty: items=self.qty
        else: items=1
        price=strtoamount(self.buf)
        self.prompt=self.defaultprompt
        self.clearbuffer()
        priceproblem=tillconfig.deptkeycheck(dept,price)
        if priceproblem is not None:
            self.cursor_off()
            self.redraw()
            if not isinstance(priceproblem,list):
                priceproblem=[priceproblem]
            ui.infopopup(priceproblem,title="Error")
            return
        trans=self.gettrans()
        if trans is None: return
        tl=Transline(transaction=trans,dept_id=dept,items=items,amount=price,
                     source=self.name,transcode='S')
        td.s.add(tl)
        td.s.flush()
        log.info("Register: deptkey: trans=%d,lid=%d,dept=%d,items=%d,"
                 "price=%f"%(trans.id,tl.id,dept,items,price))
        self.repeat=(dept,tl.id)
        self.dl.append(tline(tl.id))
        self.cursor_off()
        self.update_balance() # Also redraws
    def deptlines(self,lines):
        """Accept multiple transaction lines from an external source.

        lines is a list of (dept,text,amount) tuples; text may be None
        if the department name is to be used.

        Returns True on success; on failure, returns an error message
        as a string.

        """
        self.prompt=self.defaultprompt
        self.clearbuffer()
        trans=self.gettrans()
        if trans is None: return "Transaction cannot be started."
        for dept,text,amount in lines:
            tl=Transline(transaction=trans,dept_id=dept,items=1,amount=amount,
                         source=self.name,transcode='S',text=text)
            td.s.add(tl)
            td.s.flush()
            log.info("Register: deptlines: trans=%d,lid=%d,dept=%d,"
                     "price=%f,text=%s"%(trans.id,tl.id,dept,amount,text))
            self.dl.append(tline(tl.id))
        self.repeat=None
        self.cursor_off()
        self.update_balance()
        return True
    def gettrans(self):
        if self.trans:
            if not self.trans.closed:
                return self.trans
        self.clear()
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
            td.s.flush()
        self.redraw()
        ui.updateheader()
        return self.trans
    def drinkinkey(self):
        """The 'Drink In' key creates a negative entry in the
        transaction's payments section; the intent is that staff who
        are offered a drink that they don't want to pour immediately
        can use this key to enable the till to add the cost of their
        drink onto a transaction.  They can take the cash from the
        till tray or make a note that it's in there, and use it later
        to buy a drink.

        """
        if self.qty is not None or self.mod is not None:
            ui.infopopup(["You can't enter a quantity or use a modifier key "
                          "before pressing 'Drink In'."],title="Error")
            return
        if self.buf is None:
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
        payment=Payment(transaction=self.trans,paytype_id='CASH',
                        amount=-amount,ref="Drink 'In'")
        td.s.add(payment)
        td.s.flush()
        # XXX when we have a pline() function that takes a Payment, use it
        # here instead
        self.dl.append(rline("Drink 'In' %s"%tillconfig.fc(-amount),
                             ui.colour_changeline))
        self.cursor_off()
        self.update_balance() # Also redraws
    def cashkey(self,confirmed=False):
        # The CASH/ENTER key is also used to create a new "void" transaction
        # from lines selected from a previous, closed transaction.  If any
        # lines are selected, do that instead.
        if self.ml!=set():
            return self.cancelmarked()
        if self.qty is not None:
            log.info("Register: cashkey: payment with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        # We may have been entered from a dialog, bypassing the keypress method.
        self.refresh_trans()
        if self.trans is None or self.trans.closed:
            if self.buf is None:
                log.info("Register: cashkey: NO SALE")
                if tillconfig.nosale:
                    ui.infopopup(["No Sale has been recorded."],
                                 title="No Sale",colour=2)
                    printer.kickout()
                else:
                    ui.infopopup(["The No Sale function is not "
                                  "in use."],title="No Sale")
                return
            log.info("Register: cashkey: current transaction is closed")
            ui.infopopup(["There is no transaction in progress.  If you "
                          "want to perform a 'No Sale' transaction then "
                          "try again without entering an amount."],
                         title="Error")
            self.clearbuffer()
            self.redraw()
            return
        if self.balance is None and len(self.ml)==0 and len(self.dl)==0:
            # Special case: cash key on an empty transaction.
            # Just cancel the transaction silently.
            td.s.delete(self.trans)
            self.trans=None
            td.s.flush()
            self.clear()
            self.redraw()
            return
        # If the transaction is an old one (i.e. the "recall
        # transaction" function has been used on it) then require
        # confirmation - one of the most common user errors is to
        # recall a transaction that's being used as a tab, add some
        # lines to it, and then automatically press 'cash'.
        if self.keyguard and not confirmed:
            ui.infopopup(["Are you sure you want to close this transaction "
                          "with a cash payment?  If you are then press "
                          "Cash/Enter again.  If you pressed Cash/Enter by "
                          "mistake then press Clear now to go back."],
                         title="Confirm transaction close",
                         colour=ui.colour_confirm,keymap={
                keyboard.K_CASH:(self.cashkey,(True,),True)})
            return
        self.prompt=self.defaultprompt
        if self.buf is None:
            # Exact change, then, is it?
            log.info("Register: cashkey: exact change")
            amount=self.balance
        else:
            amount=strtoamount(self.buf)
        self.clearbuffer()
        self.redraw()
        if amount==zero:
            log.info("Register: cashkey: payment of zero")
            ui.infopopup(["You can't pay %s in cash!"%tillconfig.fc(zero),
                          'If you meant "exact change" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
            return
        payment=Payment(transaction=self.trans,amount=amount,
                        paytype_id='CASH',ref='Cash')
        td.s.add(payment)
        td.s.flush()
        self.dl.append(
            rline('Cash %s'%tillconfig.fc(amount),ui.colour_cashline))
        remain=self.trans.total-self.trans.payments_total
        if remain<zero:
            # There's some change!
            log.info("Register: cashkey: calculated change")
            payment=Payment(transaction=self.trans,amount=remain,
                            paytype_id='CASH',ref='Change')
            td.s.add(payment)
            td.s.flush()
            self.dl.append(rline('Change %s'%tillconfig.fc(remain),
                                 ui.colour_changeline))
        self.close_if_balanced()
        self.cursor_off()
        self.update_balance()
        ui.updateheader()
        printer.kickout()
    def notekey(self,amount):
        if self.qty is not None or self.buf is not None:
            log.info("Register: notekey: error popup")
            ui.infopopup(["You can only press a note key when you "
                          "haven't already entered a quantity or amount.",
                          "After dismissing this message, press Clear "
                          "and try again."],title="Error")
            return
        self.buf=str(amount)
        log.info("Register: notekey %d"%amount)
        return self.cashkey()
    def cardkey(self,amount=None,receiptno=None,cashback=None):
        self.refresh_trans()
        if self.qty is not None:
            log.info("Register: cardkey: payment with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.trans is None or self.trans.closed:
            log.info("Register: cardkey: closed or no transaction")
            ui.infopopup(["There is no transaction in progress."],
                         title="Error")
            self.clearbuffer()
            self.redraw()
            return
        self.prompt=self.defaultprompt
        if amount is None:
            if self.buf is None:
                # Exact change, then, is it?
                log.info("Register: cardkey: exact amount")
                amount=self.balance
            else:
                amount=strtoamount(self.buf)
            if amount is None: return # Empty transaction
            return cardpopup(amount,self.cardkey)
        else:
            log.info("Register: cardkey: explicit amount specified in call")
        if amount==zero:
            log.info("Register: cardkey: payment of zero")
            ui.infopopup(["You can't pay %s by card!"%tillconfig.fc(zero),
                          'If you meant "exact amount" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
            return
        self.clearbuffer()
        # We have a non-zero amount and a transaction. Pay it!
        payment=Payment(transaction=self.trans,amount=amount,
                        paytype_id='CARD',ref=receiptno)
        td.s.add(payment)
        self.dl.append(rline('Card %s %s'%(receiptno,tillconfig.fc(amount)),
                             ui.colour_cashline))
        if cashback:
            payment=Payment(transaction=self.trans,amount=-cashback,
                            paytype_id='CASH',ref='Cashback')
            td.s.add(payment)
            self.dl.append(rline('Cashback %s'%tillconfig.fc(cashback),
                                 ui.colour_changeline))
        self.close_if_balanced()
        self.cursor_off()
        self.update_balance()
        ui.updateheader()
        printer.kickout()
    def bitcoinkey(self):
        """
        Accept a Bitcoin payment.  This is currently quite primitive:
        we only permit one payment per transaction (because we pass
        the transaction number to the payment service provider to
        allow for the transaction to be restarted if necessary), and
        that payment must be for the whole outstanding balance of the
        transaction.

        In the future we will permit multiple payments per
        transaction, but this will have to wait until we reorganise
        the database layer to expose the paymentid so we can use that
        as a reference instead.

        """
        if self.qty is not None:
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.trans is None or self.trans.closed:
            ui.infopopup(["There is no transaction in progress."],
                         title="Error")
            self.clearbuffer()
            self.redraw()
            return
        self.prompt=self.defaultprompt
        for p in self.trans.payments:
            if p.paytype_id=='BTC':
                ui.infopopup(["This transaction has already been paid by "
                              "Bitcoin; no other Bitcoin payments can be "
                              "accepted for it."],title="Error")
                return
        self.clearbuffer()
        return btcpopup(self.bitcoin,self.trans.id,self.balance)
    def bitcoin(self,amount,btcamount):
        """
        We've been paid by bitcoin!

        """
        self.refresh_trans()
        payment=Payment(transaction=self.trans,amount=amount,
                        paytype_id='BTC',ref=btcamount)
        td.s.add(payment)
        td.s.flush()
        self.dl.append(rline('Bitcoin %s %s'%(btcamount,tillconfig.fc(amount)),
                             ui.colour_cashline))
        # Cashback should never arise; however, it is possible for the
        # Bitcoin payment not to cover the whole transaction.
        self.close_if_balanced()
        self.cursor_off()
        self.update_balance()
        ui.updateheader()
    def numkey(self,n):
        if (self.buf==None and self.qty==None and self.trans is not None and
            self.trans.closed):
            log.info("Register: numkey on closed transaction; "
                     "clearing display")
            self.clear()
            self.redraw()
        self.cursor_off()
        if self.buf is None: self.buf=""
        if len(self.buf)>=10:
            self.clearkey()
            log.info("Register: numkey: buffer overflow")
            ui.infopopup(["Numerical values entered here can be at most "
                          "ten digits long.  Please try again."],
                         title="Error",colour=1)
        else:
            self.buf="%s%s"%(self.buf,n)
            # Remove leading zeros
            while len(self.buf)>0 and self.buf[0]=='0': self.buf=self.buf[1:]
            if len(self.buf)==0: self.buf='0'
            # Insert a leading zero if first character is a point
            if self.buf[0]=='.': self.buf="0%s"%self.buf
            # Check that there's no more than one point
            if self.buf.count('.')>1:
                log.info("Register: numkey: multiple points")
                ui.infopopup(["You can't have more than one point in "
                              "a number!  Please try again."],
                             title="Error")
                self.buf=None
            self.update_bufferline()
            self.redraw()
    def quantkey(self):
        if self.qty is not None:
            log.info("Register: quantkey: already entered")
            ui.infopopup(["You have already entered a quantity.  If "
                          "you want to change it, press Clear after "
                          "dismissing this message."],title="Error")
            return
        if self.buf is None: q=0
        else:
            if self.buf.find('.')>0: q=0
            else:
                q=int(self.buf)
        self.buf=None
        if q>0:
            self.qty=q
        else:
            log.info("Register: quantkey: whole number required")
            ui.infopopup(["You must enter a whole number greater than "
                          "zero before pressing Quantity."],
                         title="Error")
        self.cursor_off()
        self.update_bufferline()
        self.redraw()
    def modkey(self,k):
        self.mod=ui.kb.keycap(k)
        self.cursor_off()
        self.update_bufferline()
        self.redraw()
    def clearkey(self):
        if (self.buf==None and self.qty==None and self.trans is not None and
            self.trans.closed):
            log.info("Register: clearkey on closed transaction; "
                     "clearing display")
            self.clear()
            self.redraw()
        else:
            log.info("Register: clearkey on open or null transaction; "
                     "clearing buffer")
            self.cursor_off()
            self.clearbuffer()
            self.redraw()
    def printkey(self):
        if self.trans is None:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key."],title="Error")
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
        self.refresh_trans()
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
            for l in self.trans.lines:
                if l.stockref:
                    so=td.s.query(StockOut).get(l.stockref)
                    if so: td.s.delete(so)
                td.s.delete(l)
            td.s.delete(self.trans)
            self.trans=None
            td.s.flush()
            if payments>zero:
                printer.kickout()
                refundtext="%s had already been put in the cash drawer."%(
                    tillconfig.fc(payments))
            else: refundtext=""
            self.clear()
            self.redraw()
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
        self.refresh_trans()
        if self.trans.closed:
            l=self.dl[self.s.cursor]
            if isinstance(l,rline):
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
            self.update_bufferline()
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
                        self.cursor_off()
                        self.update_balance()
                        if len(self.dl)==0:
                            # The last transaction line was deleted, so also
                            # delete the transaction.
                            self.canceltrans()
                    else:
                        log.info("Register: cancelline: reverse "
                                 "transline %d"%transline)
                        self.voidline(transline)
                        self.cursor_off()
                        self.update_balance()
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
        Add a line reversing the supplied transaction line to the current
        transaction.  tl is a Transline id

        """
        trans=self.gettrans()
        transline=td.s.query(Transline).get(tl)
        if transline.stockref is not None:
            stockout=td.s.query(StockOut).get(transline.stockref)
            nso=StockOut(
                stockitem=stockout.stockitem,qty=-stockout.qty,
                removecode=stockout.removecode)
            td.s.add(nso)
            td.s.flush()
            ntl=Transline(
                transaction=trans,items=-transline.items,
                amount=transline.amount,department=transline.department,
                source=self.name,stockref=nso.id,transcode='V')
            td.s.add(ntl)
            td.s.flush()
            nso.transline=ntl
            td.s.flush()
        else:
            ntl=Transline(
                transaction=trans,items=-transline.items,
                amount=transline.amount,department=transline.department,
                source=self.name,transcode='V',text=transline.text)
            td.s.add(ntl)
            td.s.flush()
        self.dl.append(tline(ntl.id))
    def cancelmarked(self):
        tl=list(self.ml)
        self.clear()
        trans=self.gettrans()
        if trans is None: return
        log.info("Register: cancelmarked %s; new trans=%d"%(str(tl),trans.id))
        for i in tl:
            self.voidline(i)
        self.cursor_off()
        self.update_balance()
        # XXX To deal properly with voids of card transactions, perhaps we
        # should leave the voiding transaction open here and allow the
        # operator to close with Cash or Card key as appropriate.  We'd
        # need to make sure that negative card payments work properly for
        # refunds!   Also, since this would be a change in behaviour, perhaps
        # we should pop up an explanatory dialog box here.
        self.cashkey()
    def recalltrans(self,trans):
        self.clear()
        if trans is not None:
            log.info("Register: recalltrans %d"%trans)
            registry.announce(self.name,trans)
            self.trans=td.s.query(Transaction).get(trans)
            self.keyguard=True
            self.update_note()
            for i in self.trans.lines:
                self.dl.append(tline(i.id))
            for i in self.trans.payments:
                self.dl.append(payline((i.amount,i.paytype_id,
                                        i.paytype.description,i.ref)))
            if not self.trans.closed:
                age=self.trans.age
                if age>2:
                    ui.infopopup(["This transaction is %d days old.  Please "
                                  "arrange for it to be paid soon."%age],
                                 title="Warning")
        self.cursor_off()
        self.update_balance()
    def recalltranskey(self):
        sc=Session.current(td.s)
        if sc is None:
            log.info("Register: recalltrans: no session")
            ui.infopopup(["There is no session in progress.  You can "
                          "only recall transactions that belong to the "
                          "current session."],title="Error")
            return
        log.info("Register: recalltrans")
        if (tillconfig.allow_tabs is False and self.keyguard is False and
            not (self.trans is None or self.trans.closed)):
            ui.infopopup(["We do not run tabs.  Food and drink must "
                          "be paid for at the time it is ordered."],
                         title="Error")
            return
        tl=sc.transactions
        def transsummary(t):
            return ("%d"%t.id,('open','closed')[t.closed],
                    tillconfig.fc(t.total),t.notes if t.notes else u'')
        lines=ui.table([transsummary(x) for x in tl]).format(' r l r l ')
        sl=[(x,self.recalltrans,(t.id,)) for x,t in zip(lines,tl)]
        ui.menu([('New Transaction',self.recalltrans,(None,))]+sl,
                title="Recall Transaction",
                blurb="Select a transaction and press Cash/Enter.",
                colour=ui.colour_input)
    def firstpageinit(self):
        sc=Session.current(td.s)
        if sc is None: return
        tl=[t for t in sc.transactions if not t.closed]
        if len(tl)<1: return
        lines=ui.table([("%d"%t.id,tillconfig.fc(t.total),
                         t.notes if t.notes else u'')
                         for t in tl]).format(' r r l ')
        sl=[(x,self.recalltrans,(t.id,)) for x,t in zip(lines,tl)]
        ui.menu([('New Transaction',self.recalltrans,(None,))]+sl,
                title="Open Transactions",
                blurb="There are some transactions already open.  Choose one "
                "from the list below to continue with it.  You can get back "
                "to this list by pressing the 'Recall Transaction' button.",
                colour=ui.colour_input)
    def defertrans(self,transid):
        trans=td.s.query(Transaction).get(transid)
        if trans.closed:
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be deferred."%trans.id],title="Error")
            return
        self.clear()
        self.redraw()
        trans.session=None
        td.s.flush()
        ui.infopopup(["Transaction %d has been deferred to the next "
                      "session.  Make sure you keep a note of the "
                      "transaction number and the name of the person "
                      "responsible for paying it!"%transid],
                     title="Transaction defer confirmed",
                     colour=ui.colour_confirm,dismiss=keyboard.K_CASH)
    def freedrinktrans(self,transid):
        # Temporarily disable this function - SDE 5/6/09
        ui.infopopup(["This function is no longer available.  Instead you "
                      "must write a note to Steve with the transaction IDs "
                      "that need to be converted, and he will do it after "
                      "checking very carefully!"],
                     title="Convert to Free Drinks")
        return
        #if td.trans_closed(transid):
        #    ui.infopopup(["Transaction %d has been closed, and cannot now "
        #                  "be converted to free drinks."%transid],
        #                 title="Error")
        #    return
        #lines,payments=td.trans_getlines(transid)
        #if len(payments)>0:
        #    ui.infopopup(["Some payments have already been entered against "
        #                  "transaction %d, so it can't be converted to "
        #                  "free drinks."%transid],
        #                 title="Error")
        #    return
        #td.trans_makefree(transid,'freebie')
        #self.clear()
        #self.redraw()
        #ui.infopopup(["Transaction %d has been converted to free drinks."%
        #              transid],title="Free Drinks",colour=ui.colour_confirm,
        #             dismiss=keyboard.K_CASH)
    def mergetransmenu(self,transid):
        sc=Session.current(td.s)
        log.info("Register: mergetrans")
        tl=[t for t in sc.transactions if not t.closed]
        def transsummary(t):
            return ("%d"%t.id,tillconfig.fc(t.total),t.notes if t.notes else u'')
        lines=ui.table([transsummary(x) for x in tl]).format(' r r l ')
        sl=[(x,self.mergetrans,(transid,t.id)) for x,t in zip(lines,tl)
            if t.id!=transid]
        ui.menu(sl,
                title="Merge with transaction",
                blurb="Select a transaction to merge this one into, "
                "and press Cash/Enter.",
                colour=ui.colour_input)
    def mergetrans(self,transid,othertransid):
        trans=td.s.query(Transaction).get(transid)
        othertrans=td.s.query(Transaction).get(othertransid)
        if trans.closed:
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be merged with another transaction."%transid],
                         title="Error")
            return
        if len(trans.payments)>0:
            ui.infopopup(["Some payments have already been entered against "
                          "transaction %d, so it can't be merged with another "
                          "transaction."%transid],
                         title="Error")
            return
        if othertrans.closed:
            ui.infopopup(["Transaction %d has been closed, so we can't "
                          "merge this transaction into it."%othertrans.id],
                         title="Error")
            return
        for line in trans.lines:
            line.transid=othertrans.id
        td.s.flush()
        # At this point the ORM still believes the translines belong
        # to the original transaction, and will attempt to set their transid
        # fields to NULL when we delete it.  Refresh here!
        # XXX is it possible to get the ORM to update this automatically?
        td.s.refresh(trans)
        td.s.delete(trans)
        td.s.flush()
        self.recalltrans(othertransid)
    def settransnote(self,trans,notes):
        if notes=="": notes=None
        t=td.s.query(Transaction).get(trans)
        t.notes=notes
        self.update_note()
        self.redraw()
    def settransnotes_menu(self,trans):
        sl=[(x,self.settransnote,(trans,x))
            for x in tillconfig.transaction_notes]
        ui.menu(sl,
                title="Notes for transaction %d"%trans,
                blurb="Choose the new transaction note and press Cash/Enter.",
                colour=ui.colour_input)
    def managetranskey(self):
        if self.trans is None or self.trans.closed:
            ui.infopopup(["You can only modify an open transaction."],
                         title="Error")
            return
        menu=[(keyboard.K_ONE,"Defer transaction to next session",
               self.defertrans,(self.trans.id,))]
        if tillconfig.transaction_to_free_drinks_function:
            menu=menu+[(keyboard.K_TWO,"Convert transaction to free drinks",
                        self.freedrinktrans,(self.trans.id,))]
        menu=menu+[(keyboard.K_THREE,"Merge this transaction with another "
                    "open transaction",self.mergetransmenu,(self.trans.id,)),
                   (keyboard.K_FOUR,"Set this transaction's notes "
                    "(from menu)",self.settransnotes_menu,(self.trans.id,)),
                   (keyboard.K_FIVE,"Change this transaction's notes "
                    "(free text entry)",
                    edittransnotes,(self.trans,self.update_note))]
        if tillconfig.btcmerch_api:
            menu=menu+[(keyboard.K_SEVEN,"Pay by Bitcoin",
                        self.bitcoinkey,None)]
        ui.keymenu(menu,title="Transaction %d"%self.trans.id)
    def refresh_trans(self):
        if self.trans:
            td.s.add(self.trans)
            td.s.refresh(self.trans)
    def keypress(self,k):
        # This is our main entry point.  We will have a new database session.
        # Update the transaction object before we do anything else!
        self.refresh_trans()
        if isinstance(k,magcard.magstripe):
            return magcard.infopopup(k)
        if k in keyboard.lines:
            stocklines.linemenu(k,self.linekey)
            return
        if k in keyboard.depts:
            return self.deptkey(keyboard.depts[k])
        self.repeat=None
        if k in keyboard.notes:
            return self.notekey(keyboard.notes[k])
        if k in keyboard.numberkeys or k==keyboard.K_ZEROZERO:
            return self.numkey(ui.kb.keycap(k))
        keys={
            keyboard.K_CASH: self.cashkey,
            keyboard.K_CARD: self.cardkey,
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
        if k in [keyboard.K_4JUG,keyboard.K_DOUBLE,keyboard.K_HALF]:
            return self.modkey(k)
        if k==keyboard.K_FOODORDER:
            trans=self.gettrans()
            if trans is None: return
            return foodorder.popup(self.deptlines,transid=trans.id)
        if k==keyboard.K_CANCELFOOD:
            return foodorder.cancel()
        curses.beep()

registry=transnotify()
