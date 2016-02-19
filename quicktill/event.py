import select
import time
import logging

log=logging.getLogger(__name__)

shutdowncode=None

# List of future events; objects must support the nexttime attribute
# and alarm() method. nexttime should be the time at which the object
# next wants to be called, or None if the object temporarily does not
# need to be scheduled.
eventlist=[]

# List of file descriptors to watch with handlers.  Expected to be objects
# with a fileno() method that returns the appropriate fd number, and methods
# called doread(), dowrite(), etc.
rdlist=[]

# List of functions to invoke each time around the event loop.  These
# functions may do anything, including changing timeouts and drawing
# on the display.
ticklist=[]

# List of functions to invoke before calling select.  These functions
# may not change timeouts or draw on the display.  They will typically
# flush queued output.
preselectlist = []

class time_guard(object):
    def __init__(self, name, max_time):
        self._name = name
        self._max_time = max_time
    def __enter__(self):
        self._start_time = time.time()
    def __exit__(self, type, value, traceback):
        t = time.time()
        time_taken = t - self._start_time
        if time_taken > self._max_time:
            log.info("time_guard: %s took %f seconds",self._name,time_taken)

tick_time_guard = time_guard("tick",0.5)
preselect_time_guard = time_guard("preselect",0.1)
doread_time_guard = time_guard("doread",0.5)
dowrite_time_guard = time_guard("dowrite",0.5)
doexcept_time_guard = time_guard("doexcept",0.5)
alarm_time_guard = time_guard("alarm",0.5)

def eventloop():
    while shutdowncode is None:
        # Code in ticklist may update the display
        for i in ticklist:
            with tick_time_guard:
                i()
        # Code in preselect list may not update the display
        for i in preselectlist:
            with preselect_time_guard:
                i()
        # Work out what the earliest timeout is
        timeout = None
        t = time.time()
        for i in eventlist:
            nt = i.nexttime
            i.mainloopnexttime = nt
            if nt is None:
                continue
            if timeout is None or (nt - t) < timeout:
                timeout = nt - t
        if timeout < 0.0:
            timeout = 0.0
        rd, wr, ex = select.select(rdlist, [], [], timeout)
        for i in rd:
            with doread_time_guard:
                i.doread()
        for i in wr:
            with dowrite_time_guard:
                i.dowrite()
        for i in ex:
            with doexcept_time_guard:
                i.doexcept()
        # Process any events whose time has come
        t = time.time()
        for i in eventlist:
            if not hasattr(i,'mainloopnexttime'):
                continue
            if i.mainloopnexttime and t >= i.mainloopnexttime:
                with alarm_time_guard:
                    i.alarm()
