import select,time,curses,curses.panel
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

# List of functions to invoke each time around the event loop
ticklist=[]

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

curses_update_time_guard = time_guard("curses.doupdate",0.1)
doread_time_guard = time_guard("doread",0.5)
dowrite_time_guard = time_guard("dowrite",0.5)
doexcept_time_guard = time_guard("doexcept",0.5)
alarm_time_guard = time_guard("alarm",0.5)

def eventloop():
    while shutdowncode is None:
        for i in ticklist: i()
        # Work out what the earliest timeout is
        timeout=None
        t=time.time()
        for i in eventlist:
            nt=i.nexttime
            i.mainloopnexttime=nt
            if nt is None: continue
            if timeout is None or (nt-t)<timeout:
                timeout=nt-t
        with curses_update_time_guard:
            curses.panel.update_panels()
            curses.doupdate()
        # debug curses.beep()
        if timeout>0.0:
            (rd,wr,ex)=select.select(rdlist,[],[],timeout)
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
        t=time.time()
        for i in eventlist:
            if not hasattr(i,'mainloopnexttime'): continue
            if i.mainloopnexttime and t>=i.mainloopnexttime:
                with alarm_time_guard:
                    i.alarm()
