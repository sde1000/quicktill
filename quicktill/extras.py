from . import ui, keyboard, tillconfig, user, cmdline
import twython
import time
import datetime
from requests_oauthlib import OAuth1Session
from . import td
from .models import RefusalsLog
from .secretstore import Secrets, SecretException


# Reminders at particular times of day
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
    database_required = True

    @staticmethod
    def add_arguments(parser):
        parser.add_argument("--consumer-key", action="store",
                            dest="consumer_key",
                            help="OAuth1 consumer key")
        parser.add_argument("--consumer-secret", action="store",
                            dest="consumer_secret",
                            help="OAuth1 consumer secret")
        parser.add_argument("secretstore",
                            help="Name of secretstore for credentials")

    @staticmethod
    def run(args):
        secrets = Secrets.find(args.secretstore)
        if not secrets:
            print(f"Unable to access secret store '{args.secretstore}'.")
            return 1
        try:
            with td.orm_session():
                consumer_key = secrets.fetch("consumer-key")
                consumer_secret = secrets.fetch("consumer-secret")
        except SecretException:
            consumer_key = None
            consumer_secret = None
        if args.consumer_key and args.consumer_secret:
            consumer_key = args.consumer_key
            consumer_secret = args.consumer_secret
        if not consumer_key:
            consumer_key = input("Consumer key: ")
        if not consumer_secret:
            consumer_secret = input("Consumer secret: ")
        with td.orm_session():
            secrets.store("consumer-key", consumer_key, create=True)
            secrets.store("consumer-secret", consumer_secret, create=True)
        request_token_url = 'https://api.twitter.com/oauth/request_token'
        base_authorize_url = 'https://api.twitter.com/oauth/authorize'
        access_token_url = 'https://api.twitter.com/oauth/access_token'
        oauth = OAuth1Session(
            consumer_key, client_secret=consumer_secret)
        fetch_response = oauth.fetch_request_token(request_token_url)
        resource_owner_key = fetch_response.get('oauth_token')
        resource_owner_secret = fetch_response.get('oauth_token_secret')
        authorize_url = oauth.authorization_url(base_authorize_url)
        print(f"Please visit this URL: {authorize_url}")
        verifier = input("Enter the PIN from Twitter: ")
        oauth = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier)
        oauth_tokens = oauth.fetch_access_token(access_token_url)
        resource_owner_key = oauth_tokens.get('oauth_token')
        resource_owner_secret = oauth_tokens.get('oauth_token_secret')

        tapi = twython.Twython(
            app_key=consumer_key,
            app_secret=consumer_secret,
            oauth_token=resource_owner_key,
            oauth_token_secret=resource_owner_secret)
        user = tapi.verify_credentials()

        print(f"Twitter access as @{user['screen_name']} configured.")

        with td.orm_session():
            secrets.store("token", resource_owner_key, create=True)
            secrets.store("token-secret", resource_owner_secret, create=True)


class twitter_api:
    def __init__(self, token=None, token_secret=None,
                 consumer_key=None, consumer_secret=None,
                 secrets=None):
        self.token = token
        self.token_secret = token_secret
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.credentials_provided = \
            token and token_secret and consumer_key and consumer_secret
        self.secrets = secrets

        # The database isn't available when __init__ is
        # called. Schedule a callback once initialisation is complete.
        if secrets:
            ui.run_after_init.append(self._secret_init)

    def _secret_init(self):
        try:
            if self.credentials_provided:
                # Store the credentials in the secretstore
                self.secrets.store(
                    "token", self.token, create=True)
                self.secrets.store(
                    "token-secret", self.token_secret, create=True)
                self.secrets.store(
                    "consumer-key", self.consumer_key, create=True)
                self.secrets.store(
                    "consumer-secret", self.consumer_secret, create=True)
            else:
                # Read the credentials from the secretstore
                self.token = self.secrets.fetch("token")
                self.token_secret = self.secrets.fetch("token-secret")
                self.consumer_key = self.secrets.fetch("consumer-key")
                self.consumer_secret = self.secrets.fetch("consumer-secret")
        except SecretException:
            pass

    def __call__(self):
        return twython.Twython(
            app_key=self.consumer_key,
            app_secret=self.consumer_secret,
            oauth_token=self.token,
            oauth_token_secret=self.token_secret)


class twitter_post(ui.dismisspopup):
    def __init__(self, tapi, default_text="", fail_silently=False):
        tapi = tapi()
        try:
            user = tapi.verify_credentials()
        except Exception:
            if not fail_silently:
                ui.infopopup(["Unable to connect to Twitter"],
                             title="Error")
            return
        super().__init__(7, 76,
                         title=f'@{user["screen_name"]} Twitter',
                         dismiss=keyboard.K_CLEAR,
                         colour=ui.colour_input)
        self.tapi = tapi
        self.win.drawstr(2, 2, 72, "Type in your update here and press Enter:")
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
            ui.infopopup(
                title="Tweeted", text=["Your update has been posted."],
                dismiss=keyboard.K_CASH, colour=ui.colour_confirm)
        except Exception:
            ui.popup_exception("Error posting tweet")


class Tweet(ui.lrline):
    def __init__(self, status):
        self.status = status
        super().__init__(
            ltext=status["text"],
            rtext=f'(@{status["user"]["screen_name"]} {status["created_at"]})')


class twitter_client(user.permission_checked, ui.dismisspopup):
    permission_required = ("twitter", "Use the Twitter client")

    def __init__(self, tapi):
        tapi = tapi()
        mh, mw = ui.rootwin.size()
        # We want to make our window very-nearly full screen
        w = mw - 4
        h = mh - 2
        self.tapi = tapi
        try:
            user = tapi.verify_credentials()
        except Exception:
            ui.infopopup(["Unable to connect to Twitter"],
                         title="Error")
            return
        super().__init__(
            h, w, title=f'@{user["screen_name"]} Twitter',
            dismiss=keyboard.K_CLEAR,
            colour=ui.colour_input)
        self.tl = []
        # The first line of the window is a text entry line for tweeting.
        # The rest of the window is a scrollable list of tweets by us and
        # by other people.
        self.win.drawstr(2, 2, 12, "Your tweet: ", align=">")
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
        self.tfield.set(
            f'@{self.timeline[self.tweets.cursor]["user"]["screen_name"]}: ')
        self.tfield.focus()

    def refresh(self):
        self.timeline = self.tapi.get_home_timeline(count=20)
        self.timeline.sort(key=lambda x: x["id_str"])
        self.timeline.reverse()
        self.tl = [Tweet(x) for x in self.timeline]
        self.tweets.set(self.tl)
        self.tfield.focus()


def refusals():
    reasons = [
        "ID requested but no ID provided",
        "ID requested but was not valid",
        "Purchaser appeared drunk",
        "Other",
        "(Training: not a real refusal)",
    ]
    ui.automenu([(x, _finish_refusal, (x,)) for x in reasons],
                title="Reason for refusing sale")


class _finish_refusal(ui.dismisspopup):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(10, 76, title="Refusals log entry",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 72, "Please add any additional details below "
                         "and press Enter.")
        self.win.drawstr(4, 2, 72, f"Reason: {reason}")
        self.text = ui.editfield(
            6, 2, 72, keymap={
                keyboard.K_CLEAR: (self.dismiss, None),
                keyboard.K_CASH: (self.enter, None, False)})
        self.text.focus()

    def enter(self):
        td.s.add(RefusalsLog(
            user_id=ui.current_user().userid,
            terminal=tillconfig.configname,
            details=f"{self.reason} - {self.text.f}"))
        self.dismiss()
        ui.toast("Refusals log entry added")
