from . import ui, version, printer, foodorder
from . import tillconfig
import time
import gc
import logging
log = logging.getLogger(__name__)

class lockpage(ui.basicpage):
    def __init__(self):
        super().__init__()
        self.win.set_cursor(False)
        self.idle_timeout = None
        self.updateheader()
        self._y = 1
        self.line("This till is locked.")
        self._y += 1
        unsaved = [p for p in ui.basicpage._pagelist if p != self]
        if unsaved:
            self.line("The following users have unsaved work "
                      "on this terminal:")
            for p in unsaved:
                self.line("  {} ({})".format(p.pagename(), p.unsaved_data))
            self.line("")
        else:
            # The till is idle - schedule an exit if configured
            if tillconfig.idle_exit_code is not None:
                now = time.time()
                call_at = max(
                    tillconfig.start_time + tillconfig.minimum_run_time,
                    time.time() + tillconfig.minimum_lock_screen_time)
                self.idle_timeout = tillconfig.mainloop.add_timeout(
                    call_at - now, self.alarm)
        rpproblem = printer.driver.offline()
        if rpproblem:
            self.line("Receipt printer problem: {}".format(rpproblem))
            log.info("Receipt printer problem: %s",rpproblem)
        kpproblem = foodorder._kitchenprinter_problem()
        if kpproblem:
            self.line("Kitchen printer problem: {}".format(kpproblem))
            log.info("Kitchen printer problem: %s",kpproblem)
        self.win.wrapstr(
            self.h - 1, 0, self.w, "Till version: {}".format(version.version))
        self.win.move(0, 0)
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

    def deselect(self):
        # This page ceases to exist when it disappears.
        super().deselect()
        self.dismiss()
        if self.idle_timeout:
            self.idle_timeout.cancel()
