from . import plugins
from . import ui, version
from . import tillconfig
import time
import gc
import logging
log = logging.getLogger(__name__)


class LockScreenPlugin(metaclass=plugins.InstancePluginMount):
    def add_note(self):
        """Return a string to be displayed on the lock page.
        """
        pass

    def draw(self, win, y):
        """Draw on the lock screen; return the new value for 'y'
        """
        return y

    def refresh(self):
        """Return the number of seconds to the next lock screen refresh

        If no refresh is required, return None or 0.
        """
        pass


class CheckPrinter(LockScreenPlugin):
    def __init__(self, description, printer):
        self._description = description
        self._printer = printer

    def add_note(self):
        problem = self._printer.offline()
        if problem:
            log.info("%s problem: %s", self._description, problem)
            return f"{self._description} problem: {problem}"


class lockpage(ui.basicpage):
    def __init__(self):
        super().__init__()
        self.win.set_cursor(False)
        self.idle_timeout = None
        self.refresh_timeout = None
        self.updateheader()
        self._y = 1
        self.line("This till is locked.")
        self._y += 1
        unsaved = [p for p in ui.basicpage._pagelist if p != self]
        if unsaved:
            self.line("The following users have unsaved work "
                      "on this terminal:")
            for p in unsaved:
                self.line(f"  {p.pagename()} ({p.unsaved_data})")
            self.line("")
        else:
            # The till is idle - schedule an exit if configured
            if tillconfig.idle_exit_code is not None:
                now = time.time()
                call_at = max(
                    tillconfig.start_time + tillconfig.minimum_run_time,
                    now + tillconfig.minimum_lock_screen_time)
                self.idle_timeout = tillconfig.mainloop.add_timeout(
                    call_at - now, self.alarm)
        self.win.wrapstr(
            self.h - 1, 0, self.w, f"Till version: {version.version}")
        self.win.drawstr(self._y, 0, 3, '...')
        self.win.move(0, 0)
        self.refresh_timeout = tillconfig.mainloop.add_timeout(
            2, self.draw_plugins)
        log.info("lockpage gc stats: %s, len(gc.garbage)=%d", gc.get_count(),
                 len(gc.garbage))

    def line(self, s):
        self._y += self.win.wrapstr(self._y, 1, self.w, s)

    def pagename(self):
        return "Lock"

    def alarm(self):
        # We are idle and the minimum runtime has been reached
        log.info("Till is idle: exiting with code %s",
                 tillconfig.idle_exit_code)
        tillconfig.mainloop.shutdown(tillconfig.idle_exit_code)

    def draw_plugins(self):
        self.refresh_timeout = None
        self.win.clear(self._y, 0, 1, 3)
        refresh_times = []
        for p in LockScreenPlugin.instances:
            l = p.add_note()
            if l:
                self.line(l)
            self._y = p.draw(self.win, self._y)
            refresh_times.append(p.refresh())
        refresh_time = min((x for x in refresh_times if x), default=0)
        if refresh_time:
            self.refresh_timeout = tillconfig.mainloop.add_timeout(
                refresh_time, self.refresh)
        self.win.move(0, 0)

    def refresh(self):
        # Re-display the page
        self.refresh_timeout = None
        self.deselect()

    def deselect(self):
        # This page ceases to exist when it disappears.
        super().deselect()
        self.dismiss()
        if self.idle_timeout:
            self.idle_timeout.cancel()
        if self.refresh_timeout:
            self.refresh_timeout.cancel()
