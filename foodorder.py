import ui,keyboard,td,printer,urllib

kitchenprinter=None
menuurl=None

def nv(node):
    if isinstance(node,tuple): return node
    return (node,None,False,None)

# We build a graph of available options from the menu tree.  The main
# food ordering menu builds up a list of selected options; each option
# allows the list of available next options to be retrieved.
class node:
    def __init__(self,parent,info,indent=0):
        name,price,allowpeers,children=nv(info)
        self.parent=parent
        self.name=name
        self.price=price
        self.allowpeers=allowpeers
        self.indent=indent
        if children:
            self.children=[node(self,x,indent+1) for x in children]
        else: self.children=[]
    def getchoices(self):
        return self.children+self.getparentchoices()
    def getparentchoices(self):
        if self.parent is None: return []
        if self.parent.allowpeers:
            return self.parent.getchoices()
        return self.parent.getparentchoices()
    def __str__(self):
        return ' '*self.indent+self.name

class popup(ui.dismisspopup):
    def __init__(self,func):
        if menuurl is None:
            ui.infopopup(["No menu has been set!"],title="Error")
            return
        f=urllib.urlopen(menuurl)
        g=f.read()
        f.close()
        try:
            exec(g)
            self.root=node(None,("root",None,True,menu),indent=-1)
        except:
            ui.infopopup(["There is a problem with the menu.",
                          "Ordering food is not possible until "
                          "the problem is corrected."],title="Error")
            return
        self.func=func
        self.h=20
        self.w=64
        ui.dismisspopup.__init__(self,self.h,self.w,title="Food Order",
                                 colour=ui.colour_input)
        self.win=self.pan.window()
        self.ml=[] # list of chosen nodes
        self.win.addstr(2,2,"Enter food order and press Print to finish.")
        self.buildfield()
    def buildfield(self,default=None):
        if len(self.ml)==0: parentnode=self.root
        else: parentnode=self.ml[-1]
        choices=parentnode.getchoices()
        d=dict([(x,str(x)) for x in choices])
        y=4+len(self.ml)
        km={keyboard.K_UP: (self.goback,None,False),
            keyboard.K_CLEAR: (self.goback,None,False),
            keyboard.K_PRINT: (self.finish,None,False)}
        if y<(self.h-2):
            km[keyboard.K_DOWN]=(self.fieldset,None,False)
        if default is not None:
            default=choices.index(default)
        self.field=ui.listfield(self.win,y,2,60,choices,d,keymap=km,f=default)
        self.field.focus()
    def erasefield(self):
        self.field=None
        y=4+len(self.ml)
        self.win.addstr(y,2,' '*60)
    def drawml(self):
        y=4
        for i in self.ml:
            self.win.addstr(y,2,str(i))
            y=y+1
    def fieldset(self):
        c=self.field.read()
        if c is None: return
        self.erasefield()
        self.ml.append(c)
        self.drawml()
        self.buildfield()
    def goback(self):
        self.erasefield()
        if len(self.ml)>0:
            default=self.ml[-1]
            self.ml=self.ml[:-1]
            self.buildfield(default)
        else:
            self.dismiss()
    def finish(self):
        self.fieldset()
        if len(self.ml)==0:
            ui.infopopup(["You haven't entered an order yet!"],title="Error")
            return
        number=td.foodorder_ticket()
        printer.print_food_order(kitchenprinter,number,self.ml,verbose=False)
        printer.print_food_order(printer.driver,number,self.ml,verbose=True)
        self.dismiss()
        tot=0.0
        for i in self.ml:
            if i.price is not None: tot+=i.price
        self.func(tot)

class cancel(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,5,20,title="Cancel food order",
                                 colour=ui.colour_input)
        win=self.pan.window()
        win.addstr(2,2,"Order number:")
        self.field=ui.editfield(win,2,16,5,validate=ui.validate_int,
                                keymap={
            keyboard.K_CASH: (self.finish,None,False),
            keyboard.K_CLEAR: (self.dismiss,None,False)})
        self.field.focus()
    def finish(self):
        if self.field.f is None or self.field.f=='': return
        number=int(self.field.f)
        printer.print_order_cancel(kitchenprinter,number)
        self.dismiss()
        ui.infopopup(["The kitchen has been asked to cancel order "
                      "number %d."%number],title="Food order cancelled",
                     colour=ui.colour_info,dismiss=keyboard.K_CASH)

