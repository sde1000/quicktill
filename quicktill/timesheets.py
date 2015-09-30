from __future__ import unicode_literals
import requests
from . import ui,keyboard

pinlength = 8

class Api(object):
    """A python interface to the Timesheet API"""
    def __init__(self, username, password, site, base_url, timeout = 4):
        self._site = site
        self._base_url = base_url
        self._auth = (username, password)
        self._timeout = timeout
    def get_users(self):
        r = requests.get(self._site + self._base_url, auth=self._auth,
                         timeout=self._timeout, verify=True)
        return [User(self,x) for x in r.json()]
    def action_with_pin(self, url, pin):
        r = requests.post(self._site + url, data={'pin':pin},
                          auth=self._auth, timeout=self._timeout, verify=True)
        return r.json()

class User(object):
    def __init__(self, api, d):
        self._api = api
        self.username = d['username']
        self.url = d['url']
        self.fullname = d['fullname']
        self.pin = None
        self.actions_url = None
    def check_pin(self, pin):
        ok = self._api.action_with_pin(self.url,pin)
        if ok:
            self.pin = pin
        return ok
    def action(self, action):
        return self._api.action_with_pin(action, self.pin)

class ActionPopup(ui.menu):
    def __init__(self, user, url):
        acts = None
        with ui.exception_guard("performing the requested action"):
            acts = user.action(url)
        if acts is None: return
        try:
            title = acts.get('title', 'Action')
            message = acts.get('message', None)
            actions = acts.get('actions', [])
            l = [(a['action'], ActionPopup, (user, a['url']))
                 for a in actions]
        except:
            ui.popup_exception("Invalid response from server")
            return
        if len(l) > 0:
            l=[("Don't do anything - just reload the list of available actions",
                ActionPopup, (user, url))] + l
            ui.menu.__init__(self, l, title=title,
                             blurb=[message] if message else [])
        else:
            ui.infopopup([message], title=title, colour=ui.colour_info,
                         dismiss=keyboard.K_CASH)

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
        ok = None
        with ui.exception_guard("checking the PIN"):
            ok = self.user.check_pin(self.pinfield.f)
        if ok is None:
            self.pinfield.set('')
            return
        if ok:
            self.dismiss()
            ActionPopup(self.user, ok)
        else:
            self.pinfield.set('')
            ui.infopopup(["Incorrect PIN."], title="Error")

class popup(ui.menu):
    def __init__(self,api):
        users = None
        with ui.exception_guard("fetching the staff list"):
            users = api.get_users()
        if users:
            l = [(u.fullname,enterpin,(u,)) for u in users]
            ui.menu.__init__(self,l,title="Who are you?",blurb=[])
