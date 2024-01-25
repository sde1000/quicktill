from . import ui, keyboard, tillconfig
import time
import datetime
from . import td
from .models import RefusalsLog


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


class twitter_api:
    def __init__(self, token=None, token_secret=None,
                 consumer_key=None, consumer_secret=None,
                 secrets=None):
        pass


def twitter_post(tapi, default_text="", fail_silently=False):
    ui.infopopup(["Twitter support has been removed."], title="Notice")


def twitter_client(tapi):
    ui.infopopup(["Twitter support has been removed."], title="Notice")


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
