#!/usr/bin/env python

# Main entry point for quick till application.

# Jobs:
# 1) Obtain all required resources (database connection etc.)
# 2) Initialise display
# 3) Event loop
# 4) Cleanup

# We try to keep the internal data structures describing what's going
# on as separate as possible from the display / keyboard logic.  Other
# sources of events can include a timer (on-screen clock) and possibly
# other channels (real-time message etc.)  We have a simple
# select-based event loop.

# There's a further layer on top of the normal ncurses input processing,
# to enable us to recognise keys [xx] on the special keyboard.

import curses,ui,keyboard,managetill,event,register,logging
from version import version

def start(stdwin):
    # The display is initialised at this point
    stdwin.nodelay(1) # Make getch() non-blocking

    # Initialise screen
    ui.init(stdwin)
    # Start on-screen clock
    event.eventlist.append(ui.clock(stdwin))

    # Register keyboard input handler
    event.rdlist.append(ui.reader(stdwin))

    # Create pages for various functions
    a=ui.addpage(register.page,hotkey=keyboard.K_ALICE,args=("Alice",))
    ui.addpage(register.page,hotkey=keyboard.K_BOB,args=("Bob",))
    ui.addpage(register.page,hotkey=keyboard.K_CHARLIE,args=("Charlie",))
    ui.selectpage(a)

    # Enter main event loop
    event.eventloop()

if __name__=='__main__':
    # Initialise logging
    
    log=logging.getLogger()
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    debughandler=logging.FileHandler("debug.log")
    debughandler.setLevel(logging.DEBUG)
    debughandler.setFormatter(formatter)
    infohandler=logging.FileHandler("info.log")
    infohandler.setLevel(logging.INFO)
    infohandler.setFormatter(formatter)
    errorhandler=logging.FileHandler("error.log")
    errorhandler.setLevel(logging.ERROR)
    errorhandler.setFormatter(formatter)
    handler=logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.ERROR)
    log.addHandler(debughandler)
    log.addHandler(infohandler)
    log.addHandler(errorhandler)
    log.addHandler(handler)

    log.setLevel(logging.DEBUG)
    
    log.info("Starting version %s"%version)
    try:
        curses.wrapper(start)
    except:
        log.exception("Exception caught at top level")
    log.info("Shutting down")
    logging.shutdown()
