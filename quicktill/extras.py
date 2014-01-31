from __future__ import print_function,unicode_literals
from . import ui,keyboard,printer,tillconfig,event,td,user
from . import twitter
from .models import VatBand
import traceback,sys,os,time,datetime

### Bar Billiards checker

class bbcheck(ui.dismisspopup):
    """Given the amount of money taken by a machine and the share of it
    retained by the supplier, print out the appropriate figures for
    the collection receipt.

    """
    def __init__(self,share=25.0):
        ui.dismisspopup.__init__(self,7,20,title="Bar Billiards check",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        # We assume that VAT band 'A' is the current main VAT rate.
        self.vatrate=float(td.s.query(VatBand).get('A').at(datetime.datetime.now()).rate)
        self.vatrate=self.vatrate/100.0
        self.addstr(2,2,"   Total gross:")
        self.addstr(3,2,"Supplier share:")
        self.addstr(4,2,"      VAT rate: %0.1f%%"%(self.vatrate*100.0))
        self.grossfield=ui.editfield(
            2,18,5,validate=ui.validate_float,keymap={
                keyboard.K_CLEAR: (self.dismiss,None)})
        self.sharefield=ui.editfield(
            3,18,5,validate=ui.validate_float,keymap={
                keyboard.K_CASH: (self.enter,None,False)})
        self.sharefield.set(str(share))
        ui.map_fieldlist([self.grossfield,self.sharefield])
        self.grossfield.focus()
    def enter(self):
        pdriver=printer.driver
        try:
            grossamount=float(self.grossfield.f)
        except:
            grossamount=None
        try:
            sharepct=float(self.sharefield.f)
        except:
            sharepct=None
        if grossamount is None or sharepct is None:
            return ui.infopopup(["You must fill in both fields."],
                                title="You Muppet")
        if sharepct>=100.0 or sharepct<0.0:
            return ui.infopopup(["The supplier share is a percentage, "
                                 "and must be between 0 and 100."],
                                title="You Muppet")
        balancea=grossamount/(self.vatrate+1.0)
        vat_on_nett_take=grossamount-balancea
        supplier_share=balancea*sharepct/100.0
        brewery_share=balancea-supplier_share
        vat_on_rent=supplier_share*self.vatrate
        left_on_site=brewery_share+vat_on_nett_take-vat_on_rent
        banked=supplier_share+vat_on_rent
        pdriver.start()
        pdriver.setdefattr(font=1)
        pdriver.printline("Nett take:\t\t%s"%tillconfig.fc(grossamount))
        pdriver.printline("VAT on nett take:\t\t%s"%tillconfig.fc(vat_on_nett_take))
        pdriver.printline("Balance A/B:\t\t%s"%tillconfig.fc(balancea))
        pdriver.printline("Supplier share:\t\t%s"%tillconfig.fc(supplier_share))
        pdriver.printline("Licensee share:\t\t%s"%tillconfig.fc(brewery_share))
        pdriver.printline("VAT on rent:\t\t%s"%tillconfig.fc(vat_on_rent))
        pdriver.printline("(VAT on rent is added to")
        pdriver.printline("'banked' column and subtracted")
        pdriver.printline("from 'left on site' column.)")
        pdriver.printline("Left on site:\t\t%s"%tillconfig.fc(left_on_site))
        pdriver.printline("Banked:\t\t%s"%tillconfig.fc(banked))
        pdriver.end()
        self.dismiss()

### Coffee pot timer

class coffeealarm(object):
    def __init__(self,timestampfilename,dismisskey):
        self.tsf=timestampfilename
        self.dismisskey=dismisskey
        self.update()
        event.eventlist.append(self)
    def update(self):
        try:
            sd=os.stat(self.tsf)
            self.nexttime=float(sd.st_mtime)
        except:
            self.nexttime=None
    def setalarm(self,timeout):
        "timeout is in seconds"
        now=time.time()
        self.nexttime=now+timeout
        f=file(self.tsf,'w')
        f.close()
        os.utime(self.tsf,(now,self.nexttime))
    def clearalarm(self):
        self.nexttime=None
        os.remove(self.tsf)
    def alarm(self):
        if self.nexttime==None: return
        self.clearalarm()
        ui.alarmpopup(title="Coffee pot alarm",
                      text=["Please empty out and clean the coffee pot - the "
                      "coffee in it is now too old."],
                      colour=ui.colour_info,dismiss=self.dismisskey)

class managecoffeealarm(ui.dismisspopup):
    def __init__(self,alarminstance):
        self.ai=alarminstance
        remaining=None if self.ai.nexttime is None else self.ai.nexttime-time.time()
        ui.dismisspopup.__init__(self,8,40,title="Coffee pot alarm",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        if remaining is None:
            self.addstr(2,2,"No alarm is currently set.")
        else:
            self.addstr(2,2,"Remaining time: %d minutes %d seconds"%(
                    remaining/60,remaining%60))
        self.addstr(3,2,"      New time:")
        self.addstr(3,22,"minutes")
        if remaining is not None:
            self.addstr(5,2,"Press Cancel to clear the alarm.")
        self.timefield=ui.editfield(
            3,18,3,validate=ui.validate_int,keymap={
                keyboard.K_CASH: (self.enter,None,False),
                keyboard.K_CANCEL: (self.clearalarm,None,False)})
        self.timefield.set("60") # Default time
        self.timefield.focus()
    def enter(self):
        try:
            timeout=int(self.timefield.f)*60
        except:
            return
        self.ai.setalarm(timeout)
        self.dismiss()
    def clearalarm(self):
        self.ai.clearalarm()
        self.dismiss()

### Reminders at particular times of day
class reminderpopup(object):
    def __init__(self,alarmtime,title,text,colour=ui.colour_info,
                 dismiss=keyboard.K_CANCEL):
        """

        Alarmtime is a tuple of (hour,minute).  It will be interpreted
        as being in local time; each time the alarm goes off it will
        be reinterpreted.

        """
        self.alarmtime=alarmtime
        self.title=title
        self.text=text
        self.colour=colour
        self.dismisskey=dismiss
        self.setalarm()
        event.eventlist.append(self)
    def setalarm(self):
        # If the alarm time has already passed today, we set the alarm for
        # the same time tomorrow
        atime=datetime.time(*self.alarmtime)
        candidate=datetime.datetime.combine(datetime.date.today(),atime)
        if time.mktime(candidate.timetuple())<=time.time():
            candidate=candidate+datetime.timedelta(1,0,0)
        self.nexttime=time.mktime(candidate.timetuple())
    def alarm(self):
        ui.alarmpopup(title=self.title,text=self.text,
                      colour=self.colour,dismiss=self.dismisskey)
        self.setalarm()

def twitter_auth(consumer_key,consumer_secret):
    """
    Generate oauth_token and oauth_token_secret for twitter login.
    Call this function from an interactive shell.

    """
    # This code is from the example at
    # https://github.com/simplegeo/python-oauth2
    import urlparse
    from . import oauth2 as oauth

    request_token_url = 'http://api.twitter.com/oauth/request_token'
    access_token_url = 'http://api.twitter.com/oauth/access_token'
    authorize_url = 'http://api.twitter.com/oauth/authorize'

    consumer = oauth.Consumer(consumer_key, consumer_secret)
    client = oauth.Client(consumer)

    # Step 1: Get a request token. This is a temporary token that is
    # used for having the user authorize an access token and to sign
    # the request to obtain said access token.

    resp, content = client.request(request_token_url, "POST")
    if resp['status'] != '200':
        raise Exception("Invalid response %s: %s." % (resp['status'],content))

    request_token = dict(urlparse.parse_qsl(content))

    print("Request Token:")
    print("    - oauth_token        = %s" % request_token['oauth_token'])
    print("    - oauth_token_secret = %s" % request_token['oauth_token_secret'])
    print() 

    # Step 2: Redirect to the provider. Since this is a CLI script we
    # do not redirect. In a web application you would redirect the
    # user to the URL below.

    print("Go to the following link in your browser:")
    print("%s?oauth_token=%s" % (authorize_url, request_token['oauth_token']))
    print() 

    # After the user has granted access to you, the consumer, the provider will
    # redirect you to whatever URL you have told them to redirect to. You can 
    # usually define this in the oauth_callback argument as well.
    oauth_verifier = raw_input('What is the PIN? ')

    # Step 3: Once the consumer has redirected the user back to the
    # oauth_callback URL you can request the access token the user has
    # approved. You use the request token to sign this request. After
    # this is done you throw away the request token and use the access
    # token returned. You should store this access token somewhere
    # safe, like a database, for future use.
    token = oauth.Token(request_token['oauth_token'],
                        request_token['oauth_token_secret'])
    token.set_verifier(oauth_verifier)
    client = oauth.Client(consumer, token)

    resp, content = client.request(access_token_url, "POST")
    access_token = dict(urlparse.parse_qsl(content))

    print("Access Token:")
    print("    - oauth_token        = %s" % access_token['oauth_token'])
    print("    - oauth_token_secret = %s" % access_token['oauth_token_secret'])
    print()
    print("You may now access protected resources using the access tokens above.") 
    print()

def twitter_api(token,token_secret,consumer_key,consumer_secret):
    return twitter.Api(consumer_key=consumer_key,
                       consumer_secret=consumer_secret,
                       access_token_key=token,
                       access_token_secret=token_secret)

class twitter_post(ui.dismisspopup):
    def __init__(self,tapi,default_text="",fail_silently=False):
        try:
            user=tapi.VerifyCredentials()
        except:
            if not fail_silently:
                ui.infopopup(["Unable to connect to Twitter"],
                             title="Error")
            return
        ui.dismisspopup.__init__(self,7,76,
                                 title="@%s Twitter"%user.screen_name,
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.tapi=tapi
        self.addstr(2,2,"Type in your update here and press Enter:")
        self.tfield=ui.editfield(
            4,2,72,f=default_text,flen=140,keymap={
                keyboard.K_CLEAR: (self.dismiss,None),
                keyboard.K_CASH: (self.enter,None,False)})
        self.tfield.focus()
    def enter(self):
        ttext=self.tfield.f
        if len(ttext)<20:
            ui.infopopup(title="Twitter Problem",text=[
                    "That's too short!  Try typing some more."])
            return
        self.tapi.PostUpdate(ttext)
        self.dismiss()
        ui.infopopup(title="Tweeted",text=["Your update has been posted."],
                     dismiss=keyboard.K_CASH,colour=ui.colour_confirm)

class Tweet(ui.lrline):
    def __init__(self,status):
        self.status=status
        ui.lrline.__init__(self,ltext=status.text,
                           rtext="(@%s %s)"%(
                status.user.screen_name,status.relative_created_at))

class twitter_client(user.permission_checked,ui.dismisspopup):
    permission_required=("twitter","Use the Twitter client")
    def __init__(self,tapi):
        (mh,mw)=ui.stdwin.getmaxyx()
        # We want to make our window very-nearly full screen
        w=mw-4
        h=mh-2
        self.tapi=tapi
        try:
            user=tapi.VerifyCredentials()
        except:
            ui.infopopup(["Unable to connect to Twitter"],
                         title="Error")
            return
        ui.dismisspopup.__init__(self,h,w,title="@%s Twitter"%user.screen_name,
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.tl=[]
        # The first line of the window is a text entry line for tweeting.
        # The rest of the window is a scrollable list of tweets by us and
        # by other people.
        self.addstr(2,2,"Your tweet: ")
        self.tfield=ui.editfield(
            2,14,w-16,flen=140,keymap={
                keyboard.K_CLEAR: (self.dismiss,None),
                keyboard.K_CASH: (self.enter,None,False)})
        self.tweets=ui.scrollable(4,2,w-4,h-6,self.tl,keymap={
                keyboard.K_CASH: (self.reply,None,False)})
        self.rbutton=ui.buttonfield(
            h-2,2,18,"Refresh",keymap={
                keyboard.K_CASH: (self.refresh,None)})
        ui.map_fieldlist([self.tfield,self.tweets,self.rbutton])
        self.refresh()
    def enter(self):
        ttext=self.tfield.f
        if len(ttext)<20:
            ui.infopopup(title="Twitter Problem",text=[
                    "That's too short!  Try typing some more."])
            return
        status=self.tapi.PostUpdate(ttext)
        self.tfield.set("")
        self.timeline.insert(0,status)
        self.tl.insert(0,Tweet(status))
        self.tweets.redraw()
        self.tfield.focus()
    def reply(self):
        # Fill field with reply info
        self.tfield.set("@%s: "%self.timeline[self.tweets.cursor].
                        user.screen_name)
        self.tfield.focus()
    def refresh(self):
        self.timeline=self.tapi.GetHomeTimeline(count=20)
        #self.timeline=self.timeline+self.tapi.GetReplies()
        self.timeline.sort(key=lambda x:x.created_at_in_seconds)
        self.timeline.reverse()
        self.tl=[Tweet(x) for x in self.timeline]
        self.tweets.set(self.tl)
        self.tfield.focus()
