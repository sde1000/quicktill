from . import payment,ui,td,tillconfig,keyboard,printer
from .models import Payment,zero,penny
from decimal import Decimal

class moneyfield(ui.editfield):
    def __init__(self,y,x,w):
        ui.editfield.__init__(self,y,x,w,validate=ui.validate_float)
    def keypress(self,k):
        if hasattr(k,"notevalue"):
            self.set(str(k.notevalue))
            ui.editfield.keypress(self,keyboard.K_CASH)
        else:
            ui.editfield.keypress(self,k)

class cardpopup(ui.dismisspopup):
    """
    A window that pops up whenever a card payment is accepted.  It
    prompts for the card receipt number (provided by the credit card
    terminal) and whether there is any cashback on this transaction.

    """
    def __init__(self,reg,trans,amount,func,max_cashback,cashback_first):
        self.reg=reg
        self.trans=trans
        self.amount=amount
        self.func=func
        self.max_cashback=max_cashback
        cashback_in_use=max_cashback>zero
        h=18 if cashback_in_use else 10
        ui.dismisspopup.__init__(self,h,44,title="Card payment transaction %d"%
                                 trans.id,colour=ui.colour_input)
        self.addstr(2,2,"Card payment of %s"%tillconfig.fc(amount))
        if cashback_in_use:
            if cashback_first:
                cbstart=4
                rnstart=12
            else:
                cbstart=9
                rnstart=4
        else:
            rnstart=4
        self.addstr(rnstart,2,"Please enter the receipt number from the")
        self.addstr(rnstart+1,2,"credit card receipt.")
        self.addstr(rnstart+3,2," Receipt number:")
        self.rnfield=ui.editfield(rnstart+3,19,16)
        if cashback_in_use:
            self.addstr(cbstart,2,"Is there any cashback?  Enter amount and")
            self.addstr(cbstart+1,2,"press Cash/Enter.  Leave blank and press")
            self.addstr(cbstart+2,2,"Cash/Enter if there is none.")
            self.addstr(cbstart+4,2,"Cashback amount: %s"%tillconfig.currency)
            self.cbfield=moneyfield(cbstart+4,19+len(tillconfig.currency),6)
            self._total_line=cbstart+6
            self.cbfield.sethook=self.update_total_amount
            self.update_total_amount()
            if cashback_first:
                firstfield=self.cbfield
                lastfield=self.rnfield
            else:
                firstfield=self.rnfield
                lastfield=self.cbfield
            ui.map_fieldlist([self.rnfield,self.cbfield])
        else:
            self.cbfield=None
            firstfield=self.rnfield
            lastfield=self.rnfield
        firstfield.keymap[keyboard.K_CLEAR]=(self.dismiss,None)
        lastfield.keymap[keyboard.K_CASH]=(self.enter,None)
        firstfield.focus()
    def update_total_amount(self):
        self.addstr(self._total_line,2,' '*40)
        try:
            cba=Decimal(self.cbfield.f).quantize(penny)
        except:
            cba=zero
        if cba>self.max_cashback:
            self.addstr(self._total_line,2,"Maximum cashback is %s"%(
                    tillconfig.fc(self.max_cashback)),ui.curses.color_pair(
                    ui.colour_error))
        else:
            self.addstr(self._total_line,2,"Total card payment: %s"%(
                    tillconfig.fc(self.amount+cba)))
    def enter(self):
        try:
            cba=Decimal(self.cbfield.f).quantize(penny)
        except:
            cba=zero
        if cba>self.max_cashback:
            self.cbfield.set("")
            return ui.infopopup(["Cashback is limited to a maximum of %s per "
                                 "transaction."%tillconfig.fc(
                        tillconfig.cashback_limit)],title="Error")
        receiptno=self.rnfield.f
        if receiptno=="":
            return ui.infopopup(["You must enter a receipt number."],
                                title="Error")
        self.dismiss()
        self.func(self.reg,self.trans,self.amount,cba,receiptno)

class BadCashbackMethod(Exception):
    """
    Cashback methods must have the change_given=True attribute.

    """
    pass

class CardPayment(payment.PaymentMethod):
    def __init__(self,paytype,description,machines=1,cashback_method=None,
                 max_cashback=zero,cashback_first=True,kickout=False):
        """
        Accept payments using a manual PDQ machine.  This payment
        method records the receipt number ("reference") from the PDQ
        machine as confirmation, and optionally supports cashback.

        Older versions of the till software had the receipt number
        field first in the dialog box.  Experience with users showed
        them filling in the cashback field first and then moving back
        to the reference field, so now the default is to have the
        cashback field at the top.  cashback_first can be set to False
        to restore the old behaviour.

        The kickout parameter sets whether the cash drawer will be
        opened on a card transaction that does not include cashback.

        """
        payment.PaymentMethod.__init__(self,paytype,description)
        self._machines=machines
        self._cashback_method=cashback_method
        if cashback_method and not cashback_method.change_given:
            raise BadCashbackMethod()
        self._max_cashback=max_cashback
        self._cashback_first=cashback_first
        self._kickout=kickout
        self._total_fields=[(u"Terminal {t}".format(t=t+1),
                             ui.validate_float,None)
                            for t in range(self._machines)]
    def describe_payment(self,payment):
        # Card payments use the 'ref' field for the card receipt number
        return u"%s %s"%(self.description,payment.ref)
    def start_payment(self,reg,trans,amount,outstanding):
        if amount>outstanding:
            if self._cashback_method:
                ui.infopopup(
                    ["You can't take an overpayment on cards.  If the card "
                     "being used allows cashback, the card terminal "
                     "will prompt you and you can give up to %s back."%(
                            tillconfig.fc(self._max_cashback))],
                    title="Overpayment not accepted")
            else:
                ui.infopopup(
                    ["You can't take an overpayment on cards."],
                    title="Overpayment not accepted")
            return
        cardpopup(reg,trans,amount,self._finish_payment,
                  self._max_cashback if self._cashback_method else zero,
                  self._cashback_first)
    def _finish_payment(self,reg,trans,amount,cashback,ref):
        td.s.add(trans)
        if trans.closed:
            ui.infopopup(["The transaction was closed before the payment "
                          "could be recorded.  The payment has been "
                          "ignored."],title="Transaction closed")
            return
        total=amount+cashback
        p=Payment(transaction=trans,paytype=self.get_paytype(),
                  ref=ref,amount=total)
        td.s.add(p)
        r=[payment.pline(p,method=self)]
        if cashback>zero:
            r.append(self._cashback_method.add_change(
                    trans,"%s cashback"%self.description,zero-cashback))
        if cashback>zero or self._kickout: printer.kickout()
        td.s.flush()
        reg.add_payments(trans,r)
    @property
    def total_fields(self):
        return self._total_fields
    def total(self,session,fields):
        return sum(Decimal(x) if len(x)>0 else zero for x in fields)
