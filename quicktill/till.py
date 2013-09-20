#!/usr/bin/env python

"""Entry point for the till application.  In normal use the application
will be started by calling main() from this module.

"""

from __future__ import print_function
import sys,os,curses,logging,locale
from . import ui,keyboard,event,td,printer,tillconfig,event,foodorder
from .version import version
from .models import KeyCap

def start(stdwin):
    # The display is initialised at this point
    stdwin.nodelay(1) # Make getch() non-blocking

    td.start_session()

    # Initialise screen
    ui.init(stdwin)

    # Create pages for various functions
    fp=None
    for pagedef,hotkey,args in tillconfig.pages:
        p=ui.addpage(pagedef,hotkey,args)
        if fp is None: fp=p
    ui.selectpage(fp)
    fp.firstpageinit()

    td.end_session()

    # Enter main event loop
    event.eventloop()

def run():
    # Initialise logging
    log=logging.getLogger()
    log.info("Starting version %s"%version)
    try:
        td.init()
        td.start_session()
        # Copy keycaps from database to keyboard driver
        caps=td.s.query(KeyCap).filter(KeyCap.layout==tillconfig.kbtype).all()
        for key in caps:
            if ui.kb.setkeycap(keyboard.keycodes[key.keycode],key.keycap)==False:
                log.info("Deleting stale keycap for layout %d keycode %s"%(
                    tillconfig.kbtype,key.keycode))
                td.s.delete(key)
        td.s.flush()
        td.end_session()
        curses.wrapper(start)
    except:
        log.exception("Exception caught at top level")

    log.info("Shutting down")
    logging.shutdown()

    return event.shutdowncode

def main():
    """Usual main entry point for the till software, unless you are doing
    something strange.  Reads the location of its global configuration,
    command line options, and the global configuration, and then starts
    the program.

    """
    
    try:
        f=file("/etc/quicktill/configurl")
        configurl=f.readline()
        f.close()
    except:
        configurl=None
    from optparse import OptionParser
    import urllib
    usage="usage: %prog [options]"
    parser=OptionParser(usage,version=version)
    parser.add_option("-u", "--config-url", action="store",
                      type="string", dest="configurl",
                      help="URL of global till configuration file")
    parser.add_option("-c", "--config-name", action="store",
                      type="string", dest="configname",
                      help="Till type to use from configuration file")
    parser.add_option("-d", "--database", action="store",
                      type="string", dest="database",
                      help="Database connection string; overrides "
                      "configuration file")
    parser.add_option("-l", "--logfile", action="store",
                      type="string", dest="logfile",
                      help="Log filename")
    parser.add_option("--debug", action="store_true", dest="debug",
                      help="Include debug output in logfile")
    parser.add_option("-i", "--interactive", action="store_true",
                      dest="interactive",
                      help="Enter interactive database shell")
    parser.set_defaults(configurl=configurl,configname="default",
                        database=None,logfile=None,debug=False,
                        interactive=False)
    (options,args)=parser.parse_args()
    if len(args)>0:
        parser.error("this program takes no arguments")
    if options.configurl==None:
        parser.error("No configuration URL provided in "
                     "/etc/quicktill/configurl or on command line")
    tillconfig.configversion=options.configurl
    f=urllib.urlopen(options.configurl)
    globalconfig=f.read()
    f.close()

    import imp
    g=imp.new_module("globalconfig")
    g.configname=options.configname
    exec globalconfig in g.__dict__

    config=g.configurations.get(options.configname)
    if config is None:
        print(("Configuration \"%s\" does not exist.  "
               "Available configurations:"%options.configname))
        for i in list(g.configurations.keys()):
            print("%s: %s"%(i,g.configurations[i]['description']))
        sys.exit(1)

    if options.debug and options.logfile is None:
        print("You must specify a log file to enable debugging output.")
        sys.exit(1)

    log=logging.getLogger()
    formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler=logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.setLevel(logging.ERROR)
    log.addHandler(handler)
    if options.logfile:
        loglevel=logging.DEBUG if options.debug else logging.INFO
        loghandler=logging.FileHandler(options.logfile)
        loghandler.setFormatter(formatter)
        loghandler.setLevel(logging.DEBUG if options.debug else logging.INFO)
        log.addHandler(loghandler)
        log.setLevel(loglevel)

    if 'printer' in config:
        printer.driver=config['printer'][0](*config['printer'][1])
    else:
        printer.driver=pdrivers.nullprinter()
    printer.kickout=printer.driver.kickout
    if 'labelprinter' in config:
        printer.labeldriver=config['labelprinter'][0](
            *config['labelprinter'][1])
    tillconfig.pages=config['pages']
    td.database=config.get('database')
    if options.database is not None: td.database=options.database
    ui.kb=config['kbdriver']
    tillconfig.kbtype=config['kbtype']
    foodorder.kitchenprinter=config.get('kitchenprinter')
    foodorder.menuurl=config.get('menuurl')
    tillconfig.pubname=config['pubname']
    tillconfig.pubnumber=config['pubnumber']
    tillconfig.pubaddr=config['pubaddr']
    tillconfig.currency=config['currency']
    tillconfig.cashback_limit=config['cashback_limit']
    if 'cashback_first' in config:
        tillconfig.cashback_first=config['cashback_first']
    if 'pricepolicy' in config:
        tillconfig.pricepolicy=config['pricepolicy']
    if 'format_currency' in config:
        tillconfig.fc=config['format_currency']
    if 'priceguess' in config:
        tillconfig.priceguess=config['priceguess']
    if 'deptkeycheck' in config:
        tillconfig.deptkeycheck=config['deptkeycheck']
    if 'modkeyinfo' in config:
        tillconfig.modkeyinfo=config['modkeyinfo']
    if 'nosale' in config:
        tillconfig.nosale=config['nosale']
    if 'checkdigit_print' in config:
        tillconfig.checkdigit_print=config['checkdigit_print']
    if 'checkdigit_on_usestock' in config:
        tillconfig.checkdigit_on_usestock=config['checkdigit_on_usestock']
    if 'allow_tabs' in config:
        tillconfig.allow_tabs=config['allow_tabs']
    if 'transaction_notes' in config:
        tillconfig.transaction_notes=config['transaction_notes']
    if 'usestock_hook' in config:
        tillconfig.usestock_hook=config['usestock_hook']
    if 'btcmerch' in config:
        tillconfig.btcmerch_api=config['btcmerch']

    if os.uname()[0]=='Linux':
        if os.getenv('TERM')=='xterm': os.putenv('TERM','linux')

    locale.setlocale(locale.LC_ALL,'')

    if options.interactive:
        import code
        import readline
        td.init()
        td.start_session()
        console=code.InteractiveConsole()
        console.push("import quicktill.td as td")
        console.push("from quicktill.models import *")
        console.interact()
        td.end_session()
    else:
        sys.exit(run())

if __name__=='__main__':
    main()
