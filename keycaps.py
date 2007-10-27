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
    sd("Half","1"),
    sd("Half","2"),
    sd("Half","3"),
    sd("Half","4"),
    sd("Half","5"),
    sd("Half","6"),
    sd("Half","7"),
    sd("Half","8"),
    sd("Half","9"),
    sd("Half","10"),
    sd("Half","11"),
    sd("Half","12"),
    sd("Half","13"),
    sd("Half","14"),
    sd("Half","15"),
    sd("Half","16"),
    sd("Half","Lager"),
    sd("Half","Cider"),
    sd("Half","R Cider"),
    sd("Half","St Press"),
    sd("Half","Murphys"),
    sd("Half","XXXX"),
    sd("Half","Budvar"),
    sd("Half","Bitburger"),
    sd("Half","Cellar A"),
    sd("Half","Cellar B"),
    sd("Half","Cellar C"),
    sd("Half","Cellar D"),
    sd("Half","Cellar E"),
    sd("Half","Cellar F"),
    sd("Half","1A"),
    sd("Half","1B"),
    sd("Half","1C"),
    sd("Half","2A"),
    sd("Half","2B"),
    sd("Half","2C"),
    sd("Half","3A"),
    sd("Half","3B"),
    sd("Half","3C"),
    sd("Half","4A"),
    sd("Half","4B"),
    sd("Half","4C"),
    sd("Half","5A"),
    sd("Half","5B"),
    sd("Half","5C"),
    sd("Half","6A"),
    sd("Half","6B"),
    sd("Half","6C"),
    sd("Half","7A"),
    sd("Half","7B"),
    sd("Half","7C"),
    sd("Half","8A"),
    sd("Half","8B"),
    sd("Half","8C"),
    sd("Half","Cider 1"),
    sd("Half","Cider 2"),
    sd("Half","Cider 3"),
    sd("Half","Cider 4"),
    sd("Half","Cider 5"),
    sd("Half","Cider 6"),
    # Pints
    sd("Pint","1"),
    sd("Pint","2"),
    sd("Pint","3"),
    sd("Pint","4"),
    sd("Pint","5"),
    sd("Pint","6"),
    sd("Pint","7"),
    sd("Pint","8"),
    sd("Pint","9"),
    sd("Pint","10"),
    sd("Pint","11"),
    sd("Pint","12"),
    sd("Pint","13"),
    sd("Pint","14"),
    sd("Pint","15"),
    sd("Pint","16"),
    sd("Pint","Lager"),
    sd("Pint","Cider"),
    sd("Pint","R Cider"),
    sd("Pint","St Press"),
    sd("Pint","Murphys"),
    sd("Pint","XXXX"),
    sd("Pint","Budvar"),
    sd("Pint","Bitburger"),
    sd("Pint","Cellar A"),
    sd("Pint","Cellar B"),
    sd("Pint","Cellar C"),
    sd("Pint","Cellar D"),
    sd("Pint","Cellar E"),
    sd("Pint","Cellar F"),
    sd("Pint","1A"),
    sd("Pint","1B"),
    sd("Pint","1C"),
    sd("Pint","2A"),
    sd("Pint","2B"),
    sd("Pint","2C"),
    sd("Pint","3A"),
    sd("Pint","3B"),
    sd("Pint","3C"),
    sd("Pint","4A"),
    sd("Pint","4B"),
    sd("Pint","4C"),
    sd("Pint","5A"),
    sd("Pint","5B"),
    sd("Pint","5C"),
    sd("Pint","6A"),
    sd("Pint","6B"),
    sd("Pint","6C"),
    sd("Pint","7A"),
    sd("Pint","7B"),
    sd("Pint","7C"),
    sd("Pint","8A"),
    sd("Pint","8B"),
    sd("Pint","8C"),
    sd("Pint","Cider 1"),
    sd("Pint","Cider 2"),
    sd("Pint","Cider 3"),
    sd("Pint","Cider 4"),
    sd("Pint","Cider 5"),
    sd("Pint","Cider 6"),
    # Optics, not dedicated to particular brands
    #sd("Optic","1"),
    #sd("Optic","2"),
    #sd("Optic","3"),
    #sd("Optic","4"),
    #sd("Optic","5"),
    #sd("Optic","6"),
    #sd("Optic","7"),
    #sd("Optic","8"),
    #sd("Optic","9"),
    #sd("Optic","10"),
    #sd("Optic","11"),
    #sd("Optic","12"),
    #sd("Optic","13"),
    #sd("Optic","14"),
    #sd("Optic","15"),
    # New Coalheavers keys
    sd("Single","Malt Left"),
    sd("Single","Malt Right"),
    ss("Nuts"),
    sd("Fries /","Crunchies"),
    sd("Other","Snacks"),
    ss("Barbar"),
    sd("Fruit","Beer"),
    sd("Trappist","Ale"),
    sd("Wheat","Beer"),
    sd("Guest","Bottles"),
    sd("Other","Soft drink"),
    sd("Other","Spirits"),
    ss("Half"),
    sd("Dark","Rum"),
    sd("Special","Spirits"),
    # Snacks
    ss("Crisps"),
    sd("Plain","Crisps"),
    sd("Cheese &","Onion"),
    sd("Salt &","Vinegar"),
    sd("Salt &","Pepper"),
    sd("Roast Ox","Crisps"),
    sd("Sea Salt","Crisps"),
    sd("Jalapeno","Pepper"),
    ss("Popp."),
    sd("Chilli &","Peppers"),
    sd("Wheat","Crunchies"),
    sd("Mini","Cheddars"),
    sd("Bacon","Fries"),
    sd("Scampi","Fries"),
    sd("Cheese","Moments"),
    ss("Peperami"),
    sd("Peperami","Red"),
    sd("Peperami","Green"),
    sd("Salted","Nuts"),
    sd("Dry Roast","Nuts"),
    sd("Other","Nuts"),
    sd("Chilli","Nuts"),
    sd("Honey","Nuts"),
    sd("Fruit","& Nuts"),
    sd("Pistachio","Nuts"),
    sd("Special","Nuts"),
    sd("Standard","Nuts"),
    ss("Cockles"),
    sd("Pork","Scratch."),
    ss("Chocolate"),
    ss("Twiglets"),
    ss("Pickles"),
    # Bottled beers
    ss("Val-Dieu"),
    ss("St. F"),
    ss("Schneider"),
    sd("Schneider","Weisse"),
    sd("Schneider","Aventinus"),
    ss("Slag"),
    ss("Duchesse"),
    ss("Hommel"),
    ss("Blanche"),
    ss("Orval"),
    sd("Guinness","F.E."),
    ss("Rochefort"),
    ss("Liefmans"),
    sd("Liefmans","Framb."),
    sd("Liefmans","Kriek"),
    sd("Other","Bottles"),
    # Bottled alcopops
    sd("Bacardi","Breezer"),
    sd("Lime","Breezer"),
    sd("Cranberry","Breezer"),
    sd("Smirnoff","Ice"),
    sd("Gold","Label"),
    # Bottled soft drinks
    ss("J2O"),
    ss("Tonic"),
    sd("Diet","Tonic"),
    sd("Fentimans","Ginger"),
    sd("Dry","Ginger"),
    # Canned soft drinks
    ss("Coke Can"),
    # Spirits
    sd("Smirnoff","Vodka"),
    sd("Bacardi","Rum"),
    sd("Bells","Whisky"),
    sd("Archers","Schnapps"),
    sd("Southern","Comfort"),
    sd("Jack","Daniel's"),
    sd("Captain","Morgan"),
    ss("Malibu"),
    sd("Gordon's","Gin"),
    ss("Martini"),
    ss("Sherry"),
    sd("Bushmills","Whisky"),
    sd("Tia","Maria"),
    ss("Brandy"),
    ss("Tanqueray"),
    sd("Single","Malt"),
    sd("Other","Spirit"),
    # Random stuff
    sd("Small","Wine"),
    sd("Medium","Wine"),
    sd("Large","Wine"),
    sd("Wine","Bottle"),
    sd("Other","Bot. Beer"),
    sd("Other","Bot. Soft"),
    sd("Soft","Pint"),
    sd("Soft","Half"),
    sd("Mixer","40p"),
    sd("Mixer","20p"),
    ss("Cordial"),
    sd("Order","Food"),
    sd("Cancel","Food"),
    ss(""),
    # Payment types / large keys / misc
    ss("4pt jug"),
    ss("Double"),
    ss("Voucher"),
    ss("CARD"),
    sd("Drink","'In'"),
    ds("CARD"),
    dd("CASH","/ ENTER"),
    ds("HELP"),
    ds("Void Line"),
    )

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
