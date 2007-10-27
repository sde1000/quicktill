#!/usr/bin/env python

"""Main module for quick till application.  This module is imported by
the configuration file for the till.

It is expected that the configuration module will set up logging,
etc.; write appropriate values into the tillconfig module; and then
invoke till.run() with appropriate parameters.

"""

import sys,curses,ui,keyboard,event,logging,td,printer,tillconfig,event
from version import version

log=logging.getLogger()

def start(stdwin,kbdrv,pages):
    # The display is initialised at this point
    stdwin.nodelay(1) # Make getch() non-blocking

    # Initialise screen
    ui.init(stdwin,kbdrv)

    # Create pages for various functions
    fp=None
    for pagedef,hotkey,args in pages:
        p=ui.addpage(pagedef,hotkey,args)
        if fp is None: fp=p
    ui.selectpage(fp)

    # Enter main event loop
    event.eventloop()

def run(database,kbdrv,pdriver,kickout,pages):
    """Start up the till software.  Called from the local configuration
    module.

    """

    # Initialise logging
    
    log.info("Starting version %s"%version)
    try:
        td.init(database)
        # Copy keycaps from database to keyboard driver
        caps=td.keyboard_getcaps(tillconfig.kbtype)
        for keycode,keycap in caps:
            if kbdrv.setkeycap(keyboard.keycodes[keycode],keycap)==False:
                log.info("Deleting stale keycap for layout %d keycode %s"%(
                    tillconfig.kbtype,keycode))
                td.keyboard_delcap(tillconfig.kbtype,keycap)
        printer.driver=pdriver
        printer.kickout=kickout
        curses.wrapper(start,kbdrv,pages)
    except:
        log.exception("Exception caught at top level")

    log.info("Shutting down")
    logging.shutdown()

    return event.shutdowncode
