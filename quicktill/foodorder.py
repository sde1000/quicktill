import ui,keyboard,td,printer,urllib,imp,textwrap,curses,sys,traceback

kitchenprinter=None
menuurl=None

class fooditem:
    def __init__(self,name,price,staffdiscount=False):
        self.name=name
        self.price=price
        self.staffdiscount=staffdiscount
    def getname(self):
        return self.name
    def getprice(self):
        if self.staffdiscount:
            if self.price<=1.50: return self.price
            if self.price<=4.50: return self.price-1.50
            return self.price-3.00
        return self.price
    def display(self,width):
        """
        Returns a list of lines, formatted and padded with spaces to
        the specified maximum width.  The final line includes the
        price aligned to the right.

        """
        name=self.getname()
        price=self.getprice()
        w=textwrap.wrap(name,width)
        if len(w)==0: w=[""]
        pf=" %0.2f"%price
        if price==0.0: pf=""
        if len(w[-1])+len(pf)>width:
            w.append("")
        w[-1]=w[-1]+(' '*(width-len(w[-1])-len(pf)))+pf
        w=["%s%s"%(x,' '*(width-len(x))) for x in w]
        return w

emptyitem=fooditem("",0.0)

class menuchoice:
    def __init__(self,options):
        """
        options is a list of (name,action) tuples

        """
        possible_keys=[
            keyboard.K_ONE, keyboard.K_TWO, keyboard.K_THREE,
            keyboard.K_FOUR, keyboard.K_FIVE, keyboard.K_SIX,
            keyboard.K_SEVEN, keyboard.K_EIGHT, keyboard.K_NINE,
            keyboard.K_ZERO, keyboard.K_ZEROZERO, keyboard.K_POINT]
        o=zip(possible_keys,options)
        self.options=o
        self.optionkeys={}
        for i in o:
            self.optionkeys[i[0]]=i
    def menu_keypress(self,itemfunc,k):
        """
        Possibly handle a keypress which will ultimately lead to the
        selection of a menu item.  When a menu item is selected, call
        itemfunc with the fooditem object as an argument.  If
        something else is selected (a submenu perhaps), invoke its
        display_menu() method and return True to indicate the keypress
        was handled.

        """
        if k in self.optionkeys:
            option=self.optionkeys[k][1]
            # If it's a float then we return the fooditem immediately -
            # it's a simple one.  If not, we assume it's an object
            # and invoke its display_menu method.
            if isinstance(option[1],float):
                itemfunc(fooditem(option[0],option[1]))
                return True
            try:
                option[1].display_menu(itemfunc)
            except:
                e=traceback.format_exception(sys.exc_type,sys.exc_value,
                                             sys.exc_traceback)
                ui.infopopup(e,title="There is a problem with the menu")
            return True
        return False

class simplemenu(menuchoice):
    def __init__(self,options,title=None):
        menuchoice.__init__(self,options)
        self.title=title
    def display_menu(self,itemfunc):
        # Create a popup for the menu.  When it returns an option, set
        # it up to call our menu_keypress method, probably inherited
        # from menuchoice
        il=[(key,opt[0],self.menu_keypress,(itemfunc,key))
            for key,opt in self.options]
        ui.keymenu(il,colour=ui.colour_line,title=self.title)

class subopts:
    """
    A menu item which can have an arbitrary number of suboptions.
    Suboptions can have a price associated with them.  It's possible
    to create classes that override the pricing method to implement
    special price policies, eg. 'Ice cream: first two scoops for 3
    pounds, then 1 pound per extra scoop'.

    """
    def __init__(self,name,itemprice,subopts,atleast=0,atmost=None,
                 connector='; ',nameconnector=': '):
        self.name=name
        self.itemprice=itemprice
        self.subopts=subopts
        self.atleast=atleast
        self.atmost=atmost
        self.nameconnector=nameconnector
        self.connector=connector
    def price(self,options):
        tot=self.itemprice
        for opt,price in options:
            tot=tot+price
        return tot
    def display_menu(self,itemfunc):
        """
        Pop up the suboptions selection dialog.  This has a 'text
        entry' area at the top which is initially filled in with the
        item name.  The suboptions are shown below.  Pressing Enter
        confirms the current entry.  Pressing a suboption number adds
        the option to the dialog.

        """
        subopts_dialog(self.name,self.subopts,self.atleast,self.atmost,
                       self.connector,self.nameconnector,self.finish,
                       itemfunc)
    def finish(self,itemfunc,chosen_options):
        total=self.price(chosen_options)
        listpart=self.connector.join([x[0] for x in chosen_options])
        if len(chosen_options)==0: name=self.name
        else: name=self.nameconnector.join([self.name,listpart])
        itemfunc(fooditem(name,total))
        
class subopts_dialog(ui.dismisspopup):
    def __init__(self,name,subopts,atleast,atmost,connector,nameconnector,
                 func,itemfunc):
        # Height: we need four lines for the "text entry" box at the top,
        # four lines for the top/bottom border, three lines for the prompt,
        # and len(subopts) lines for the suboptions list.
        h=4+4+3+len(subopts)
        self.w=68
        possible_keys=[
            (keyboard.K_ONE," 1"),
            (keyboard.K_TWO," 2"),
            (keyboard.K_THREE," 3"),
            (keyboard.K_FOUR," 4"),
            (keyboard.K_FIVE," 5"),
            (keyboard.K_SIX," 6"),
            (keyboard.K_SEVEN," 7"),
            (keyboard.K_EIGHT," 8"),
            (keyboard.K_NINE," 9"),
            (keyboard.K_ZERO," 0"),
            (keyboard.K_ZEROZERO,"00"),
            (keyboard.K_POINT,". ")]
        opts=zip(possible_keys,subopts)
        km={keyboard.K_CASH: (self.finish,None,False)}
        for k,so in opts:
           km[k[0]]=(self.newsubopt,(so,),False)
        ui.dismisspopup.__init__(self,h,self.w,name+" options",
                                 colour=ui.colour_line,keymap=km)
        y=9
        for k,so in opts:
           self.addstr(y,2,"%s: %s"%(k[1],so[0]))
           y=y+1
        self.ol=[]
        self.name=name
        self.atleast=atleast
        self.atmost=atmost
        self.connector=connector
        self.nameconnector=nameconnector
        self.func=func
        self.itemfunc=itemfunc
        self.redraw()
    def redraw(self):
        listpart=self.connector.join([x[0] for x in self.ol])
        if len(self.ol)>0 or self.atleast>0:
            o=self.name+self.nameconnector+listpart
        else:
            o=self.name
        w=textwrap.wrap(o,self.w-4)
        while len(w)<4: w.append("")
        if len(w)>4: self.atmost=len(self.ol)-1 # stop sillyness!
        w=["%s%s"%(x,' '*(self.w-4-len(x))) for x in w]
        y=2
        attr=curses.color_pair(ui.colour_line)|curses.A_REVERSE
        for i in w:
            self.addstr(y,2,i,attr)
            y=y+1
        self.addstr(7,2,' '*(self.w-4))
        if len(self.ol)<self.atleast:
            self.addstr(7,2,"Choose options from the list below.")
        elif len(self.ol)<self.atmost or self.atmost is None:
            self.addstr(7,2,
                            "Choose options, and press Cash/Enter to confirm.")
        else:
            self.addstr(7,2,"Press Cash/Enter to confirm.")
        self.win.move(2,2)
    def newsubopt(self,so):
        if len(self.ol)<self.atmost or self.atmost is None:
            if isinstance(so[1],float):
                self.ol.append(so)
                self.redraw()
            else:
                possible_keys=[
                    keyboard.K_ONE, keyboard.K_TWO, keyboard.K_THREE,
                    keyboard.K_FOUR, keyboard.K_FIVE, keyboard.K_SIX,
                    keyboard.K_SEVEN, keyboard.K_EIGHT, keyboard.K_NINE,
                    keyboard.K_ZERO, keyboard.K_ZEROZERO, keyboard.K_POINT]
                zz=zip(possible_keys,so[1])
                il=[(key,opt[0],self.newsubopt,(opt,))
                    for key,opt in zz]
                ui.keymenu(il,colour=ui.colour_input,title=so[0])
    def finish(self):
        if len(self.ol)<self.atleast: return
        self.func(self.itemfunc,self.ol)
        self.dismiss()

class tablenumber(ui.dismisspopup):
    """
    Request a table number and call a function with it.

    """
    def __init__(self,func):
        ui.dismisspopup.__init__(self,5,20,title="Table number",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_line)
        self.addstr(2,2,"Table number:")
        self.numberfield=ui.editfield(
            2,16,5,validate=ui.validate_int,
            keymap={keyboard.K_CASH: (self.enter,None)})
        self.func=func
        self.numberfield.focus()
    def enter(self):
        pdriver=printer.driver
        try:
            number=int(self.numberfield.f)
        except:
            number=None
        self.dismiss()
        self.func(number)

class popup(ui.basicpopup):
    def __init__(self,func,ordernumberfunc=td.foodorder_ticket):
        if menuurl is None:
            ui.infopopup(["No menu has been set!"],title="Error")
            return
        try:
            f=urllib.urlopen(menuurl)
            g=f.read()
            f.close()
        except:
            ui.infopopup(["Unable to read the menu!"],title="Error")
            return
        try:
            self.foodmenu=imp.new_module("foodmenu")
            exec g in self.foodmenu.__dict__
        except:
            e=traceback.format_exception(sys.exc_type,sys.exc_value,
                                         sys.exc_traceback)
            ui.infopopup(e,title="There is a problem with the menu")
            return
        self.func=func
        self.ordernumberfunc=ordernumberfunc
        self.h=20
        self.w=64
        ui.basicpopup.__init__(self,self.h,self.w,title="Food Order",
                          colour=ui.colour_input)
        self.addstr(self.h-1,3,"Clear: abandon order   Print: finish   "
                    "Cancel:  delete item")
        # Split the top level menu into lines for display
        tlm=[""]
        labels=["1","2","3","4","5","6","7","8","9","0","00","."]
        for i in self.foodmenu.menu:
            label=labels.pop(0)
            ls="%s: %s"%(label,i[0])
            trial="%s%s%s"%(tlm[-1],('','  ')[len(tlm[-1])>0],ls)
            if len(trial)>self.w-4:
                tlm.append(ls)
            else:
                tlm[-1]=trial
        maxy=self.h-len(tlm)-2
        y=maxy+1
        for i in tlm:
            self.addstr(y,2,i)
            y=y+1
        self.maxy=maxy
        self.toplevel=menuchoice(self.foodmenu.menu)
        self.ml=[] # list of chosen items
        self.cursor=0 # which entry in self.ml is highlighted
        self.top=0 # which item in ml is currently at the top of the window
        self.drawml()
    def insert_item(self,item):
        self.ml.insert(self.cursor,item)
        self.cursor_down()
        self.drawml()
    def duplicate_item(self):
        if len(self.ml)==0: return
        if self.cursor>=len(self.ml):
            self.insert_item(self.ml[-1])
        else:
            self.insert_item(self.ml[self.cursor])
    def delete_item(self):
        """
        Delete the item under the cursor.  If there is no item under
        the cursor, delete the last item.  The cursor stays in the
        same place.

        """
        if len(self.ml)==0: return # Nothing to delete
        if self.cursor==len(self.ml):
            self.ml.pop()
            self.cursor_up()
        else:
            del self.ml[self.cursor]
        self.drawml()
    def cursor_up(self):
        if self.cursor>0: self.cursor=self.cursor-1
        if self.cursor<self.top: self.top=self.cursor
        self.drawml()
    def cursor_down(self):
        if self.cursor<len(self.ml): self.cursor=self.cursor+1
        lastitem=self.drawml()
        while self.cursor>lastitem:
            self.top=self.top+1
            lastitem=self.drawml()
    def drawml(self):
        """
        Redraw the menu with the current scroll and cursor locations.
        Returns the index of the last complete item that fits on the
        screen.  (This is useful to compare against the cursor
        position to ensure the cursor is displayed.)

        """
        # First clear the drawing space
        for y in range(1,self.maxy):
            self.addstr(y,1,' '*(self.w-2))
        y=2
        i=self.top
        lastcomplete=i
        if i>0: self.addstr(1,1,'...')
        else: self.addstr(1,1,'   ')
        cursor_y=None
        while i<=len(self.ml):
            if i>=len(self.ml):
                item=emptyitem
            else:
                item=self.ml[i]
            l=item.display(self.w-4)
            colour=curses.color_pair(ui.colour_input)
            if i==self.cursor:
                colour=colour|curses.A_REVERSE
                cursor_y=y
            for j in l:
                if y<self.maxy:
                    self.addstr(y,2,j,colour)
                    y=y+1
            if y<self.maxy:
                lastcomplete=i
            else:
                break
            i=i+1
        if len(self.ml)>i:
            self.addstr(self.maxy,1,'...')
        else:
            self.addstr(self.maxy,1,'   ')
        if cursor_y is not None:
            self.win.move(cursor_y,2)
        return lastcomplete
    def printkey(self):
        if len(self.ml)==0:
            ui.infopopup(["You haven't entered an order yet!"],title="Error")
            return
        tablenumber(self.finish)
    def finish(self,tablenumber):
        staffdiscount=(tablenumber==0)
        for i in self.ml:
            i.staffdiscount=staffdiscount
        tot=0.0
        for i in self.ml:
            tot+=i.getprice()
        number=self.ordernumberfunc()
        printer.print_food_order(kitchenprinter,number,self.ml,verbose=False,
                                 tablenumber=tablenumber)
        printer.print_food_order(printer.driver,number,self.ml,verbose=True,
                                 tablenumber=tablenumber)
        self.dismiss()
        self.func(tot)
    def keypress(self,k):
        if k==keyboard.K_CLEAR:
            # Maybe ask for confirmation?
            self.dismiss()
        elif k==keyboard.K_CANCEL:
            self.delete_item()
        elif k==keyboard.K_QUANTITY:
            self.duplicate_item()
        elif k==keyboard.K_PRINT:
            self.printkey()
        elif k==keyboard.K_UP:
            self.cursor_up()
        elif k==keyboard.K_DOWN:
            self.cursor_down()
        elif self.toplevel.menu_keypress(self.insert_item,k):
            return

class cancel(ui.dismisspopup):
    def __init__(self):
        ui.dismisspopup.__init__(self,5,20,title="Cancel food order",
                                 colour=ui.colour_input)
        self.addstr(2,2,"Order number:")
        self.field=ui.editfield(
            2,16,5,validate=ui.validate_int,
            keymap={keyboard.K_CASH: (self.finish,None)})
        self.field.focus()
    def finish(self):
        if self.field.f is None or self.field.f=='': return
        number=int(self.field.f)
        printer.print_order_cancel(kitchenprinter,number)
        self.dismiss()
        ui.infopopup(["The kitchen has been asked to cancel order "
                      "number %d."%number],title="Food order cancelled",
                     colour=ui.colour_info,dismiss=keyboard.K_CASH)
