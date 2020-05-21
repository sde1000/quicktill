# This code is obsolete, and is just being kept around for reference.

import requests
from decimal import Decimal
from . import payment, ui, tillconfig, printer, td, keyboard
from .models import zero, penny, Payment, Transaction
try:
    import qrcode
    _qrcode_available = True
except ImportError:
    _qrcode_available = False
import logging
log = logging.getLogger(__name__)

APIVersion = "1.0"

class Api:
    """A python interface to the BTCMerch API
    """
    def __init__(self, username, password, site, base_url):
        self._base_url = base_url + site + "/"
        self._auth = (username, password)

    def request_payment(self, ref, description, amount):
        response = requests.post(
            self._base_url + "payment.json",
            data={'ref': str(ref), 'description': description,
                  'amount': str(amount)}, auth=self._auth)
        response.raise_for_status()

        return response.json(parse_float=Decimal)

    def transactions_total(self, translist):
        response = requests.post(
            self._base_url + "totals.json",
            data={'transaction': translist},
            auth=self._auth)
        response.raise_for_status()

        return response.json(parse_float=Decimal)

    def transactions_reconcile(self, ref, translist):
        response = requests.post(
            self._base_url + "totals.json",
            data={'ref': ref, 'transaction': translist},
            auth=self._auth)
        response.raise_for_status()

        return response.json(parse_float=Decimal)

class btcpopup(ui.dismisspopup):
    """A window used to accept a Bitcoin payment.
    """
    def __init__(self, pm, reg, payment):
        self._pm = pm
        self._reg = reg
        self._paymentid = payment.id
        mh, mw = ui.rootwin.size()
        self.h = mh
        self.w = mh * 2
        self.response = {}
        # Title will be drawn in "refresh()"
        super().__init__(
            self.h, self.w, colour=ui.colour_input, keymap={
                keyboard.K_CASH: (self.refresh, None, False),
                keyboard.K_PRINT: (self.printout, None, False)})
        self.refresh()

    @staticmethod
    def qrcode_data(response):
        """Construct a bitcoin URL using pay_to_address and to_pay from a
        btcmerch server response.
        """
        return "bitcoin:{}?amount={}".format(
            response['pay_to_address'], response['to_pay'])

    def draw_qrcode(self):
        if not _qrcode_available:
            self.win.drawstr(2, 2, self.w - 4,
                             "QR code library not installed. Press Print.")
            return
        q = qrcode.QRCode(border=2)
        q.add_data(self.qrcode_data(self.response))
        m = q.get_matrix()
        size = len(m)
        # Will it fit using single block characters?
        if size + 2 < self.h and ((size * 2) + 2) < self.w:
            # Yes!  Try to center it
            x = (self.w // 2) - size
            y = (self.h - size) // 2
            for line in m:
                self.win.addstr(
                    y, x, ''.join(
                        ["  " if c else "\u2588\u2588" for c in line]))
                y = y + 1
        # Will it fit using half block characters?
        elif (size // 2) < self.h and size + 2 < self.w:
            # Yes.
            x = (self.w - size) // 2
            y = (self.h - (size // 2)) // 2
            # We work on two rows at once.
            lt = {
                (False, False): "\u2588", # Full block
                (False, True): "\u2580", # Upper half block
                (True, False): "\u2584", # Lower half block
                (True, True): " ", # No block
                }
            while len(m) > 0:
                if len(m) > 1:
                    row = zip(m[0], m[1])
                else:
                    row = zip(m[0], [True] * len(m[0]))
                m = m[2:]
                self.win.addstr(y, x, ''.join([lt[c] for c in row]))
                y = y + 1
        else:
            self.win.drawstr(
                2, 2, self.w - 4,
                "QR code will not fit on this screen.  Press Print.")

    def printout(self):
        if 'to_pay_url' in self.response:
            with ui.exception_guard("printing the QR code"):
                data = self.qrcode_data(self.response)
                with printer.driver as d:
                    d.printline("\t" + tillconfig.pubname, emph=1)
                    d.printline("\t{} payment".format(self._pm.description))
                    d.printline("\t" + self.response['description'])
                    d.printline("\t" + tillconfig.fc(self.response['amount']))
                    d.printline("\t{} {} to pay".format(
                            self.response['to_pay'], self._pm._currency))
                    d.printqrcode(data.encode('utf-8'))
                    d.printline()
                    d.printline("\t" + self.response['pay_to_address'])
                    d.printline()
                    d.printline()

    def refresh(self):
        payment = td.s.query(Payment).get(self._paymentid)
        if not payment:
            self.dismiss()
            ui.infopopup(["The payment record for this transaction has "
                          "disappeared.  The transaction can't be "
                          "completed."], title="Error")
            return
        if payment.amount != zero:
            self.dismiss()
            ui.infopopup(["The payment has already been completed."],
                         title="Error")
            return
        # A pending Bitcoin payment has the GBP amount as the reference.
        amount = Decimal(payment.ref)
        try:
            result = self._pm._api.request_payment(
                "p{}".format(self._paymentid),
                "Payment {}".format(self._paymentid), amount)
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 409:
                return ui.infopopup(
                    ["The {} merchant service has rejected the payment "
                     "request because the amount has changed.".
                     format(self._pm.description)],
                    title="{} error".format(self._pm.description))
            return ui.infopopup([str(e)], title="{} http error".format(
                self._pm.description))
        except Exception as e:
            return ui.infopopup([str(e)], title="{} error".format(
                self._pm.description))
        self.response = result
        if 'to_pay_url' in result:
            self.win.addstr(
                0, 1, "{} payment of {} - press {} to recheck".format(
                    self._pm.description, tillconfig.fc(amount),
                    keyboard.K_CASH.keycap))
            self.draw_qrcode()
        self.win.addstr(self.h - 1, 3, "Received {} of {} {} so far".format(
            result['paid_so_far'], result['amount_in_btc'],
            self._pm._currency))
        if result['paid']:
            self.dismiss()
            self._pm._finish_payment(self._reg, payment,
                                     result['amount_in_btc'])

class BitcoinPayment(payment.PaymentMethod):
    def __init__(self, paytype, description,
                 username, password, site, base_url,
                 currency="BTC", min_payment=Decimal("1.00"),
                 account_code = None):
        payment.PaymentMethod.__init__(self, paytype, description)
        self._api = Api(username, password, site, base_url)
        self._min_payment = min_payment
        self._currency = currency
        self.account_code = account_code

    def describe_payment(self, payment):
        if payment.amount == zero:
            # It's a pending payment.  The ref field is the amount in
            # our configured currency (i.e. NOT in Bitcoin).
            return "Pending {} payment of {}{}".format(
            self.description, tillconfig.currency, payment.ref)
        return "{} ({} {})".format(self.description, payment.ref,
                                   self._currency)

    def payment_is_pending(self, pline_instance):
        return pline_instance.amount == zero

    def resume_payment(self, reg, pline_instance):
        if self.payment_is_pending(pline_instance):
            p = td.s.query(Payment).get(pline_instance.payment_id)
            btcpopup(self, reg, p)

    def start_payment(self, reg, transid, amount, outstanding):
        trans = td.s.query(Transaction).get(transid)
        # Search the transaction for an unfinished Bitcoin payment; if
        # there is one, check to see if it's already been paid.
        for p in trans.payments:
            if p.paytype_id == self.paytype:
                if p.amount == zero:
                    btcpopup(self, reg, p)
                    return
        if amount < zero:
            ui.infopopup(
                ["We don't support refunds using {}.".format(
                    self.description)],
                title="Refund not suported")
            return
        if amount > outstanding:
            ui.infopopup(
                ["You can't take an overpayment using {}.".format(
                    self.description)],
                title="Overpayment not accepted")
            return
        if amount < self._min_payment:
            ui.infopopup(
                ["The minimum amount you can take using {} is {}.  "
                 "Small transactions will cost "
                 "proportionally too much in transaction fees.".format(
                     self.description, tillconfig.fc(self._min_payment))],
                title="Payment too small")
            return
        # We're ready to attempt a Bitcoin payment at this point.  Add
        # the Payment to the transaction to get its ID.
        p = Payment(transaction=trans, paytype=self.get_paytype(),
                    ref=str(amount), amount=zero, user=ui.current_user().dbuser)
        td.s.add(p)
        td.s.flush()
        reg.add_payments(transid, [payment.pline(p, method=self)])
        btcpopup(self, reg, p)

    def _finish_payment(self, reg, payment, btcamount):
        amount = Decimal(payment.ref)
        payment.ref = str(btcamount)
        payment.amount = amount
        td.s.flush()
        reg.payments_update()
        ui.infopopup(["{} payment received".format(self.description)],
                     title=self.description,
                     dismiss=keyboard.K_CASH, colour=ui.colour_info)

    def _payment_ref_list(self, session):
        td.s.add(session)
        # Find all the payments in this session
        payments = td.s.query(Payment).join(Transaction).\
            filter(Payment.paytype_id == self.paytype).\
            filter(Payment.amount != zero).\
            filter(Transaction.session == session).\
            all()
        return ["p{}".format(p.id) for p in payments]

    def total(self, session, fields):
        td.s.add(session)
        btcval = zero
        try:
            btcval = Decimal(self._api.transactions_total(
                self._payment_ref_list(session))["total"]).quantize(penny)
        except Exception as e:
            return str(e)
        return btcval

    def commit_total(self, session, amount):
        td.s.add(session)
        payment_ref_list = self._payment_ref_list(session)
        try:
            btcval = Decimal(self._api.transactions_total(
                payment_ref_list)["total"]).quantize(penny)
            if btcval != amount:
                return "Server says amount is {}, but we are trying to " \
                    "record {} as the total".format(btcval, amount)
            self._api.transactions_reconcile(
                str(session.id), payment_ref_list)
        except Exception as e:
            return str(e)

    def accounting_info(self, sessiontotal):
        return self.account_code, sessiontotal.session.date, \
            "{} takings".format(self.description)
