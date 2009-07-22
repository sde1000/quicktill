import select,time,curses,curses.panel

shutdowncode=None

# List of future events; objects must support nexttime() and alarm()
# methods. nexttime() should return the time at which the object next
# wants to be called.
eventlist=[]

# List of file descriptors to watch with handlers.  Expected to be objects
# with a fileno() method that returns the appropriate fd number, and methods
# called doread(), dowrite(), etc.
rdlist=[]

def eventloop():
    while shutdowncode is None:
        # Work out what the earliest timeout is
        timeout=None
        t=time.time()
        for i in eventlist:
            nt=i.nexttime
            i.mainloopnexttime=nt
            if nt is None: continue
            if timeout is None or (nt-t)<timeout:
                timeout=nt-t
        curses.panel.update_panels()
        curses.doupdate()
        # debug curses.beep()
        if timeout>0.0:
            (rd,wr,ex)=select.select(rdlist,[],[],timeout)
            for i in rd: i.doread()
            for i in wr: i.dowrite()
            for i in ex: i.doexcept()
        # Process any events whose time has come
        t=time.time()
        for i in eventlist:
            if i.mainloopnexttime is None: continue
            if t>=i.mainloopnexttime:
                i.alarm()
