"""Cash register page.  Allows transaction entry, voiding of lines.
Also supports function keys to go to various popups: price lookup, management,
etc."""

import magcard,tillconfig
import sets,curses
import td,ui,keyboard,printer
import stock,stocklines
import logging
from managetill import popup as managetill
from managestock import popup as managestock
from plu import popup as plu
from usestock import popup as usestock
from recordwaste import popup as recordwaste
log=logging.getLogger()

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

# Also used for voids...
class tline:
    def __init__(self,transline):
        self.transline=transline
    def display(self,win,y,ml,hl=False):
        (h,w)=win.getmaxyx()
        if self.transline in ml:
            colour=curses.color_pair(ui.colour_cancelline)
        else: colour=curses.color_pair(0)
        attr=(colour,colour|curses.A_REVERSE)[hl]
        # Fetch details of this transaction line and format them...
        (trans,items,amount,dept,deptstr,stockref,
         transcode)=td.trans_getline(self.transline)
        if stockref is not None:
            (qty,removecode,stockid,manufacturer,name,shortname,abv,
             unitname)=td.stock_fetchline(stockref)
            abvs=stock.abvstr(abv)
            qty=qty/items
            qtys=tillconfig.qtystring(qty,unitname)
            ss="%s %s%s %s"%(manufacturer,name,abvs,qtys)
            if len(ss)>w:
                ss="%s %s %s"%(shortname,qtys,unitname)
                if len(ss)>w:
                    ss=ss[:w]
        else:
            ss=deptstr
        win.insstr(y,0,' '*w,attr)
        win.insstr(y,0,ss,attr)
        astr="%d @ %s = %s"%(items,tillconfig.fc(amount),
                             tillconfig.fc(items*amount))
        win.insstr(y,w-len(astr),astr,attr)

# Used for payments etc.
class rline:
    def __init__(self,text,attr):
        self.text=text
        self.attr=curses.color_pair(attr)
    def display(self,win,y,ml,hl=False):
        (h,w)=win.getmaxyx()
        attr=(self.attr,self.attr|curses.A_REVERSE)[hl]
        win.insstr(y,0,' '*w,attr)
        win.insstr(y,w-len(self.text),self.text,attr)

def payline(p):
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
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        win=self.pan.window()
        win.addstr(2,2,"Card payment of %s"%tillconfig.fc(amount))
        win.addstr(4,2,"Please enter the receipt number from the")
        win.addstr(5,2,"credit card receipt.")
        win.addstr(7,2," Receipt number:")
        km={keyboard.K_CLEAR: (self.dismiss,None,True)}
        self.rnfield=ui.editfield(win,7,19,16,keymap=km)
        win.addstr(9,2,"Is there any cashback?  Enter amount and")
        win.addstr(10,2,"press Cash/Enter.  Leave blank and press")
        win.addstr(11,2,"Cash/Enter if there is none.")
        win.addstr(13,2,"Cashback amount: %s"%tillconfig.currency)
        km={keyboard.K_CASH: (self.enter,None,False),
            keyboard.K_CARD: (self.enter,None,False),
            keyboard.K_TWENTY: (self.note,(20.0,),False),
            keyboard.K_TENNER: (self.note,(10.0,),False),
            keyboard.K_FIVER: (self.note,(5.0,),False),
            keyboard.K_CLEAR: (self.dismiss,None,True)}
        self.cbfield=ui.editfield(win,13,19+len(tillconfig.currency),6,
                                validate=ui.validate_float,
                                keymap=km)
        ui.map_fieldlist([self.rnfield,self.cbfield])
        self.rnfield.focus()
    def note(self,size):
        self.cbfield.set("%0.2f"%size)
        self.enter()
    def enter(self):
        try:
            cba=float(self.cbfield.f)
        except:
            cba=0.0
        if cba>tillconfig.cashback_limit:
            self.cbfield.set("")
            return ui.infopopup(["Cashback is limited to a maximum of %s per "
                                 "transaction."%tillconfig.fc(
                tillconfig.cashback_limit)],title="Error")
        total=self.amount+cba
        receiptno=self.rnfield.f
        self.dismiss()
        self.func(total,receiptno)

class page(ui.basicpage):
    def __init__(self,panel,name):
        global registry
        ui.basicpage.__init__(self,panel)
        self.name=name
        registry.register(self)
        self.clear()
        self.redraw()
    def clear(self):
        self.dl=[] # Display list
        self.ml=sets.Set() # Marked transactions set
        self.top=0 # Top line of display
        self.cursor=None # Cursor position
        self.trans=None # Current transaction
        self.repeat=None # If dept/line button pressed, update this transline
        self.balance=None # Balance of current transaction
        self.prompt="Ready"
        self.buf=None # Input buffer
        self.qty=None # Quantity (integer)
        self.mod=None # Modifier (string)
        self.keyguard=False # Require confirmation for 'Cash' or 'Cancel'
    def pagename(self):
        if self.trans is not None:
            ts=" - Transaction %d (%s)"%(self.trans,("open","closed")
                                         [td.trans_closed(self.trans)])
        else: ts=""
        return "%s%s"%(self.name,ts)
    def pagesummary(self):
        if self.trans is None: return ""
        elif td.trans_closed(self.trans): return ""
        else: return "%s:%d"%(self.name[0],self.trans)
    def tnotify(self,name,trans):
        "Receive notification that another page has claimed this transaction"
        if trans==0 or (self.name!=name and self.trans==trans):
            self.clear()
            self.redraw()
    def drawline(self,li):
        if li=='buf': li=len(self.dl)+1
        y=li-self.top
        if self.qty is not None: m="%d of "%self.qty
        else: m=""
        if self.mod is not None: m="%s%s "%(m,self.mod)
        if self.buf is not None: m="%s%s"%(m,self.buf)
        if y>=0 and y<self.h:
            self.win.insstr(y,0,' '*self.w)
            if y==0 and self.top>0:
                self.win.addstr(y,0,'...')
            elif li<len(self.dl):
                self.dl[li].display(self.win,y,self.ml,self.cursor==li)
            elif li==len(self.dl)+1:
                if len(m)>0:
                    self.win.addstr(y,0,m)
                else:
                    self.win.addstr(y,0,self.prompt)
                if self.balance:
                    bstr="%s %s"%(("Change","Amount to pay")
                                  [self.balance>=0.0],
                                  tillconfig.fc(self.balance))
                    self.win.insstr(y,self.w-len(bstr),bstr)
        # Position cursor?
        if self.cursor is None:
            cy=len(self.dl)+1-self.top
            if cy>=self.h: cy=0
            cx=len(m)
        else:
            cy=self.cursor-self.top
            cx=0
        if cy>=self.h: cy=self.h-1
        self.win.move(cy,cx)
    def redraw(self):
        self.win.clear()
        for i in range(0,len(self.dl)+2):
            self.drawline(i)
        ui.updateheader(self)
    def cursor_up(self):
        if self.cursor is None:
            if len(self.dl)>0:
                self.cursor=len(self.dl)-1
        elif self.cursor>0:
            self.cursor=self.cursor-1
        if self.cursor<self.top+1:
            self.top=self.top-(self.h/3)
            if self.top<0: self.top=0
            self.redraw()
        else:
            self.drawline(self.cursor)
            self.drawline(self.cursor+1)
    def cursor_down(self):
        if self.cursor is None: return
        if self.cursor<len(self.dl)-1:
            self.cursor=self.cursor+1
            if (self.cursor-self.top)>=self.h-2:
                self.top=self.top+(self.h/3)
                self.redraw()
            else:
                self.drawline(self.cursor-1)
                self.drawline(self.cursor)
    def cursor_off(self):
        # Scroll so that buffer/balance line is visible
        oldtop=self.top
        self.top=len(self.dl)-self.h+3
        if self.top<0: self.top=0
        if self.cursor is not None:
            c=self.cursor
            self.cursor=None
            self.drawline(c)
        if self.top!=oldtop: self.redraw()
    def addline(self,litem):
        self.dl.append(litem)
        self.cursor_off()
        if (len(self.dl)-self.top)>self.h-2:
            self.top=len(self.dl)-(self.h*2/3)
            self.redraw()
        else:
            self.drawline(len(self.dl)-1)
            self.drawline(len(self.dl))
            self.drawline(len(self.dl)+1)
    def update_balance(self):
        if self.trans:
            (lines,payments)=td.trans_balance(self.trans)
            self.balance=lines-payments
        else: self.balance=None
        self.drawline('buf')
    def linekey(self,line):
        name,qty,dept,pullthru,menukey,stocklineid,location,capacity=line
        repeat_lid=None
        repeat_stockid=None
        if self.repeat is not None:
            if self.repeat[0]==line:
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
            if self.buf.find('.')>=0:
                unitprice=float(self.buf)
            else:
                unitprice=float(self.buf)/100.0
            log.info("Register: linekey: manual price override to %0.2f"%(
                unitprice))
            self.buf=None
        else:
            unitprice=None
        if self.qty is not None: items=self.qty
        else: items=1
        self.qty=None
        repeatcandidate=False
        checkdept=None
        if self.mod=='Half':
            qty=0.5
            checkdept=[1,2,3] # must be ale, keg or cider
        if self.mod=='Double':
            qty=2.0
            checkdept=[4] # must be spirits
        elif self.mod=='4pt Jug':
            qty=4.0
            checkdept=[1,2,3] # must be ale, keg, cider
        else:
            repeatcandidate=True
        # Now we know how many we are trying to sell.
        (sell,unallocated,snd,stockremain)=(
            stocklines.calculate_sale(stocklineid,items))
        if capacity is not None and unallocated>0:
            ui.infopopup(
                ["There are fewer than %d items of %s on display.  "
                 "If you have recently put more stock on display you "
                 "must tell the till about it using the 'Use Stock' "
                 "button after dismissing this message."%(
                items,name)],title="Not enough stock on display")
            return
        if sell==[]:
            log.info("Register: linekey: no stock in use for %s"%name)
            ui.infopopup(["No stock is registered for %s."%name,
                          "To tell the till about stock on sale, "
                          "press the 'Use Stock' button after "
                          "dismissing this message."],
                         title="%s has no stock"%name)
            return
        # We might have to abort if an invalid modifier key has been used.
        if checkdept is not None:
            for stockid,items in sell:
                dept=snd[stockid]['dept']
                if dept not in checkdept:
                    ui.infopopup(["You can't use the '%s' modifier with "
                                  "stock in department %d."%(self.mod,dept)],
                                 title="Error")
                    return
        self.mod=None # we wait until now to clear it so it's usable
                      # in the error message
        # At this point we have a list of (stockid,amount) that corresponds
        # to the quantity requested.  We can go ahead and add them to the
        # transaction.
        trans=self.gettrans()
        if trans is None: return
        # By this point we're committed to trying to sell the items.
        for stockid,items in sell:
            sd=snd[stockid]
            # Check first to see whether we may need to record a pullthrough.
            if pullthru is not None:
                pullthru_required=td.stock_checkpullthru(stockid,'11:00:00')
            else:
                pullthru_required=False
            # If the stock number we're selling now matches repeat_stockid
            # then we can add to the previous transline rather than
            # creating a new one
            if repeat_stockid==stockid:
                lid=repeat_lid
                log.info("Register: linekey: added %d to lid=%d"%
                         (items,lid))
                td.stock_sellmore(lid,items)
                self.drawline(len(self.dl)-1)
                repeat_stockid=None
                repeat_lid=None
            else:
                if unitprice is None: unitprice=tillconfig.pricepolicy(sd,qty)
                lid=td.stock_sell(self.trans,sd['dept'],stockid,items,qty,
                                  unitprice,self.name,'S')
                self.addline(tline(lid))
                log.info(
                    "Register: linekey: trans=%d,lid=%d,sn=%d,items=%d,qty=%f"
                    %(self.trans,lid,stockid,items,qty))
            if repeatcandidate: self.repeat=(line,lid,stockid)
        if stockremain is None:
            sd=snd[stockid]
            self.prompt="%s: %0.1f %ss remaining"%(
                name,sd['remaining']-(qty*items),sd['unitname'])
            if sd['remaining']-(qty*items)<0.0 and not pullthru_required:
                ui.infopopup([
                    "There appears to be %0.1f %ss of %s left!  Please "
                    "check that you're still using stock item %d; if you've "
                    "started using a new item, tell the till about it "
                    "using the 'Use Stock' button after dismissing this "
                    "message."%(sd['remaining']-(qty*items),sd['unitname'],
                                stock.format_stock(sd,maxw=40),sd['stockid'])],
                             title="Warning")
        else:
            self.prompt="%s: %d left on display; %d in stock"%(
                name,stockremain[0],stockremain[1])
        self.update_balance()
        if pullthru_required:
            sd=snd[stockid]
            sd['pullthruqty']=pullthru
            ui.infopopup(["According to the till records, %(manufacturer)s "
                          "%(name)s hasn't been "
                          "sold or pulled through in the last 11 hours.  "
                          "Would you like to record that you've pulled "
                          "through %(pullthruqty)0.1f %(unitname)ss?  "
                          "Press 'Record Waste' if you do, or Clear if "
                          "you don't."%sd],
                         title="Pull through?",colour=ui.colour_input,
                         keymap={
                keyboard.K_WASTE:
                (td.stock_recordwaste,(stockid,'pullthru',pullthru,False),
                 True)})
    def deptkey(self,dept):
        if self.repeat and self.repeat[0]==dept:
            # Increase the quantity of the most recent entry
            log.info("Register: deptkey: adding to lid=%d"%self.repeat[1])
            td.trans_additems(self.repeat[1],1)
            self.drawline(len(self.dl)-1)
            self.update_balance()
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
        self.prompt="Ready"
        if self.mod is not None:
            ui.infopopup(["You can't use the '%s' modifier with a "
                          "department key."%self.mod],title="Error")
            return
        if self.qty: items=self.qty
        else: items=1
        if self.buf.find('.')>=0:
            price=float(self.buf)
        else:
            price=float(self.buf)/100.0
        self.buf=None
        self.qty=None
        trans=self.gettrans()
        if trans is None: return
        lid=td.trans_addline(trans,dept,items,price,self.name,'S')
        log.info("Register: deptkey: trans=%d,lid=%d,dept=%d,items=%d,"
                 "price=%f"%(trans,lid,dept,items,price))
        self.repeat=(dept,lid)
        self.addline(tline(lid))
        self.update_balance()
    def gettrans(self):
        if self.trans:
            if not td.trans_closed(self.trans):
                return self.trans
        self.clear()
        self.trans=td.trans_new(note=self.name)
        if self.trans is None:
            log.info("Register: gettrans: no session active")
            ui.infopopup(["No session is active.",
                          "You must use the Management menu "
                          "to start a session before you "
                          "can sell anything."],
                         title="Error")
        self.redraw()
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
        if self.buf.find('.')>=0:
            amount=float(self.buf)
        else:
            amount=float(self.buf)/100.0
        self.buf=None
        if self.trans is None or td.trans_closed(self.trans):
            ui.infopopup(["A Drink 'In' can't be the only item in a "
                          "transaction; it must be added to a transaction "
                          "that is already open."],title="Error")
            return
        trans=self.gettrans()
        if trans is None: return
        td.trans_addpayment(trans,'CASH',-amount,"Drink 'In'")
        self.addline(rline("Drink 'In' %s"%tillconfig.fc(-amount),
                           ui.colour_changeline))
        self.update_balance()
        ui.updateheader(self)
    def cashkey(self,confirmed=False):
        # The CASH/ENTER key is also used to create a new "void" transaction
        # from lines selected from a previous, closed transaction.  If any
        # lines are selected, do that instead.
        if self.ml!=sets.Set():
            return self.cancelmarked()
        self.prompt="Ready"
        if self.qty is not None:
            log.info("Register: cashkey: payment with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.trans is None or td.trans_closed(self.trans):
            if self.buf is None:
                log.info("Register: cashkey: NO SALE")
                ui.infopopup(["No Sale has been recorded."],
                             title="No Sale",colour=2)
                printer.kickout()
                return
            log.info("Register: cashkey: current transaction is closed")
            ui.infopopup(["There is no transaction in progress.  If you "
                          "want to perform a 'No Sale' transaction then "
                          "try again without entering an amount."],
                         title="Error")
            self.buf=None
            self.drawline('buf')
            return
        if self.buf is None:
            # Exact change, then, is it?
            log.info("Register: cashkey: exact change")
            amount=self.balance
        else:
            if self.buf.find('.')>=0:
                amount=float(self.buf)
            else:
                amount=float(self.buf)/100.0
        if amount==0.0:
            log.info("Register: cashkey: payment of zero")
            ui.infopopup(["You can't pay %s in cash!"%tillconfig.fc(0.0),
                          'If you meant "exact change" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
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
            self.drawline('buf')
            return
        self.buf=None
        # We have a non-zero amount and a transaction. Pay it!
        remain=td.trans_addpayment(self.trans,'CASH',amount,'Cash')
        self.addline(rline('Cash %s'%tillconfig.fc(amount),ui.colour_cashline))
        if remain<0.0:
            # There's some change!
            log.info("Register: cashkey: calculated change")
            td.trans_addpayment(self.trans,'CASH',remain,'Change')
            self.addline(rline('Change %s'%tillconfig.fc(remain),
                               ui.colour_changeline))
        self.update_balance()
        ui.updateheader(self)
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
    def cardkey(self,amount=None,receiptno=None):
        self.prompt="Ready"
        if self.qty is not None:
            log.info("Register: cardkey: payment with quantity not allowed")
            ui.infopopup(["You can't enter a quantity before telling "
                          "the till about a payment.  After dismissing "
                          "this message, press Clear and try again."],
                         title="Error")
            return
        if self.trans is None or td.trans_closed(self.trans):
            log.info("Register: cardkey: closed or no transaction")
            ui.infopopup(["There is no transaction in progress."],
                         title="Error")
            self.buf=None
            self.drawline('buf')
            return
        if amount is None:
            if self.buf is None:
                # Exact change, then, is it?
                log.info("Register: cardkey: exact amount")
                amount=self.balance
            else:
                if self.buf.find('.')>=0:
                    amount=float(self.buf)
                else:
                    amount=float(self.buf)/100.0
            return cardpopup(amount,self.cardkey)
        else:
            log.info("Register: cardkey: explicit amount specified in call")
        if amount==0.0:
            log.info("Register: cardkey: payment of zero")
            ui.infopopup(["You can't pay %s by card!"%tillconfig.fc(0.0),
                          'If you meant "exact amount" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
            return
        self.buf=None
        # We have a non-zero amount and a transaction. Pay it!
        remain=td.trans_addpayment(self.trans,'CARD',amount,receiptno)
        self.addline(rline('Card %s %s'%(receiptno,tillconfig.fc(amount)),
                           ui.colour_cashline))
        if remain<0.0:
            # There's some change!
            log.info("Register: cardkey: calculated cashback")
            td.trans_addpayment(self.trans,'CASH',remain,'Cashback')
            self.addline(rline('Cashback %s'%tillconfig.fc(remain),
                               ui.colour_changeline))
        self.update_balance()
        ui.updateheader(self)
        printer.kickout()
        
    def numkey(self,n):
        if (self.buf==None and self.qty==None and self.trans is not None and
            td.trans_closed(self.trans)):
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
            self.drawline('buf')
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
        self.drawline('buf')
    def modkey(self,k):
        self.mod=ui.kb.keycap(k)
        self.drawline('buf')
    def clearkey(self):
        if (self.buf==None and self.qty==None and self.trans is not None and
            td.trans_closed(self.trans)):
            log.info("Register: clearkey on closed transaction; "
                     "clearing display")
            self.clear()
            self.redraw()
        else:
            log.info("Register: clearkey on open transaction; clearing buffer")
            self.cursor_off()
            self.qty=None
            self.buf=None
            self.mod=None
            self.drawline('buf')
    def printkey(self):
        if self.trans is None:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key."],title="Error")
            return
        log.info("Register: printing transaction %d"%self.trans)
        printer.print_receipt(self.trans)
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
                "removed immediately.  If you're looking at a closed "
                "transaction, you must select the lines you're "
                "interested in and then press Cash/Enter to void them."],
                         title="Help on Cancel")
        else:
            if self.cursor is None:
                log.info("Register: cancelkey confirm kill "
                         "transaction %d"%self.trans)
                ui.infopopup(["Are you sure you want to %s all of "
                              "transaction number %d?  Press Cash/Enter "
                              "to confirm, or Clear to go back."%(
                              ("cancel","void")[td.trans_closed(self.trans)],
                              self.trans)],
                             title="Confirm Transaction Cancel",
                             keymap={
                    keyboard.K_CASH: (self.canceltrans,None,True)})
            else:
                self.cancelline()
    def canceltrans(self):
        # Yes, they really want to do it.  But is it open or closed?
        if td.trans_closed(self.trans):
            log.info("Register: cancel closed transaction %d"%self.trans)
            # Select all lines
            for i in range(0,len(self.dl)):
                self.markline(i)
            # Create new 'void' transaction
            self.cancelmarked()
        else:
            # Delete this transaction and everything to do with it
            log.info("Register: cancel open transaction %d"%self.trans)
            tn=self.trans
            (tot,payments)=td.trans_balance(tn)
            td.trans_cancel(tn)
            if payments>0.0:
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
            self.drawline(line)
    def cancelline(self,force=False):
        if td.trans_closed(self.trans):
            if self.ml==sets.Set():
                ui.infopopup(
                    ["Use the Up and Down keys and the Cancel key "
                     "to select lines from this transaction that "
                     "you want to void, and then press Cash/Enter "
                     "to create a new transaction that voids these "
                     "lines.  If you don't want to cancel lines from "
                     "this transaction, press Clear after dismissing "
                     "this message."],
                    title="Help on voiding lines from closed transactions")
            self.markline(self.cursor)
            self.prompt="Press Cash/Enter to void the blue lines"
            self.drawline('buf')
        else:
            l=self.dl[self.cursor]
            if isinstance(l,tline):
                transline=l.transline
                if force:
                    log.info("Register: cancelline: delete "
                             "transline %d"%transline)
                    td.trans_deleteline(transline)
                    del self.dl[self.cursor]
                    self.cursor=None
                    self.update_balance()
                    self.redraw()
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
    def cancelmarked(self):
        tl=list(self.ml)
        self.clear()
        trans=self.gettrans()
        if trans is None: return
        log.info("Register: cancelmarked %s; new trans=%d"%(str(tl),trans))
        for i in tl:
            (transid,items,amount,dept,desc,stockref,
             transcode)=td.trans_getline(i)
            if stockref is not None:
                (qty,removecode,stockitem,manufacturer,name,shortname,abv,
                 unitname)=td.stock_fetchline(stockref)
                lid=td.stock_sell(trans,dept,stockitem,-items,qty/items,
                                  amount,self.name,'V')
            else:
                lid=td.trans_addline(trans,dept,-items,amount,self.name,'V')
            self.addline(tline(lid))
        self.update_balance()
        self.cashkey()
    def recalltrans(self,trans):
        self.clear()
        if trans is not None:
            log.info("Register: recalltrans %d"%trans)
            registry.announce(self.name,trans)
            self.trans=trans
            self.keyguard=True
            (lines,payments)=td.trans_getlines(trans)
            for i in lines:
                self.dl.append(tline(i))
            for i in payments:
                self.dl.append(payline(i))
        self.cursor_off() # will scroll to balance if necessary
        self.update_balance()
        self.redraw()
    def recalltranskey(self):
        sc=td.session_current()
        if sc is None:
            log.info("Register: recalltrans: no session")
            ui.infopopup(["There is no session in progress.  You can "
                          "only recall transactions that belong to the "
                          "current session."],title="Error")
            return
        log.info("Register: recalltrans")
        tl=td.session_translist(sc[0])
        def transsummary(t):
            num,closed,amount=t
            return ("%d"%num,('open','closed')[closed],tillconfig.fc(amount))
        lines=ui.table([transsummary(x) for x in tl]).format(' r l r ')
        sl=[(x,self.recalltrans,(t[0],)) for x,t in zip(lines,tl)]
        ui.menu([('New Transaction',self.recalltrans,(None,))]+sl,
                title="Recall Transaction",
                blurb="Select a transaction and press Cash/Enter.",
                colour=ui.colour_input)
    def defertrans(self,transid):
        if td.trans_closed(transid):
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be deferred."],title="Error")
            return
        self.clear()
        self.redraw()
        td.trans_defer(transid)
        ui.infopopup(["Transaction %d has been deferred to the next "
                      "session.  Make sure you keep a note of the "
                      "transaction number and the name of the person "
                      "responsible for paying it!"%transid],
                     title="Transaction defer confirmed",
                     colour=ui.colour_confirm,dismiss=keyboard.K_CASH)
    def freedrinktrans(self,transid):
        if td.trans_closed(transid):
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be converted to free drinks."%transid],
                         title="Error")
            return
        lines,payments=td.trans_getlines(transid)
        if len(payments)>0:
            ui.infopopup(["Some payments have already been entered against "
                          "transaction %d, so it can't be converted to "
                          "free drinks."%transid],
                         title="Error")
            return
        td.trans_makefree(transid,'freebie')
        self.clear()
        self.redraw()
        ui.infopopup(["Transaction %d has been converted to free drinks."%
                      transid],title="Free Drinks",colour=ui.colour_confirm,
                     dismiss=keyboard.K_CASH)
    def mergetransmenu(self,transid):
        sc=td.session_current()
        log.info("Register: mergetrans")
        tl=td.session_translist(sc[0],onlyopen=True)
        def transsummary(t):
            num,closed,amount=t
            return ("%d"%num,tillconfig.fc(amount))
        lines=ui.table([transsummary(x) for x in tl]).format(' r r ')
        sl=[(x,self.mergetrans,(transid,t[0])) for x,t in zip(lines,tl)
            if t[0]!=transid]
        ui.menu(sl,
                title="Merge with transaction",
                blurb="Select a transaction to merge this one into, "
                "and press Cash/Enter.",
                colour=ui.colour_input)
    def mergetrans(self,transid,othertransid):
        if td.trans_closed(transid):
            ui.infopopup(["Transaction %d has been closed, and cannot now "
                          "be merged with another transaction."%transid],
                         title="Error")
            return
        lines,payments=td.trans_getlines(transid)
        if len(payments)>0:
            ui.infopopup(["Some payments have already been entered against "
                          "transaction %d, so it can't be merged with another "
                          "transaction."%transid],
                         title="Error")
            return
        td.trans_merge(transid,othertransid)
        self.recalltrans(othertransid)
    def managetranskey(self):
        if self.trans is None or td.trans_closed(self.trans):
            ui.infopopup(["You can only modify an open transaction."],
                         title="Error")
            return
        ui.keymenu([(keyboard.K_ONE,"Defer transaction to next session",
                     self.defertrans,(self.trans,)),
                    (keyboard.K_TWO,"Convert transaction to free drinks",
                     self.freedrinktrans,(self.trans,)),
                    (keyboard.K_THREE,"Merge this transaction with another "
                     "open transaction",self.mergetransmenu,(self.trans,))],
                   title="Transaction %d"%self.trans,clear=True)
    def keypress(self,k):
        if isinstance(k,magcard.magstripe):
            return magcard.infopopup(k)
        if k in keyboard.lines:
            return stocklines.linemenu(k,self.linekey)
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
            keyboard.K_UP: self.cursor_up,
            keyboard.K_DOWN: self.cursor_down,
            keyboard.K_PRICECHECK: plu,
            keyboard.K_MANAGETILL: managetill,
            keyboard.K_MANAGESTOCK: managestock,
            keyboard.K_USESTOCK: usestock,
            keyboard.K_WASTE: recordwaste,
            }
        if k in keys: return keys[k]()
        if k in [keyboard.K_4JUG,keyboard.K_DOUBLE,keyboard.K_HALF]:
            return self.modkey(k)
        curses.beep()

registry=transnotify()
