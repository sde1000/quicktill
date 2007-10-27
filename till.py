#!/usr/bin/env python

"""Main module for quick till application.  This module is imported by
the configuration file for the till.

It is expected that the configuration module will set up logging,
etc.; write appropriate values into the tillconfig module; and then
invoke till.run() with appropriate parameters.

"""

import sys,curses,ui,keyboard,event,register,logging,td,printer
from version import version

log=logging.getLogger()

def start(stdwin,pages):
    # The display is initialised at this point
    stdwin.nodelay(1) # Make getch() non-blocking

    # Initialise screen
    ui.init(stdwin)

    # Create pages for various functions
    fp=None
    for hotkey,args in pages:
        p=ui.addpage(register.page,hotkey,args)
        if fp is None: fp=p
    ui.selectpage(fp)

    # Enter main event loop
    event.eventloop()

def run(database,kblayout,pdriver,kickout,pages):
    """Start up the till software.  Called from the local configuration
    module.

    """

    # Initialise logging
    
    log.info("Starting version %s"%version)
    try:
        td.init(database)
        ui.initkb(kblayout)
        printer.driver=pdriver
        printer.kickout=kickout
        curses.wrapper(start,pages)
    except:
        log.exception("Exception caught at top level")

    log.info("Shutting down")
    logging.shutdown()
