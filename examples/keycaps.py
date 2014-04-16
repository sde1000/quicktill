#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Example script to generate a grid of keyboard labels suitable for
# cutting out and putting under the caps of a Preh keyboard

from __future__ import unicode_literals

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4 as A4

pw,ph=A4

# Buttons come in single and double types
bs=(39,92)

class button(object):
    def __init__(self):
        self.width=bs[0]
        self.height=bs[0]
    def draw(self,f):
        f.setLineWidth(0.25)
        f.rect(0,0,self.width,self.height)

class textbutton(button):
    def __init__(self,lines):
        button.__init__(self)
        self.lines=lines
        self.lines.reverse()
        self.fontsize=8
        self.pitch=10
        self.font="Helvetica"
    def draw(self,f):
        button.draw(self,f)
        f.setFont(self.font,self.fontsize)
        l=len(self.lines)
        totalheight=(l-1)*self.pitch+self.fontsize
        y=(self.height-totalheight)/2+1
        for i in self.lines:
            f.drawCentredString(self.width/2,y,i)
            y=y+self.pitch

class ss(textbutton):
    def __init__(self,*args):
        textbutton.__init__(self,list(args))

class bss(textbutton):
    def __init__(self,text):
        textbutton.__init__(self,[text])
        self.fontsize=20
        self.font="Helvetica-Bold"

class dd(ss):
    def __init__(self,*args):
        ss.__init__(self,*args)
        self.width=bs[1]
        self.height=bs[1]
        self.fontsize=18
        self.pitch=18
        self.font="Helvetica-Bold"

class ds(textbutton):
    def __init__(self,text):
        textbutton.__init__(self,[text])
        self.width=bs[1]
        self.fontsize=16

class arrow(button):
    def __init__(self,kind):
        button.__init__(self)
        self.kind=kind
    def draw(self,f):
        button.draw(self,f)
        f.translate(self.width/2,self.height/2)
        if self.kind=='LEFT':
            f.rotate(90)
        elif self.kind=='RIGHT':
            f.rotate(270)
        elif self.kind=='DOWN':
            f.rotate(180)
        p=f.beginPath()
        p.moveTo(-1,0)
        p.lineTo(-1,10)
        p.lineTo(-3,10)
        p.lineTo(0,13)
        p.lineTo(3,10)
        p.lineTo(1,10)
        p.lineTo(1,0)
        p.close()
        f.drawPath(p,stroke=0,fill=1)
    
    
# A list of keycaps on the standard IPL keyboard

kl=(
    # Bright yellow
    ss("Alice"),
    ss("Bob"),
    ss("Charlie"),
    ss("Drink 'In'"),
    ss("Double"),
    ss("Quantity"),
    ss("4pt jug"),
    ss("Half"),
    ss("£20"),
    ss("£10"),
    ss("£5"),
    ds("CARD"),
    dd("CASH","/ ENTER"),
    # Bright red
    ss("Clear"),
    ds("Lock"),
    # Green
    ss("Stock","Terminal"),
    ss("Recall","Trans"),
    ss("Price","Check"),
    ss("Cancel"),
    ss("Manage","Till"),
    ss("Manage","Stock"),
    ss("Use","Stock"),
    ss("Record","Waste"),
    ss("Manage","Trans"),
    ss("Print"),
    ss("Apps"),
    ss("Order","Food"),
    ss("Kitchen","Message"),
    # Dark blue - departments
    ss("Misc"),
    ss("Hot","Drinks"),
    ss("Wine"),
    ss("Soft"),
    ss("Food"),
    # White - cursor keys and numbers
    arrow("UP"),
    arrow("DOWN"),
    arrow("LEFT"),
    arrow("RIGHT"),
    bss("00"),
    bss("0"),
    bss("1"),
    bss("2"),
    bss("3"),
    bss("4"),
    bss("5"),
    bss("6"),
    bss("7"),
    bss("8"),
    bss("9"),
    bss("."),

    # Put your own keycaps here

    # Dark blue - same as departments
    ss("Crisps"),
    ss("Nuts"),
    ss("Other","Snacks"),
    ss("Rolls"),
    ss("Pint 1"),
    ss("Pint 2"),
    ss("Pint 3"),
    ss("Pint 4"),
    ss("Half 5"),
    ss("Half 6"),
    ss("Half 7"),
    ss("Half 8"),
    ss("Pint","Lager"),
    ss("Pint","Thatchers"),
    ss("Pint","Real Cider"),

    # Pale blue
    ss("Half 1"),
    ss("Half 2"),
    ss("Half 3"),
    ss("Half 4"),
    ss("Pint 5"),
    ss("Pint 6"),
    ss("Pint 7"),
    ss("Pint 8"),
    ss("Half","Lager"),
    ss("Half","Thatchers"),
    ss("Half","Real Cider"),

    # Bright yellow
    ss("Coke Can"),
    ss("Tonic"),
    ss("J2O"),

    # Orangey
    ss("Fruit","Beer"),
    ss("Trappist"),
    ss("Cider / ","Ginger"),
    ss("German","Bottle"),
    ss("Abbaye"),
    ss("Craft","Bottle"),
    ss("Other","Bottle"),
    ss("Soft","Bottle"),

    # Pale green
    ss("Bar","Spirits"),
    ss("Bells"),
    ss("Southern","Comfort"),
    ss("Bacardi"),
    ss("Brandy"),
    ss("Lambs"),
    ss("Smirnoff"),
    ss("Gordons"),
    ss("Half","Soft Drink"),
    ss("Pint","Soft Drink"),
    ss("Dash /","Mixer"),
    ss("125ml","Wine"),
    ss("175ml","Wine"),
    ss("250ml","Wine"),

    # Pale red
    ss("Gins"),
    ss("Speyside"),
    ss("Islay"),
    ss("Lowland"),
    ss("Highland"),
    ss("Other","Spirit"),

    # White
    ss("Half","Garage"),
    ss("Pint","Garage"),
    )

if __name__=="__main__":
    f=canvas.Canvas("caps.pdf")
    margin=28
    maxx=pw-margin
    x=margin
    y=margin
    lh=0
    for i in kl:
        if (x+i.width)>maxx:
            x=margin
            y=y+lh
            lh=0
        f.saveState()
        f.translate(x,y)
        i.draw(f)
        f.restoreState()
        lh=max(lh,i.height)
        x=x+i.width
        
    f.showPage()
    f.save()
    del f
