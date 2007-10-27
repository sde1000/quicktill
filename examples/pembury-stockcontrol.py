#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

"""Till configuration file for the Pembury Tavern stock control terminal.

"""

import sys,os,sets,time,math,logging,urllib
#sys.path.append('../quicktill')

from quicktill.keyboard import *
from quicktill import *
import quicktill.keyboard,quicktill.kbdrivers
from quicktill.pdrivers import nullprinter,Epson_TM_U220,pdf
from quicktill.extras import bbcheck,departurelist
import quicktill.tillconfig,quicktill.till,quicktill.stockterminal
import quicktill.ui

dbname="dbname=pembury"

kbdrv=kbdrivers.curseskeyboard()
tillconfig.kbtype=0

#pdriver=nullprinter()
#pdriver=Epson_TM_U220(
#    ('wraith.pembury.i.individualpubs.co.uk',5768),57)
pdriver=pdf("xpdf")

tillconfig.has_media_slot=True

# Define log output here?
log=logging.getLogger()
formatter=logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler=logging.StreamHandler()
handler.setFormatter(formatter)
handler.setLevel(logging.ERROR)
log.addHandler(handler)

def departures():
    menu=[
        (keyboard.K_ONE,"Hackney Downs",departurelist,("Hackney Downs","HAC")),
        (keyboard.K_TWO,"Hackney Central",departurelist,("Hackney Central","HKC")),
        (keyboard.K_THREE,"London Liverpool Street",departurelist,("London Liverpool Street","LST")),
         ]
    ui.keymenu(menu,"Stations")

def extrasmenu():
    menu=[
        (keyboard.K_ONE,"Bar Billiards checker",bbcheck,None),
        (keyboard.K_TWO,"Train Departure Times",departures,None),
        ]
    ui.keymenu(menu,"Extras")

from managestock import popup as managestock
from stock import annotate
from recordwaste import popup as recordwaste
from managetill import popup as managetill
hotkeys={
    ord('s'): managestock,
    ord('S'): managestock,
    ord('a'): annotate,
    ord('A'): annotate,
    ord('r'): recordwaste,
    ord('R'): recordwaste,
    ord('t'): extrasmenu,
    ord('T'): extrasmenu,
    ord('m'): managetill,
    ord('M'): managetill,
    }

pages=[(stockterminal.page,K_ALICE,(hotkeys,))]

f=urllib.urlopen("http://till5.pembury.i.individualpubs.co.uk:8080/pemburyglobal.py")
g=f.read()
f.close()

exec(g)

till.run(dbname,kbdrv,pdriver,pdriver.kickout,pages)
