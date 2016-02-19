import json
import http.client
import urllib.request, urllib.error, urllib.parse
import ssl
import socket
from decimal import Decimal
from . import payment,ui,tillconfig,printer,td,keyboard
from .models import zero,penny,Payment,Transaction
try:
    import qrcode
    _qrcode_available = True
except ImportError:
    _qrcode_available = False
import logging
log=logging.getLogger(__name__)

APIVersion="1.0"

class BTCMerchError(Exception):
    "Base class for exceptions in this module."
    def __str__(self):
        return "General BTCMerch error"

class HTTPError(BTCMerchError):
    "Used to wrap exceptions from urllib2"
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "HTTP error from BTCMerch: %s"%self.e

class URLError(BTCMerchError):
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "URL error from BTCMerch: %s"%self.e

class JSONError(BTCMerchError):
    def __str__(self):
        return "Invalid JSON was received from the server"

#class BTCMerchHTTPSConnection(httplib.HTTPSConnection):
#    '''Class that makes HTTPS connection, checking that the
#    certificate is a BTCMerch server certificate that we recognise.
#
#    '''
#    def connect(self):
#        sock=socket.create_connection((self.host,self.port),self.timeout)
#        if self._tunnel_host:
#            self.sock=sock
#            self._tunnel()
#        self.sock=ssl.wrap_socket(sock,cert_reqs=ssl.CERT_REQUIRED,
#                                  ca_certs="/etc/ssl/certs/ca-certificates.crt")

#class BTCMerchHTTPSHandler(urllib2.HTTPSHandler):
#    def https_open(self,req):
#        return self.do_open(BTCMerchHTTPSConnection,req)

class Api(object):
    '''A python interface to the BTCMerch API

    '''
    def __init__(self,
                 username,password,site,base_url):
        self._base_url=base_url+site+"/"
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None,base_url,username,password)
        auth = urllib.request.HTTPBasicAuthHandler(password_mgr)
        no_proxy = urllib.request.ProxyHandler({})
#        https=BTCMerchHTTPSHandler()
#        self._opener=urllib2.build_opener(https,auth,no_proxy)
        self._opener = urllib.request.build_opener(auth,no_proxy)
    def _sendrequest(self,url,**parameters):
        if parameters:
            data = urllib.parse.urlencode(parameters, doseq=True)
            request=urllib.request.Request(self._base_url + url, data)
        else:
            request=urllib.request.Request(self._base_url + url)
        try:
            u=self._opener.open(request)
            response=u.read()
            u.close()
            return response.strip("\r\n\t ")
        except urllib.error.HTTPError as e:
            raise HTTPError(e)
        except urllib.error.URLError as e:
            raise URLError(e)
        except http.client.InvalidURL as e:
            raise URLError(e)
    def request_payment(self,ref,description,amount):
        response=self._sendrequest("payment.json",
                                   ref=str(ref),description=description,
                                   amount=str(amount))
        try:
            return json.loads(response,parse_float=Decimal)
        except ValueError:
            raise JSONError
    def transactions_total(self,translist):
        response=self._sendrequest("totals.json",transaction=translist)
        try:
            return json.loads(response,parse_float=Decimal)
        except ValueError:
            raise JSONError
    def transactions_reconcile(self,ref,translist):
        response=self._sendrequest("totals.json",ref=ref,transaction=translist)
        try:
            return json.loads(response,parse_float=Decimal)
        except ValueError:
            raise JSONError
    def test_connection(self):
        response=self._sendrequest("totals.json")
        try:
            return json.loads(response,parse_float=Decimal)
        except ValueError:
            raise JSONError

class btcpopup(ui.dismisspopup):
    """
    A window used to accept a Bitcoin payment.

    """
    def __init__(self,pm,reg,payment):
        self._pm=pm
        self._reg=reg
        self._paymentid=payment.id
        (mh,mw)=ui.stdwin.getmaxyx()
        self.h=mh
        self.w=mh*2
        self.response={}
        # Title will be drawn in "refresh()"
        ui.dismisspopup.__init__(
            self,self.h,self.w,colour=ui.colour_input,keymap={
                keyboard.K_CASH:(self.refresh,None,False),
                keyboard.K_PRINT:(self.printout,None,False)})
        self.refresh()
    def draw_qrcode(self):
        if not _qrcode_available:
            self.addstr(2, 2, "QR code library not installed. Press Print.")
            return
        q=qrcode.QRCode(border=2)
        q.add_data("bitcoin:{}?amount={}".format(
                self.response['pay_to_address'],
                self.response['to_pay']))
        m=q.get_matrix()
        size=len(m)
        # Will it fit using single block characters?
        if size+2<self.h and ((size*2)+2)<self.w:
            # Yes!  Try to center it
            x=(self.w/2)-size
            y=(self.h-size)/2
            for line in m:
                self.addstr(y,x,''.join(["  " if c else "\u2588\u2588" for c in line]))
                y=y+1
        # Will it fit using half block characters?
        elif (size/2)<self.h and size+2<self.w:
            # Yes.
            x=(self.w-size)/2
            y=(self.h-(size/2))/2
            # We work on two rows at once.
            lt={
                (False,False): "\u2588", # Full block
                (False,True): "\u2580", # Upper half block
                (True,False): "\u2584", # Lower half block
                (True,True): " ", # No block
                }
            while len(m)>0:
                if len(m)>1:
                    row=list(zip(m[0],m[1]))
                else:
                    row=list(zip(m[0],[True]*len(m[0])))
                m=m[2:]
                self.addstr(y,x,''.join([lt[c] for c in row]))
                y=y+1
        else:
            self.addstr(
                2,2,"QR code will not fit on this screen.  Press Print.")
    def printout(self):
        if 'to_pay_url' in self.response:
            with ui.exception_guard("printing the QR code"):
                with printer.driver as d:
                    d.printline("\t"+tillconfig.pubname,emph=1)
                    d.printline("\t{} payment".format(self._pm.description))
                    d.printline("\t"+self.response['description'])
                    d.printline("\t"+tillconfig.fc(self.response['amount']))
                    d.printline("\t{} {} to pay".format(
                            self.response['to_pay'],self._pm._currency))
                    d.printqrcode(str(self.response['to_pay_url']))
                    d.printline()
                    d.printline()
    def refresh(self):
        payment=td.s.query(Payment).get(self._paymentid)
        if not payment:
            self.dismiss()
            ui.infopopup(["The payment record for this transaction has "
                          "disappeared.  The transaction can't be "
                          "completed."],title="Error")
            return
        if payment.amount!=zero:
            self.dismiss()
            ui.infopopup(["The payment has already been completed."],
                         title="Error")
            return
        # A pending Bitcoin payment has the GBP amount as the reference.
        amount=Decimal(payment.ref)
        try:
            result=self._pm._api.request_payment(
                "p{}".format(self._paymentid),
                "Payment {}".format(self._paymentid),amount)
        except HTTPError as e:
            if e.e.code==409:
                return ui.infopopup(
                    ["The {} merchant service has rejected the payment "
                     "request because the amount has changed.".
                     format(self._pm.description)],
                    title="{} error".format(self._pm.description))
            return ui.infopopup([str(e)],title="{} error".format(
                        self._pm.description))
        except BTCMerchError as e:
            return ui.infopopup([str(e)],title="{} error".format(
                        self._pm.description))
        self.response=result
        if 'to_pay_url' in result:
            self.addstr(
                0,1,"{} payment of {} - press {} to recheck".format(
                    self._pm.description,tillconfig.fc(amount),
                    keyboard.K_CASH.keycap))
            self.draw_qrcode()
        self.addstr(self.h-1,3,"Received {} of {} {} so far".format(
                result['paid_so_far'],result['amount_in_btc'],
                self._pm._currency))
        if result['paid']:
            self.dismiss()
            self._pm._finish_payment(self._reg,payment,
                                     result['amount_in_btc'])

class BitcoinPayment(payment.PaymentMethod):
    def __init__(self,paytype,description,
                 username,password,site,base_url,
                 currency="BTC",min_payment=Decimal("1.00")):
        payment.PaymentMethod.__init__(self,paytype,description)
        self._api=Api(username,password,site,base_url)
        self._min_payment=min_payment
        self._currency=currency
    def describe_payment(self,payment):
        if payment.amount==zero:
            # It's a pending payment.  The ref field is the amount in
            # our configured currency (i.e. NOT in Bitcoin).
            return "Pending {} payment of {}{}".format(
            self.description,tillconfig.currency,payment.ref)
        return "{} ({} {})".format(self.description,payment.ref,
                                   self._currency)
    def payment_is_pending(self,pline_instance):
        return pline_instance.amount==zero
    def resume_payment(self,reg,pline_instance):
        if self.payment_is_pending(pline_instance):
            p=td.s.query(Payment).get(pline_instance.payment_id)
            btcpopup(self,reg,p)
    def start_payment(self,reg,trans,amount,outstanding):
        # Search the transaction for an unfinished Bitcoin payment; if
        # there is one, check to see if it's already been paid.
        for p in trans.payments:
            if p.paytype_id==self.paytype:
                if p.amount==zero:
                    btcpopup(self,reg,p)
                    return
        if amount<zero:
            ui.infopopup(
                ["We don't support refunds using {}.".format(
                        self.description)],
                title="Refund not suported")
            return
        if amount>outstanding:
            ui.infopopup(
                ["You can't take an overpayment using {}.".format(
                        self.description)],
                title="Overpayment not accepted")
            return
        if amount<self._min_payment:
            ui.infopopup(
                ["The minimum amount you can take using {} is {}.  "
                 "Small transactions will cost the customer "
                 "proportionally too much in transaction fees.".format(
                        self.description,tillconfig.fc(self._min_payment))],
                title="Payment too small")
            return
        # We're ready to attempt a Bitcoin payment at this point.  Add
        # the Payment to the transaction to get its ID.
        p=Payment(transaction=trans,paytype=self.get_paytype(),
                  ref=str(amount),amount=zero,user=ui.current_user().dbuser)
        td.s.add(p)
        td.s.flush()
        reg.add_payments(trans,[payment.pline(p,method=self)])
        btcpopup(self,reg,p)
    def _finish_payment(self,reg,payment,btcamount):
        amount=Decimal(payment.ref)
        payment.ref=str(btcamount)
        payment.amount=amount
        td.s.flush()
        reg.payments_update()
        ui.infopopup(["{} payment received".format(self.description)],
                     title=self.description,
                     dismiss=keyboard.K_CASH,colour=ui.colour_info)
    def _payment_ref_list(self,session):
        td.s.add(session)
        # Find all the payments in this session
        payments=td.s.query(Payment).join(Transaction).\
            filter(Payment.paytype_id==self.paytype).\
            filter(Payment.amount!=zero).\
            filter(Transaction.session==session).\
            all()
        return ["p{}".format(p.id) for p in payments]
    def total(self,session,fields):
        td.s.add(session)
        btcval=zero
        try:
            btcval=Decimal(self._api.transactions_total(
                self._payment_ref_list(session))["total"]).quantize(penny)
        except BTCMerchError:
            ui.infopopup(
                ["Could not retrieve {} total; please try again "
                 "later.".format(self.description)],
                title="Error")
        return btcval
    def commit_total(self,session,amount):
        td.s.add(session)
        try:
            self._api.transactions_reconcile(
                str(session.id),self._payment_ref_list(session))
        except Exception as e:
            return str(e)
