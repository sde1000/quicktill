#!/usr/bin/env python

import td

td.init("dbname=oakdale")

kbl=2
# Line, halfkey, pintkey
ll=[
    ("Festival A1","K_LINE16","K_LINE29"),
    ("Festival A2","K_LINE17","K_LINE30"),
    ("Festival A3","K_LINE18","K_LINE31"),
    ("Festival A4","K_LINE19","K_LINE32"),
    ("Festival A5","K_LINE20","K_LINE33"),
    ("Festival A6","K_LINE21","K_LINE34"),
    ("Festival A7","K_LINE22","K_LINE35"),
    ("Festival A8","K_LINE23","K_LINE36"),
    ("Festival B1","K_LINE42","K_LINE55"),
    ("Festival B2","K_LINE43","K_LINE56"),
    ("Festival B3","K_LINE44","K_LINE57"),
    ("Festival B4","K_LINE45","K_LINE58"),
    ("Festival B5","K_LINE46","K_LINE59"),
    ("Festival B6","K_LINE47","K_LINE60"),
    ("Festival B7","K_LINE48","K_LINE61"),
    ("Festival B8","K_LINE49","K_LINE62"),
    ("Festival C1","K_LINE67","K_LINE82"),
    ("Festival C2","K_LINE68","K_LINE83"),
    ("Festival C3","K_LINE69","K_LINE84"),
    ("Festival C4","K_LINE70","K_LINE85"),
    ("Festival C5","K_LINE71","K_LINE86"),
    ("Festival C6","K_LINE72","K_LINE87"),
    ("Festival C7","K_LINE73","K_LINE88"),
    ("Festival C8","K_LINE74","K_LINE89"),
]

for name,halfkey,pintkey in ll:
    line=td.stockline_create(name,"Festival",1,None,None)
    td.keyboard_addbinding(kbl,halfkey,"K_ONE",line,0.5)
    td.keyboard_addbinding(kbl,pintkey,"K_ONE",line,1.0)

