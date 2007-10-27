#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-

from reportlab.pdfgen import canvas

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
    # Screen names
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
    ss("Mallory"),
    ss("Nigel"),
    ss("Oedipus"),
    # Till / stock management keys
    ss("Cancel"),
    ss("Clear"),
    ss("Print"),
    sd("Manage","Till"),
    sd("Manage","Stock"),
    sd("Use","Stock"),
    sd("Record","Waste"),
    sd("Price","Check"),
    sd("Recall","Trans"),
    sd("Manage","Trans"),
    ss("Quantity"),
    ss("Panic"),
    sd("Call","Manager"),
    ss("Void"),
    ss("Help"),
    # Numeric keypad
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
    ss("£20"),
    ss("£10"),
    ss("£5"),
    # Departments
    sd("Real","Ale"),
    ss("Keg"),
    sd("Real","Cider"),
    ss("Spirits"),
    ss("Snacks"),
    ss("Bottles"),
    ss("Soft"),
    ss("Misc"),
    ss("Wine"),
    ss("Food"),
    sd("Hot","Drinks"),
    # Arrows and misc buttons
    arrow("UP"),
    arrow("DOWN"),
    arrow("LEFT"),
    arrow("RIGHT"),
    # Half pints
    sd("Half","A1"),
    sd("Half","A2"),
    sd("Half","A3"),
    sd("Half","A4"),
    sd("Half","A5"),
    sd("Half","A6"),
    sd("Half","A7"),
    sd("Half","A8"),
    sd("Half","A9"),
    sd("Half","A10"),
    sd("Half","A11"),
    sd("Half","A12"),
    sd("Half","A13"),
    sd("Half","A14"),
    sd("Half","A15"),
    sd("Half","A16"),
    sd("Half","A17"),
    sd("Half","A18"),
    sd("Half","A19"),
    sd("Half","A20"),
    sd("Half","A21"),
    sd("Half","A22"),
    sd("Half","A23"),
    sd("Half","A24"),
    sd("Half","A25"),
    sd("Half","A26"),
    sd("Half","A27"),
    sd("Half","A28"),
    sd("Half","A29"),
    sd("Half","A30"),
    sd("Half","B1"),
    sd("Half","B2"),
    sd("Half","B3"),
    sd("Half","B4"),
    sd("Half","B5"),
    sd("Half","B6"),
    sd("Half","B7"),
    sd("Half","B8"),
    sd("Half","B9"),
    sd("Half","B10"),
    sd("Half","B11"),
    sd("Half","B12"),
    sd("Half","B13"),
    sd("Half","B14"),
    sd("Half","B15"),
    sd("Half","B16"),
    sd("Half","B17"),
    sd("Half","B18"),
    sd("Half","B19"),
    sd("Half","B20"),
    sd("Half","B21"),
    sd("Half","B22"),
    sd("Half","B23"),
    sd("Half","B24"),
    sd("Half","B25"),
    sd("Half","B26"),
    sd("Half","B27"),
    sd("Half","B28"),
    sd("Half","B29"),
    sd("Half","B30"),
    sd("Half","C1"),
    sd("Half","C2"),
    sd("Half","C3"),
    sd("Half","C4"),
    sd("Half","C5"),
    sd("Half","C6"),
    sd("Half","C7"),
    sd("Half","C8"),
    sd("Half","C9"),
    sd("Half","C10"),
    sd("Half","C11"),
    sd("Half","C12"),
    sd("Half","C13"),
    sd("Half","C14"),
    sd("Half","C15"),
    sd("Half","C16"),
    sd("Half","C17"),
    sd("Half","C18"),
    sd("Half","C19"),
    sd("Half","C20"),
    sd("Half","C21"),
    sd("Half","C22"),
    sd("Half","C23"),
    sd("Half","C24"),
    sd("Half","C25"),
    sd("Half","C26"),
    sd("Half","C27"),
    sd("Half","C28"),
    sd("Half","C29"),
    sd("Half","C30"),
    sd("Half","Cider 1"),
    sd("Half","Cider 2"),
    sd("Half","Cider 3"),
    sd("Half","Cider 4"),
    sd("Half","Cider 5"),
    sd("Half","Cider 6"),
    sd("Half","Cider 7"),
    sd("Half","Cider 8"),
    sd("Half","Cider 9"),
    sd("Half","Cider 10"),
    # Pints
    sd("Pint","A1"),
    sd("Pint","A2"),
    sd("Pint","A3"),
    sd("Pint","A4"),
    sd("Pint","A5"),
    sd("Pint","A6"),
    sd("Pint","A7"),
    sd("Pint","A8"),
    sd("Pint","A9"),
    sd("Pint","A10"),
    sd("Pint","A11"),
    sd("Pint","A12"),
    sd("Pint","A13"),
    sd("Pint","A14"),
    sd("Pint","A15"),
    sd("Pint","A16"),
    sd("Pint","A17"),
    sd("Pint","A18"),
    sd("Pint","A19"),
    sd("Pint","A20"),
    sd("Pint","A21"),
    sd("Pint","A22"),
    sd("Pint","A23"),
    sd("Pint","A24"),
    sd("Pint","A25"),
    sd("Pint","A26"),
    sd("Pint","A27"),
    sd("Pint","A28"),
    sd("Pint","A29"),
    sd("Pint","A30"),
    sd("Pint","B1"),
    sd("Pint","B2"),
    sd("Pint","B3"),
    sd("Pint","B4"),
    sd("Pint","B5"),
    sd("Pint","B6"),
    sd("Pint","B7"),
    sd("Pint","B8"),
    sd("Pint","B9"),
    sd("Pint","B10"),
    sd("Pint","B11"),
    sd("Pint","B12"),
    sd("Pint","B13"),
    sd("Pint","B14"),
    sd("Pint","B15"),
    sd("Pint","B16"),
    sd("Pint","B17"),
    sd("Pint","B18"),
    sd("Pint","B19"),
    sd("Pint","B20"),
    sd("Pint","B21"),
    sd("Pint","B22"),
    sd("Pint","B23"),
    sd("Pint","B24"),
    sd("Pint","B25"),
    sd("Pint","B26"),
    sd("Pint","B27"),
    sd("Pint","B28"),
    sd("Pint","B29"),
    sd("Pint","B30"),
    sd("Pint","C1"),
    sd("Pint","C2"),
    sd("Pint","C3"),
    sd("Pint","C4"),
    sd("Pint","C5"),
    sd("Pint","C6"),
    sd("Pint","C7"),
    sd("Pint","C8"),
    sd("Pint","C9"),
    sd("Pint","C10"),
    sd("Pint","C11"),
    sd("Pint","C12"),
    sd("Pint","C13"),
    sd("Pint","C14"),
    sd("Pint","C15"),
    sd("Pint","C16"),
    sd("Pint","C17"),
    sd("Pint","C18"),
    sd("Pint","C19"),
    sd("Pint","C20"),
    sd("Pint","C21"),
    sd("Pint","C22"),
    sd("Pint","C23"),
    sd("Pint","C24"),
    sd("Pint","C25"),
    sd("Pint","C26"),
    sd("Pint","C27"),
    sd("Pint","C28"),
    sd("Pint","C29"),
    sd("Pint","C30"),
    sd("Pint","Cider 1"),
    sd("Pint","Cider 2"),
    sd("Pint","Cider 3"),
    sd("Pint","Cider 4"),
    sd("Pint","Cider 5"),
    sd("Pint","Cider 6"),
    sd("Pint","Cider 7"),
    sd("Pint","Cider 8"),
    sd("Pint","Cider 9"),
    sd("Pint","Cider 10"),
    ss(""),
    ss(""),
    ss(""),
    ss(""),
    ss(""),
    ss(""),
    # Payment types / large keys / misc
    ss("4pt jug"),
    ss("Half"),
    ss("Double"),
    ss("Voucher"),
    ss("CARD"),
    sd("Drink","'In'"),
    ds("CARD"),
    dd("CASH","/ ENTER"),
    ds("HELP"),
    ds("Void Line"),
    )

#kl=[ss("")]*315

f=canvas.Canvas("caps.pdf")
ix=13
maxx=550
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
        
f.showPage()
f.save()
del f
