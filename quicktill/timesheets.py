import json
import httplib
import urllib
import urllib2
import ssl
import socket
import ui,keyboard

APIVersion="1.0"
pinlength=8

class TimesheetError(Exception):
    "Base class for exceptions in this module."
    def __str__(self):
        return "General Timesheet error"

class HTTPError(TimesheetError):
    "Used to wrap exceptions from urllib2"
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "HTTP error from Timesheet: %s"%self.e

class URLError(TimesheetError):
    def __init__(self,e):
        self.e=e
    def __str__(self):
        return "URL error from Timesheet: %s"%self.e

class JSONError(TimesheetError):
    def __str__(self):
        return "Invalid JSON was received from the server"

class TimesheetHTTPSConnection(httplib.HTTPSConnection):
    '''Class that makes HTTPS connection, checking that the
    certificate is a Timesheet server certificate that we recognise.

    '''
    def connect(self):
        sock=socket.create_connection((self.host,self.port),self.timeout)
        if self._tunnel_host:
            self.sock=sock
            self._tunnel()
        self.sock=ssl.wrap_socket(sock,cert_reqs=ssl.CERT_REQUIRED,
                                  ca_certs="/etc/ssl/certs/ca-certificates.crt")

class TimesheetHTTPSHandler(urllib2.HTTPSHandler):
    def https_open(self,req):
        return self.do_open(TimesheetHTTPSConnection,req)

class Api(object):
    '''A python interface to the Timesheet API

    '''
    def __init__(self,
                 username,password,site=None,base_url=None):
        if site is None: site="https://admin.individualpubs.co.uk"
        if base_url is None:
            base_url="/schedule/%s/api/users/"%username
        self._site=site
        self._base_url=base_url
        password_mgr=urllib2.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None,site+'/',username,password)
        auth=urllib2.HTTPBasicAuthHandler(password_mgr)
        no_proxy=urllib2.ProxyHandler({})
        https=TimesheetHTTPSHandler()
        self._opener=urllib2.build_opener(https,auth,no_proxy)
    def _sendrequest(self,url,**parameters):
        if parameters:
            data=urllib.urlencode(parameters)
            request=urllib2.Request(self._site+url,data)
        else:
            request=urllib2.Request(self._site+url)
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
    def get_users(self):
        response=self._sendrequest(self._base_url)
        try:
            return [User(self,x) for x in json.loads(response)]
        except ValueError:
            raise JSONError
    def action_with_pin(self,url,pin):
        response=self._sendrequest(url,pin=pin)
        try:
            return json.loads(response)
        except ValueError:
            raise JSONError

class User(object):
    def __init__(self,api,d):
        self._api=api
        self.username=d['username']
        self.url=d['url']
        self.fullname=d['fullname']
        self.pin=None
        self.actions_url=None
    def check_pin(self,pin):
        ok=self._api.action_with_pin(self.url,pin)
        if ok:
            self.pin=pin
        return ok
    def action(self,action):
        return self._api.action_with_pin(action,self.pin)

class ActionPopup(ui.menu):
    def __init__(self,user,url):
        self.user=user
        try:
            acts=user.action(url)
        except TimesheetError as e:
            ui.infopopup([str(e)],title="Timesheet error")
            return
        try:
            title=acts.get('title','Action')
            message=acts.get('message',None)
            actions=acts.get('actions',[])
            l=[(a['action'],self.do_action,(a['url'],))
               for a in actions]
        except:
            ui.popup_exception("Invalid response from server")
            return
        if len(l)>0:
            ui.menu.__init__(self,l,title=title,blurb=message)
        else:
            ui.infopopup([message],title=title,colour=ui.colour_info,
                         dismiss=keyboard.K_CASH)
    def do_action(self,url):
        ActionPopup(self.user,url)

class enterpin(ui.dismisspopup):
    def __init__(self,user):
        self.user=user
        ui.dismisspopup.__init__(self,5,20+pinlength,title=user.fullname,
                                 colour=ui.colour_input)
        self.addstr(2,2,"Enter your PIN:")
        self.pinfield=ui.editfield(2,18,pinlength,keymap={
                keyboard.K_CASH:(self.enter,None,False)})
        self.pinfield.focus()
    def enter(self):
        try:
            ok=self.user.check_pin(self.pinfield.f)
        except TimesheetError as e:
            ui.infopopup([str(e)],title="Timesheet error")
            return
        if ok:
            self.dismiss()
            ActionPopup(self.user,ok)
        else:
            self.pinfield.set('')
            ui.infopopup(["Incorrect PIN."],title="Error")

class popup(ui.menu):
    def __init__(self,api):
        try:
            users=api.get_users()
        except TimesheetError as e:
            ui.infopopup([str(e)],title="Timesheet error")
            return
        l=[(u.fullname,enterpin,(u,)) for u in users]
        ui.menu.__init__(self,l,title="Who are you?",blurb=None)
