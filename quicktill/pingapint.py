#!/bin/env python
# -*- coding: utf-8 -*-

import json
import httplib
import urllib
import urllib2
import re
import ssl
import socket

APIVersion="1.2"
codelengthmin=6
codelengthmax=6

class PingaPintError(Exception):
    "Base class for exceptions in this module."
    def __str__(self):
        return "General PingaPint error"

class InvalidVID(PingaPintError):
    "Validation succeeded, but validation ID field was missing or invalid."
    def __str__(self):
        return "Bad validation ID; this is an internal PingaPint error"

class HTTPError(PingaPintError):
    "Used to wrap exceptions from urllib2"
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "HTTP error from PingaPint: %s"%self.e

class URLError(PingaPintError):
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "URL error from PingaPint: %s"%self.e

class InvalidCode(PingaPintError):
    def __str__(self):
        return "Code has wrong length or invalid characters"

class CodeNotValid(PingaPintError):
    def __str__(self):
        return "Not a valid PingaPint code"

class CodeHasExpired(PingaPintError):
    def __str__(self):
        return "Code has expired"

class CodeAlreadyRedeemed(PingaPintError):
    def __str__(self):
        return "Code already redeemed"

class OtherError(PingaPintError):
    def __init__(self,code):
        self.msg=code
    def __str__(self):
        return self.msg

class UnknownResult(PingaPintError):
    def __str__(self):
        return "Unknown result code from PingaPint server"

class PPintHTTPSConnection(httplib.HTTPSConnection):
    '''Class that makes HTTPS connection, checking that the
    certificate is a PingaPint server certificate that we recognise.

    '''
    def connect(self):
        sock=socket.create_connection((self.host,self.port),self.timeout)
        if self._tunnel_host:
            self.sock=sock
            self._tunnel()
        self.sock=ssl.wrap_socket(sock,cert_reqs=ssl.CERT_REQUIRED,
                                  ca_certs="/etc/ssl/certs/ca-certificates.crt")

class PPintHTTPSHandler(urllib2.HTTPSHandler):
    def https_open(self,req):
        return self.do_open(PPintHTTPSConnection,req)

class Api(object):
    '''A python interface to the PingaPint API

    '''
    def __init__(self,
                 username,password,DeviceSN,test=True,base_url=None):
        self._DeviceSN=DeviceSN
        self._test=test
        if base_url is None: base_url="https://www.pingapint.com/api/"
        self._base_url=base_url
        password_mgr=urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None,base_url,username,password)
        auth=urllib2.HTTPBasicAuthHandler(password_mgr)
        no_proxy=urllib2.ProxyHandler({})
        https=PPintHTTPSHandler()
        self._opener=urllib2.build_opener(https,auth,no_proxy)

    def _sendrequest(self,url,parameters):
        params=urllib.urlencode(parameters)
        request=urllib2.Request(url,params)
        u=self._opener.open(request)
        response=u.read()
        u.close()
        return response.strip("\r\n\t ")

    def validate(self,code):
        """Validate a PingaPint code; the code is passed as an argument.

        On success, returns a tuple of:
        amount validated (float)
        validation ID (int)
        raw JSON returned by the server, for storage (string)

        """
        if len(code)<codelengthmin or len(code)>codelengthmax:
            raise InvalidCode
        if re.match(r"^[0123456789]+$",code) is None:
            raise InvalidCode
        parameters={
            'Code':code,
            'DeviceSN':self._DeviceSN,
            'Test':"1" if self._test else "0",
            'APIVersion':APIVersion}
        try:
            response=self._sendrequest(self._base_url+"validate.php",parameters)
        except urllib2.HTTPError as e:
            raise HTTPError(e)
        except urllib2.URLError as e:
            raise URLError(e)
        d=json.loads(response)
        result=d.get("Result",None)
        if result=="ValidRedemption":
            amount=d.get("ValueRedeemed",0.0)
            vid=d.get("ValidationID",None)
            if vid is None:
                raise InvalidVID
            vid=int(vid)
            return (float(amount),vid,response)
        elif result=="CodeNotValid":
            raise CodeNotValid
        elif result=="CodeHasExpired":
            raise CodeHasExpired
        elif result=="CodeAlreadyRedeemed":
            raise CodeAlreadyRedeemed
        elif result[0:5]=="Error":
            raise OtherError(result)
        raise UnknownResult
