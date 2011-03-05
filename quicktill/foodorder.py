import ui,keyboard,td,printer,urllib,imp,textwrap,curses,sys,traceback,math
import tillconfig

kitchenprinter=None
menuurl=None

class fooditem(ui.lrline):
    def __init__(self,name,price):
        self.update(name,price)
    def update(self,name,price):
        self.name=name
        self.price=price
        ui.lrline.__init__(self,name,tillconfig.fc(self.price)
                           if self.price!=0.0 else "")

# Defaults, for compatibility with older menu definition files; these
# defaults wil be removed once all known menu files have been updated,
# and the popup code will display an error if any of them are missing.
# These defaults are specific to Individual Pubs Limited.

# Default staff discount policy.  Returns the amount to be taken off
# the price of each line of an order.
def default_staffdiscount(tablenumber,item):
    if tablenumber!=0: return 0.00
    discount=item.price*0.4
    if discount>3.00: discount=3.00
    discount=math.floor(discount*20.0)/20.0
    return discount

default_footer=("Please make sure your table number is displayed "
                "on your table.  Your food will be brought to you.")

default_dept=10

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
        try:
            number=int(self.numberfield.f)
        except:
            number=None
        self.dismiss()
        self.func(number)

class edititem(ui.dismisspopup):
    """
    Allow the user to edit the text of a food order item.

    """
    def __init__(self,item,func):
        ui.dismisspopup.__init__(self,5,66,title="Edit line",
                                 dismiss=keyboard.K_CLEAR,
                                 colour=ui.colour_line)
        self.addstr(2,2,"Edit this line:")
        self.linefield=ui.editfield(3,2,62,f=item.name,flen=240,
            keymap={keyboard.K_CASH: (self.enter,None)})
        self.func=func
        self.item=item
        self.linefield.focus()
    def enter(self):
        if len(self.linefield.f)>0:
            self.item.update(self.linefield.f,self.item.price)
        self.dismiss()
        self.func()

class popup(ui.basicpopup):
    def __init__(self,func,ordernumberfunc=td.foodorder_ticket,transid=None):
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
        if "menu" not in self.foodmenu.__dict__:
            ui.infopopup(["The menu file was read succesfully, but did not "
                          "contain a menu definition."],
                         title="No menu defined")
            return
        self.staffdiscount=(
            self.foodmenu.staffdiscount
            if "staffdiscount" in self.foodmenu.__dict__
            else default_staffdiscount)
        self.footer=(
            self.foodmenu.footer
            if "footer" in self.foodmenu.__dict__
            else default_footer)
        self.dept=(
            self.foodmenu.dept
            if "dept" in self.foodmenu.__dict__
            else default_dept)
        self.func=func
        self.transid=transid
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
        self.ml=[] # list of chosen items
        self.order=ui.scrollable(2,2,self.w-4,maxy-1,self.ml,
                                 lastline=ui.emptyline())
        self.toplevel=menuchoice(self.foodmenu.menu)
        self.order.focus()
    def insert_item(self,item):
        self.ml.insert(self.order.cursor,item)
        self.order.cursor_down()
        self.order.redraw()
    def duplicate_item(self):
        if len(self.ml)==0: return
        if self.order.cursor>=len(self.ml):
            self.insert_item(self.ml[-1])
        else:
            self.insert_item(self.ml[self.order.cursor])
    def edit_item(self):
        if len(self.ml)==0: return
        if self.order.cursor_at_end(): return
        edititem(self.ml[self.order.cursor],self.order.redraw)
    def delete_item(self):
        """
        Delete the item under the cursor.  If there is no item under
        the cursor, delete the last item.  The cursor stays in the
        same place.

        """
        if len(self.ml)==0: return # Nothing to delete
        if self.order.cursor_at_end():
            self.ml.pop()
            self.order.cursor_up()
        else:
            del self.ml[self.order.cursor]
        self.order.redraw()
    def printkey(self):
        if len(self.ml)==0:
            ui.infopopup(["You haven't entered an order yet!"],title="Error")
            return
        tablenumber(self.finish)
    def finish(self,tablenumber):
        discount=sum([self.staffdiscount(tablenumber,x) for x in self.ml],0.0)
        if discount>0.0:
            self.ml.append(fooditem("Staff discount",0.0-discount))
        tot=sum([x.price for x in self.ml],0.0)
        number=self.ordernumberfunc()
        # We need to prepare a list of (dept,text,amount) tuples for
        # the register. We enter these into the register before
        # printing, so that we can avoid printing if there is a
        # register problem.
        rl=[(self.dept,x.name,x.price) for x in self.ml]
        if tablenumber is not None:
            rl.insert(0,(self.dept,"Food order %d (table %s):"%
                         (number,tablenumber),0.00))
        else:
            rl.insert(0,(self.dept,"Food order %d:"%number,0.00))
        r=self.func(rl)
        if r==True:
            printer.print_food_order(printer.driver,number,self.ml,
                                     verbose=True,tablenumber=tablenumber,
                                     footer=self.footer,transid=self.transid)
            try:
                printer.print_food_order(kitchenprinter,number,self.ml,
                                         verbose=False,tablenumber=tablenumber,
                                         footer=self.footer,transid=self.transid)
            except:
                e=traceback.format_exception_only(sys.exc_type,sys.exc_value)
                self.dismiss()
                ui.infopopup(
                    ["There was a problem sending the order to the "
                     "printer in the kitchen.  You must now take "
                     "the customer's copy of the order to the kitchen "
                     "so that they can make it.  Check that the printer "
                     "in the kitchen has paper, is turned on, and is plugged "
                     "in to the network.","","The error message from the "
                     "printer is:"]+e,title="Kitchen printer error")
                return
            self.dismiss()
        else:
            ui.infopopup([r],title="Error")
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
        elif k==keyboard.K_CASH:
            self.edit_item()
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
