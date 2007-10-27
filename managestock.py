# -*- coding: iso-8859-1 -*-

"""Implements the 'Manage Stock' menu."""

import ui,td,keyboard,curses,curses.ascii,time,priceguess,printer
import stock,delivery

import logging
log=logging.getLogger()

def newdelivery():
    # New deliveries need a supplier to be chosen before they can be edited.
    log.info("New delivery")
    delivery.selectsupplier(delivery.create_and_edit_delivery,allow_new=True)

def editdelivery():
    log.info("Edit delivery")
    delivery.deliverylist(delivery.delivery,unchecked_only=True)

def displaydelivery():
    log.info("Display delivery")
    delivery.deliverylist(delivery.delivery,checked_only=True)

def finish_reason(sn,reason):
    td.stock_finish(sn,reason)
    log.info("Stock: finished item %d reason %s"%(sn,reason))
    ui.infopopup(["Stock item %d is now finished."%sn],dismiss=keyboard.K_CASH,
                  title="Stock Finished",colour=ui.colour_info)

def finish_item(sn):
    sd=td.stock_info(sn)
    fl=[(x[1],finish_reason,(sn,x[0])) for x in td.stockfinish_list()]
    ui.menu(fl,blurb="Please indicate why you are finishing stock number %d:"%
            sn,title="Finish Stock",w=60)

def finishstock():
    log.info("Finish stock")
    def fs(sn):
        sd=td.stock_info(sn)
        return "%7d %s"%(sn,stock.stock_description(sn))
    sl=td.stock_search()
    sl=[(fs(x),finish_item,(x,)) for x in sl]
    ui.menu(sl,title="Finish stock not currently on sale",
            blurb="Choose a stock item to finish.")

def stockcheck():
    # Build a list of all not-finished stock items.  Things we want to show:
    log.info("Stock check")
    sl=td.stock_search(exclude_stock_on_sale=False)
    def fs(sn):
        sd=td.stock_info(sn)
        return "%7d %-40s %.0f %ss"%(sn,stock.format_stock(sd,maxw=40),
                                 sd['remaining'],sd['unitname'])
    sl=[(fs(x),stock.stockinfo_popup,(x,)) for x in sl]
    ui.menu(sl,title="Stock Check",blurb="Select a stock item and press "
            "Cash/Enter for more information.  The number of units remaining "
            "is shown.",dismiss_on_select=False)

def stockhistory():
    # Build a list of all finished stock items.  Things we want to show:
    log.info("Stock history")
    sl=td.stock_search(finished_stock_only=True)
    sl.reverse()
    def fs(sn):
        sd=td.stock_info(sn)
        return "%7d %-40s %.0f %ss"%(sn,stock.format_stock(sd,maxw=40),
                                 sd['remaining'],sd['unitname'])
    sl=[(fs(x),stock.stockinfo_popup,(x,)) for x in sl]
    ui.menu(sl,title="Stock History",blurb="Select a stock item and press "
            "Cash/Enter for more information.  The number of units remaining "
            "when the stock was finished is shown.",dismiss_on_select=False)

def updatesupplier():
    log.info("Update supplier")
    delivery.selectsupplier(
        lambda x:delivery.editsupplier(lambda a:None,x),allow_new=False)

def popup():
    "Pop up the stock management menu."
    log.info("Stock management popup")
    menu=[
        (keyboard.K_ONE,"Record a new delivery",newdelivery,None),
        (keyboard.K_TWO,"Edit an existing (unconfirmed) delivery",
         editdelivery,None),
        (keyboard.K_THREE,"Display an old (confirmed) delivery",
         displaydelivery,None),
        (keyboard.K_FOUR,"Finish stock not currently on sale",
         finishstock,None),
        (keyboard.K_FIVE,"Stock check (unfinished stock)",stockcheck,None),
        (keyboard.K_SIX,"Stock history (finished stock)",stockhistory,None),
        (keyboard.K_SEVEN,"Update supplier details",updatesupplier,None),
#        (keyboard.K_ZEROZERO,"Correct a stock type record",selectstocktype,
#         (lambda x:selectstocktype(lambda:None,default=x,mode=2),)),
        ]
    ui.keymenu(menu,"Stock Management options")
