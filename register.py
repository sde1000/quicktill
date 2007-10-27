"""Cash register page.  Allows transaction entry, voiding of lines.
Also supports function keys to go to various popups: price lookup, management,
etc."""

import sets,curses
import td,ui,keyboard,plu,manage,printer,stock,usestock,recordwaste

import logging
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
            if abv is not None:
                abvs=' (%.1f%% ABV)'%abv
            else: abvs=''
            qty=qty/items
            if qty==1.0:
                qtys=unitname
            elif qty==0.5:
                qtys="half %s"%unitname
            else:
                qtys="%.1f %s"%(qty,unitname)
            ss="%s %s%s %s"%(manufacturer,name,abvs,qtys)
            if len(ss)>w:
                ss="%s %s %s"%(shortname,qtys,unitname)
                if len(ss)>w:
                    ss=ss[:w]
        else:
            ss=deptstr
        win.insstr(y,0,' '*w,attr)
        win.insstr(y,0,ss,attr)
        astr="%d @ £%0.2f = £%0.2f"%(items,amount,items*amount)
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
    (amount,paytype)=p
    if amount==None: amount=0.0
    if paytype[0:4]=='CASH':
        if amount>=0.0:
            return rline('Cash £%0.2f'%amount,ui.colour_cashline)
        return rline('Change £%0.2f'%amount,ui.colour_changeline)
    return rline("%s £%0.2f"%(paytype,amount),ui.colour_cashline)

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
        self.buf=None
        self.qty=None
    def pagename(self):
        if self.trans is not None:
            ts=" - Transaction %d (%s)"%(self.trans,("open","closed")
                                         [td.trans_closed(self.trans)])
        else: ts=""
        return "%s%s"%(self.name,ts)
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
                    bstr="%s £%0.2f"%(("Change","Amount to pay")
                                      [self.balance>=0.0],self.balance)
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
        sn=td.stock_onsale(line[0])
        if sn is None:
            log.info("Register: linekey: no stock in use for %s"%line[0])
            ui.infopopup(["No stock is in use for %s."%line[0],
                          "To tell the till about stock on sale, "
                          "press the 'Use Stock' button after "
                          "dismissing this message."],
                         title="%s has no stock"%line[0])
            return
        def update_prompt():
            sd=td.stock_info(sn)
            self.prompt="%s: %0.1f %ss remaining"%(line[0],sd['remaining'],
                                                   sd['unitname'])
        if self.repeat is not None:
            if self.repeat[0]==line:
                log.info("Register: linekey: sell more of lid=%d"%self.repeat[1])
                td.stock_sellmore(self.repeat[1],1)
                self.drawline(len(self.dl)-1)
                update_prompt()
                self.update_balance()
                return
        self.repeat=None
        if self.qty is not None:
            items=self.qty
        elif self.buf is not None:
            if self.buf.find('.')>=0:
                log.info("Register: linekey: found decimal point in buffer")
                ui.infopopup(["You may only enter a whole number of items "
                              "before pressing a line key."],title="Error")
                self.buf=None
                self.drawline('buf')
                return
            items=int(self.buf)
        else:
            items=1
        if items<1: items=1
        self.buf=None
        self.qty=None
        trans=self.gettrans()
        if trans is None: return
        lid=td.stock_sell(self.trans,sn,items,line[1],self.name,'S')
        log.info("Register: linekey: trans=%d,lid=%d,sn=%d,items=%d,qty=%f"%
                 (self.trans,lid,sn,items,line[1]))
        self.repeat=(line,lid)
        self.addline(tline(lid))
        update_prompt()
        self.update_balance()
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
        log.info("Register: deptkey: trans=%d,lid=%d,dept=%d,items=%d,price=%f"%
                 (trans,lid,dept,items,price))
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
    def cashkey(self):
        if self.ml!=sets.Set():
            self.cancelmarked()
            return
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
            ui.infopopup(["You can't pay £0.00 in cash!",
                          'If you meant "exact change" then please '
                          'press Clear after dismissing this message, '
                          'and try again.'],title="Error")
            return
        self.buf=None
        # We have a non-zero amount and a transaction. Pay it!
        remain=td.trans_addpayment(self.trans,'CASH',amount)
        self.addline(rline('Cash £%0.2f'%amount,ui.colour_cashline))
        if remain<0.0:
            # There's some change!
            log.info("Register: cashkey: calculated change")
            td.trans_addpayment(self.trans,'CASH',remain)
            self.addline(rline('Change £%0.2f'%remain,ui.colour_changeline))
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
    def numkey(self,n):
        if (self.buf==None and self.qty==None and self.trans is not None and
            td.trans_closed(self.trans)):
            log.info("Register: numkey on closed transaction; clearing display")
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
    def clearkey(self):
        if (self.buf==None and self.qty==None and self.trans is not None and
            td.trans_closed(self.trans)):
            log.info("Register: clearkey on closed transaction; clearing display")
            self.clear()
            self.redraw()
        else:
            log.info("Register: clearkey on open transaction; clearing buffer")
            self.cursor_off()
            self.qty=None
            self.buf=None
            self.drawline('buf')
    def printkey(self):
        if self.trans is None:
            log.info("Register: printkey without transaction")
            ui.infopopup(["There is no transaction currently selected to "
                          "print.  You can recall old transactions using "
                          "the 'Recall Trans' key."],title="Error")
            return
        if not td.trans_closed(self.trans):
            log.info("Register: printkey on open transaction")
            ui.infopopup(["The current transaction is still open.  "
                          "You can't print a receipt for it until it "
                          "is paid in full."],
                         title="Error")
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
                log.info("Register: cancelkey confirm kill transaction %d"%self.trans)
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
                refundtext="£%0.2f had already been put in the cash drawer."%payments
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
                ui.infopopup(["Use the Up and Down keys and the Cancel key "
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
                    log.info("Register: cancelline: delete transline %d"%transline)
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
            (transid,items,amount,dept,desc,stockref,transcode)=td.trans_getline(i)
            if stockref is not None:
                (qty,removecode,stockitem,manufacturer,name,shortname,abv,
                 unitname)=td.stock_fetchline(stockref)
                lid=td.stock_sell(trans,stockitem,-items,qty/items,self.name,'V')
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
        tl=td.trans_sessionlist(sc[0])
        def transsummary(t):
            closed=td.trans_closed(t)
            (lines,payments)=td.trans_balance(t)
            lt="£%0.2f"%lines
            return "%6d %s%s%s"%(t,('open  ','closed')[closed],
                                  ' '*(11-len(lt)),lt)
        sl=[(transsummary(t),self.recalltrans,(t,)) for t in tl]
        ui.menu([('New Transaction',self.recalltrans,(None,))]+sl,
                title="Recall Transaction",
                blurb="Select a transaction and press Cash/Enter.",
                colour=ui.colour_input)
    def keypress(self,k):
        if k in keyboard.lines:
            return ui.linemenu(keyboard.lines[k],self.linekey)
        if k in keyboard.depts:
            return self.deptkey(keyboard.depts[k])
        self.repeat=None
        if k in keyboard.notes:
            return self.notekey(keyboard.notes[k])
        if k in keyboard.numberkeys or k==keyboard.K_ZEROZERO:
            return self.numkey(ui.codes[k][1])
        keys={
            keyboard.K_CASH: self.cashkey,
            keyboard.K_QUANTITY: self.quantkey,
            keyboard.K_CLEAR: self.clearkey,
            keyboard.K_CANCEL: self.cancelkey,
            keyboard.K_PRINT: self.printkey,
            keyboard.K_RECALLTRANS: self.recalltranskey,
            keyboard.K_UP: self.cursor_up,
            keyboard.K_DOWN: self.cursor_down,
            keyboard.K_PRICECHECK: plu.popup,
            keyboard.K_MANAGETILL: manage.popup,
            keyboard.K_MANAGESTOCK: stock.popup,
            keyboard.K_USESTOCK: usestock.popup,
            keyboard.K_WASTE: recordwaste.popup,
            }
        if k in keys: return keys[k]()
        if k in ui.codes:
            ui.infopopup(["%s is not a valid key at this time."%
                          ui.codes[k][1]],title="Error")
        else:
            curses.beep()

registry=transnotify()
