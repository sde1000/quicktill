#!/usr/bin/env python

import sping.PDF.pdfgen as pdflib

pw=595
ph=842

# Buttons are square. Sizes for different numbers of buttons are:
bs=(38,92)

class button:
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
    def __init__(self,text):
        textbutton.__init__(self,[text])

class bss(textbutton):
    def __init__(self,text):
        textbutton.__init__(self,[text])
        self.fontsize=20
        self.font="Helvetica-Bold"

class sd(textbutton):
    def __init__(self,l1,l2):
        textbutton.__init__(self,[l1,l2])

class dd(sd):
    def __init__(self,l1,l2):
        sd.__init__(self,l1,l2)
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
    
    
# A list of keycaps

kl=(
    ss("Alice"),
    ss("Bob"),
    ss("Charlie"),
    ss("Doris"),
    ss("Eddie"),
    ss("Frank"),
    ss("Giles"),
    ss("Helen"),
    ss("Ian"),
    ss("Jane"),
    ss("Kate"),
    ss("Liz"),
    ss("Maurice"),
    ss("Cancel"),
    ss("Clear"),
    sd("Manage","Till"),
    sd("Manage","Stock"),
    sd("Use","Stock"),
    sd("Record","Waste"),
    ss("Print"),
    sd("Price","Check"),
    sd("Recall","Trans"),
    ss("Quantity"),
    ss("£20"),
    ss("£10"),
    ss("£5"),
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
    ss("Spirits"),
    ss("Misc"),
    ss("Wine"),
    ss("Soft"),
    ss("Food"),
    ss("Bottles"),
    ss("Panic"),
    ss("Void"),
    ss("Help"),
    arrow("UP"),
    arrow("DOWN"),
    arrow("LEFT"),
    arrow("RIGHT"),
    sd("Half","1"),
    sd("Half","2"),
    sd("Half","3"),
    sd("Half","4"),
    sd("Half","5"),
    sd("Half","6"),
    sd("Half","7"),
    sd("Half","8"),
    sd("Half","Lager"),
    sd("Half","Cider"),
    sd("Pint","1"),
    sd("Pint","2"),
    sd("Pint","3"),
    sd("Pint","4"),
    sd("Pint","5"),
    sd("Pint","6"),
    sd("Pint","7"),
    sd("Pint","8"),
    sd("Pint","Lager"),
    sd("Pint","Cider"),
    sd("Plain","Crisps"),
    sd("Cheese &","Onion"),
    sd("Salt &","Vinegar"),
    sd("Salt &","Pepper"),
    sd("Roast Ox","Crisps"),
    sd("Wheat","Crunchies"),
    sd("Mini","Cheddars"),
    sd("Bacon","Fries"),
    sd("Scampi","Fries"),
    sd("Cheese","Moments"),
    ss("Peperami"),
    sd("Salted","Nuts"),
    sd("Dry Roast","Nuts"),
    sd("Other","Nuts"),
    sd("Chilli","Nuts"),
    sd("Honey","Nuts"),
    sd("Fruit","& Nuts"),
    sd("Pistachio","Nuts"),
    ss("Cockles"),
    sd("Pork","Scratch."),
    ss("Chocolate"),
    ss("Twiglets"),
    ss("Pickles"),
    dd("CASH","/ ENTER"),
    ds("HELP"),
    ds("Void Line"),
    )

f=pdflib.Canvas("caps.pdf")
ix=20
maxx=500
x=ix
y=20
lh=0
for i in kl:
    f.saveState()
    f.translate(x,y)
    i.draw(f)
    f.restoreState()
    lh=max(lh,i.height)
    x=x+i.width
    if x>maxx:
        x=ix
        y=y+lh
        lh=0
        
f.save()
del f
