from . import ui, keyboard, tillconfig, user, cmdline
import twython
import time, datetime
from requests_oauthlib import OAuth1Session

### Reminders at particular times of day
class reminderpopup:
    def __init__(self, alarmtime, title, text, colour=ui.colour_info,
                 dismiss=keyboard.K_CANCEL):
        """Pop up a reminder at a particular time of day

        Alarmtime is a tuple of (hour, minute).  It will be
        interpreted as being in local time; each time the alarm goes
        off it will be reinterpreted.

        The popup window will appear on whichever page is active at
        the time.
        """
        self.alarmtime = alarmtime
        self.title = title
        self.text = text
        self.colour = colour
        self.dismisskey = dismiss
        ui.run_after_init.append(self.setalarm)

    def setalarm(self):
        # If the alarm time has already passed today, we set the alarm for
        # the same time tomorrow
        now = time.time()
        atime = datetime.time(*self.alarmtime)
        candidate = datetime.datetime.combine(datetime.date.today(), atime)
        if time.mktime(candidate.timetuple()) <= now:
            candidate = candidate + datetime.timedelta(1, 0, 0)
        nexttime = time.mktime(candidate.timetuple())
        tillconfig.mainloop.add_timeout(
            nexttime - now, self.alarm, desc="reminder popup")

    def alarm(self):
        ui.alarmpopup(title=self.title, text=self.text,
                      colour=self.colour, dismiss=self.dismisskey)
        self.setalarm()

class twitter_auth(cmdline.command):
    """Generate tokens for Twitter login.
    """
    command = "twitter-auth"
    help = "authorise with Twitter"

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--consumer-key", action="store",
                            dest="consumer_key",
                            help="OAuth1 consumer key")
        parser.add_argument("--consumer-secret", action="store",
                            dest="consumer_secret",
                            help="OAuth1 consumer secret")

    @staticmethod
    def run(args):
        if not args.consumer_key:
            args.consumer_key = input("Consumer key: ")
        if not args.consumer_secret:
            args.consumer_secret = input("Consumer secret: ")
        request_token_url = 'https://api.twitter.com/oauth/request_token'
        base_authorize_url = 'https://api.twitter.com/oauth/authorize'
        access_token_url = 'https://api.twitter.com/oauth/access_token'
        oauth = OAuth1Session(
            args.consumer_key, client_secret=args.consumer_secret)
        fetch_response = oauth.fetch_request_token(request_token_url)
        resource_owner_key = fetch_response.get('oauth_token')
        resource_owner_secret = fetch_response.get('oauth_token_secret')
        authorize_url = oauth.authorization_url(base_authorize_url)
        print("Please visit this URL: {}".format(authorize_url))
        verifier = input("Enter the PIN from Twitter: ")
        oauth = OAuth1Session(
            args.consumer_key,
            client_secret=args.consumer_secret,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier)
        oauth_tokens = oauth.fetch_access_token(access_token_url)
        resource_owner_key = oauth_tokens.get('oauth_token')
        resource_owner_secret = oauth_tokens.get('oauth_token_secret')

        tapi = twython.Twython(
            app_key=args.consumer_key,
            app_secret=args.consumer_secret,
            oauth_token=resource_owner_key,
            oauth_token_secret=resource_owner_secret)
        user = tapi.verify_credentials()

        print("Paste the following to enable Twitter access as @{}:".format(
            user['screen_name']))
        print("""
        tapi = quicktill.extras.twitter_api(
            token='{}',
            token_secret='{}',
            consumer_key='{}',
            consumer_secret='{}')""".format(
                resource_owner_key, resource_owner_secret,
                args.consumer_key, args.consumer_secret))

def twitter_api(token, token_secret, consumer_key, consumer_secret):
    return twython.Twython(
        app_key=consumer_key,
        app_secret=consumer_secret,
        oauth_token=token,
        oauth_token_secret=token_secret)

class twitter_post(ui.dismisspopup):
    def __init__(self, tapi, default_text="", fail_silently=False):
        try:
            user = tapi.verify_credentials()
        except:
            if not fail_silently:
                ui.infopopup(["Unable to connect to Twitter"],
                             title="Error")
            return
        ui.dismisspopup.__init__(self, 7, 76,
                                 title="@{} Twitter".format(user["screen_name"]),
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_input)
        self.tapi = tapi
        self.addstr(2, 2, "Type in your update here and press Enter:")
        self.tfield = ui.editfield(
            4, 2, 72, f=default_text, flen=140, keymap={
                keyboard.K_CLEAR: (self.dismiss, None),
                keyboard.K_CASH: (self.enter, None, False)})
        self.tfield.focus()

    def enter(self):
        ttext = self.tfield.f
        if len(ttext) < 20:
            ui.infopopup(title="Twitter Problem", text=[
                    "That's too short!  Try typing some more."])
            return
        try:
            self.tapi.update_status(status=ttext)
            self.dismiss()
            ui.infopopup(title="Tweeted", text=["Your update has been posted."],
                         dismiss=keyboard.K_CASH, colour=ui.colour_confirm)
        except:
            ui.popup_exception("Error posting tweet")

class Tweet(ui.lrline):
    def __init__(self, status):
        self.status = status
        ui.lrline.__init__(
            self, ltext=status["text"],
            rtext="(@{} {})".format(
                status["user"]["screen_name"], status["created_at"]))

class twitter_client(user.permission_checked, ui.dismisspopup):
    permission_required = ("twitter", "Use the Twitter client")
    def __init__(self, tapi):
        mh, mw = ui.maxwinsize()
        # We want to make our window very-nearly full screen
        w = mw - 4
        h = mh - 2
        self.tapi = tapi
        try:
            user = tapi.verify_credentials()
        except:
            ui.infopopup(["Unable to connect to Twitter"],
                         title="Error")
            return
        ui.dismisspopup.__init__(
            self, h, w, title="@{} Twitter".format(user["screen_name"]),
            dismiss=keyboard.K_CLEAR,
            colour=ui.colour_input)
        self.tl = []
        # The first line of the window is a text entry line for tweeting.
        # The rest of the window is a scrollable list of tweets by us and
        # by other people.
        self.addstr(2, 2, "Your tweet: ")
        self.tfield = ui.editfield(
            2, 14, w - 16, flen=140, keymap={
                keyboard.K_CLEAR: (self.dismiss, None),
                keyboard.K_CASH: (self.enter, None, False)})
        self.tweets = ui.scrollable(4, 2, w - 4, h - 6, self.tl, keymap={
                keyboard.K_CASH: (self.reply, None, False)})
        self.rbutton = ui.buttonfield(
            h - 2, 2, 18, "Refresh", keymap={
                keyboard.K_CASH: (self.refresh, None)})
        ui.map_fieldlist([self.tfield, self.tweets, self.rbutton])
        self.refresh()

    def enter(self):
        ttext = self.tfield.f
        if len(ttext) < 20:
            ui.infopopup(title="Twitter Problem", text=[
                "That's too short!  Try typing some more."])
            return
        status = self.tapi.update_status(status=ttext)
        self.tfield.set("")
        self.timeline.insert(0, status)
        self.tl.insert(0, Tweet(status))
        self.tweets.redraw()
        self.tfield.focus()

    def reply(self):
        # Fill field with reply info
        self.tfield.set("@{}: ".format(
            self.timeline[self.tweets.cursor]["user"]["screen_name"]))
        self.tfield.focus()

    def refresh(self):
        self.timeline = self.tapi.get_home_timeline(count=20)
        self.timeline.sort(key=lambda x: x["id_str"])
        self.timeline.reverse()
        self.tl = [Tweet(x) for x in self.timeline]
        self.tweets.set(self.tl)
        self.tfield.focus()
