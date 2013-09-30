import json
import httplib
import urllib
import urllib2
import ssl
import socket
import decimal

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
