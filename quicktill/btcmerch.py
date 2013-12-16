import json
import httplib
import urllib
import urllib2
import ssl
import socket
import decimal
from . import payment,ui

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
        password_mgr=urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None,base_url,username,password)
        auth=urllib2.HTTPBasicAuthHandler(password_mgr)
        no_proxy=urllib2.ProxyHandler({})
#        https=BTCMerchHTTPSHandler()
#        self._opener=urllib2.build_opener(https,auth,no_proxy)
        self._opener=urllib2.build_opener(auth,no_proxy)
    def _sendrequest(self,url,**parameters):
        if parameters:
            data=urllib.urlencode(parameters,doseq=True)
            request=urllib2.Request(self._base_url+url,data)
        else:
            request=urllib2.Request(self._base_url+url)
        try:
            u=self._opener.open(request)
            response=u.read()
            u.close()
            return response.strip("\r\n\t ")
        except urllib2.HTTPError as e:
            raise HTTPError(e)
        except urllib2.URLError as e:
            raise URLError(e)
        except httplib.InvalidURL as e:
            raise URLError(e)
    def request_payment(self,ref,description,amount):
        response=self._sendrequest("payment.json",
                                   ref=str(ref),description=description,
                                   amount=str(amount))
        try:
            return json.loads(response,parse_float=decimal.Decimal)
        except ValueError:
            raise JSONError
    def transactions_total(self,translist):
        response=self._sendrequest("totals.json",transaction=translist)
        try:
            return json.loads(response,parse_float=decimal.Decimal)
        except ValueError:
            raise JSONError
    def transactions_reconcile(self,ref,translist):
        response=self._sendrequest("totals.json",ref=ref,transaction=translist)
        try:
            return json.loads(response,parse_float=decimal.Decimal)
        except ValueError:
            raise JSONError
    def test_connection(self):
        response=self._sendrequest("totals.json")
        try:
            return json.loads(response,parse_float=decimal.Decimal)
        except ValueError:
            raise JSONError

# XXX temporarily moving this code here as part of the payments
# reorganisation; it will need updating to work when away from register.py
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
                    row=list(zip(m[0],m[1]))
                else:
                    row=list(zip(m[0],[True]*len(m[0])))
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

# XXX moved from managetill.py
def bitcoincheck():
    log.info("Bitcoin service check")
    if tillconfig.btcmerch_api is None:
        return ui.infopopup(
            ["Bitcoin service is not configured for this till."],
            title="Bitcoin info",dismiss=keyboard.K_CASH)
    try:
        rv=tillconfig.btcmerch_api.test_connection()
    except btcmerch.BTCMerchError as e:
        return ui.infopopup([str(e)],title="Bitcoin error")
    return ui.infopopup(
        ["Bitcoin service ok; it reports it owes us %s for the current "
         "session."%rv[u'total']],
        title="Bitcoin info",dismiss=keyboard.K_CASH,
        colour=ui.colour_info)

class BitcoinPayment(payment.PaymentMethod):
    def __init__(self,paytype,description,
                 username,password,site,base_url):
        payment.PaymentMethod.__init__(self,paytype,description)
        self._api=Api(username,password,site,base_url)
