from __future__ import print_function,unicode_literals
from . import ui,keyboard,printer,tillconfig,event,td,user,cmdline
import twitter
import urlparse
from .models import VatBand
import traceback,sys,os,time,datetime
from requests_oauthlib import OAuth1Session

### Bar Billiards checker

class bbcheck(ui.dismisspopup):
    """Given the amount of money taken by a machine and the share of it
    retained by the supplier, print out the appropriate figures for
    the collection receipt.

    """
    def __init__(self,vatband,share=25.0):
        ui.dismisspopup.__init__(self,7,20,title="Bar Billiards check",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        # We assume that VAT band 'A' is the current main VAT rate.
        self.vatrate=float(td.s.query(VatBand).get(vatband).at(datetime.datetime.now()).rate)
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
        with printer.driver as d:
            d.setdefattr(font=1)
            d.printline("Nett take:\t\t%s"%tillconfig.fc(grossamount))
            d.printline("VAT on nett take:\t\t%s"%tillconfig.fc(vat_on_nett_take))
            d.printline("Balance A/B:\t\t%s"%tillconfig.fc(balancea))
            d.printline("Supplier share:\t\t%s"%tillconfig.fc(supplier_share))
            d.printline("Licensee share:\t\t%s"%tillconfig.fc(brewery_share))
            d.printline("VAT on rent:\t\t%s"%tillconfig.fc(vat_on_rent))
            d.printline("(VAT on rent is added to")
            d.printline("'banked' column and subtracted")
            d.printline("from 'left on site' column.)")
            d.printline("Left on site:\t\t%s"%tillconfig.fc(left_on_site))
            d.printline("Banked:\t\t%s"%tillconfig.fc(banked))
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

class twitter_auth(cmdline.command):
    """Generate tokens for Twitter login.

    """
    @staticmethod
    def add_arguments(subparsers):
        parser=subparsers.add_parser(
            'twitter-auth',help="authorise with Twitter",
            description=twitter_auth.__doc__)
        parser.add_argument("--consumer-key", action="store",
                            dest="consumer_key",
                            help="OAuth1 consumer key")
        parser.add_argument("--consumer-secret", action="store",
                            dest="consumer_secret",
                            help="OAuth1 consumer secret")
        parser.set_defaults(command=twitter_auth.run)
    @staticmethod
    def run(args):
        if not args.consumer_key: args.consumer_key=raw_input("Consumer key: ")
        if not args.consumer_secret:
            args.consumer_secret=raw_input("Consumer secret: ")
        request_token_url='https://api.twitter.com/oauth/request_token'
        base_authorize_url = 'https://api.twitter.com/oauth/authorize'
        access_token_url = 'https://api.twitter.com/oauth/access_token'
        oauth=OAuth1Session(args.consumer_key,client_secret=args.consumer_secret)
        fetch_response=oauth.fetch_request_token(request_token_url)
        resource_owner_key=fetch_response.get('oauth_token')
        resource_owner_secret=fetch_response.get('oauth_token_secret')
        authorize_url=oauth.authorization_url(base_authorize_url)
        print("Please visit this URL: {}".format(authorize_url))
        verifier=raw_input("Enter the PIN from Twitter: ")
        oauth=OAuth1Session(args.consumer_key,
                            client_secret=args.consumer_secret,
                            resource_owner_key=resource_owner_key,
                            resource_owner_secret=resource_owner_secret,
                            verifier=verifier)
        oauth_tokens=oauth.fetch_access_token(access_token_url)
        resource_owner_key=oauth_tokens.get('oauth_token')
        resource_owner_secret=oauth_tokens.get('oauth_token_secret')

        tapi=twitter.Api(consumer_key=args.consumer_key,
                         consumer_secret=args.consumer_secret,
                         access_token_key=resource_owner_key,
                         access_token_secret=resource_owner_secret)
        user=tapi.VerifyCredentials()

        print("Paste the following to enable Twitter access as @{}:".format(
            user.screen_name))
        print("""
        tapi=extras.twitter_api(
            token='{}',
            token_secret='{}',
            consumer_key='{}',
            consumer_secret='{}')""".format(
                resource_owner_key,resource_owner_secret,
                args.consumer_key,args.consumer_secret))

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
        try:
            self.tapi.PostUpdate(ttext)
            self.dismiss()
            ui.infopopup(title="Tweeted",text=["Your update has been posted."],
                         dismiss=keyboard.K_CASH,colour=ui.colour_confirm)
        except:
            ui.popup_exception("Error posting tweet")

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
