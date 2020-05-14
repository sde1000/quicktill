import urllib
from types import ModuleType
import textwrap
import sys
import traceback
import datetime
import hashlib
import logging
from . import ui, keyboard, td, printer, tillconfig, user
from . import lockscreen
from . import register
from .models import zero, penny
from decimal import Decimal

log = logging.getLogger(__name__)

class fooditem(ui.lrline):
    def __init__(self, name, price, dept=None):
        self.dept = dept
        self.update(name, price, dept)

    def update(self, name, price, dept=None):
        self.name = name
        self.price = Decimal(price).quantize(penny)
        if dept:
            self.dept = dept
        super().__init__(name, tillconfig.fc(self.price)
                         if self.price != zero else "")

    def copy(self):
        return fooditem(self.name, self.price, self.dept)

def handle_option(itemfunc, option):
    """Handle an option chosen from a menu

    An option is either a tuple of (name, price), a tuple of (name,
    price, dept), or a tuple of (name, action) where action is an
    object with a display_menu method.
    """
    if hasattr(option[1], 'display_menu'):
        with ui.exception_guard("processing the menu option"):
            option[1].display_menu(itemfunc, default_title=option[0])
    else:
        itemfunc(fooditem(*option))

class simplemenu:
    def __init__(self, options, title=None):
        self.options = options
        self.title = title

    def display_menu(self, itemfunc, default_title=None):
        il = [(opt[0], handle_option, (itemfunc, opt))
            for opt in self.options]
        ui.automenu(il, spill="keymenu", colour=ui.colour_line,
                    title=self.title or default_title)

class subopts:
    """
    A menu item which can have an arbitrary number of suboptions.
    Suboptions can have a price associated with them.  It's possible
    to create classes that override the pricing method to implement
    special price policies, eg. 'Ice cream: first two scoops for 3
    pounds, then 1 pound per extra scoop'.

    """
    def __init__(self, name, itemprice, subopts, dept=None, atleast=0, atmost=None,
                 connector='; ', nameconnector=': '):
        self.name = name
        self.itemprice = itemprice
        self.subopts = subopts
        self.atleast = atleast
        self.atmost = atmost
        self.nameconnector = nameconnector
        self.connector = connector
        self.dept = dept

    def price(self, options):
        tot = self.itemprice
        for opt, price in options:
            tot = tot + price
        return tot

    def display_menu(self, itemfunc, default_title=None):
        """
        Pop up the suboptions selection dialog.  This has a 'text
        entry' area at the top which is initially filled in with the
        item name.  The suboptions are shown below.  Pressing Enter
        confirms the current entry.  Pressing a suboption number adds
        the option to the dialog.

        """
        subopts_dialog(self.name, self.subopts, self.atleast, self.atmost,
                       self.connector, self.nameconnector, self.finish,
                       itemfunc)

    def finish(self, itemfunc, chosen_options):
        total = self.price(chosen_options)
        listpart = self.connector.join([x[0] for x in chosen_options])
        if len(chosen_options) == 0:
            name = self.name
        else:
            name = self.nameconnector.join([self.name, listpart])
        itemfunc(fooditem(name, total, self.dept))
        
class subopts_dialog(ui.dismisspopup):
    def __init__(self, name, subopts, atleast, atmost, connector, nameconnector,
                 func, itemfunc):
        possible_keys = [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "00", "."]
        # If we have more options than keys, split them into a submenu.
        if len(subopts) > len(possible_keys):
            subopts = subopts[:len(possible_keys) - 1] + \
                     [("More...", subopts[len(possible_keys) - 1:])]
        # Height: we need four lines for the "text entry" box at the top,
        # four lines for the top/bottom border, three lines for the prompt,
        # and len(subopts) lines for the suboptions list.
        h = 4 + 4 + 3 + len(subopts)
        self.w = 68
        opts = list(zip(possible_keys, subopts))
        km = {keyboard.K_CASH: (self.finish, None, False)}
        for k, so in opts:
           km[k] = (self.newsubopt, (so,), False)
        super().__init__(h, self.w, name + " options",
                         colour=ui.colour_line, keymap=km)
        y = 9
        for k, so in opts:
           self.win.addstr(y, 2, f"{k:>2}: {so[0]}")
           y = y + 1
        self.ol = []
        self.name = name
        self.atleast = atleast
        self.atmost = atmost
        self.connector = connector
        self.nameconnector = nameconnector
        self.func = func
        self.itemfunc = itemfunc
        self.redraw()

    def redraw(self):
        listpart = self.connector.join([x[0] for x in self.ol])
        if len(self.ol) > 0 or self.atleast > 0:
            o = self.name + self.nameconnector + listpart
        else:
            o = self.name
        w = textwrap.wrap(o, self.w - 4)
        while len(w) < 4:
            w.append("")
        if len(w) > 4:
            self.atmost = len(self.ol) - 1 # stop sillyness!
        w = ["%s%s"%(x, ' ' * (self.w - 4 - len(x))) for x in w]
        y = 2
        colour = ui.colour_line.reversed
        for i in w:
            self.win.addstr(y, 2, i, colour)
            y = y + 1
        self.win.addstr(7, 2, ' ' * (self.w - 4))
        if len(self.ol) < self.atleast:
            self.win.addstr(7, 2, "Choose options from the list below.")
        elif self.atmost is None or len(self.ol) < self.atmost:
            self.win.addstr(7, 2,
                            "Choose options, and press Cash/Enter to confirm.")
        else:
            self.win.addstr(7, 2, "Press Cash/Enter to confirm.")
        self.win.move(2, 2)

    def newsubopt(self, so):
        if self.atmost is None or len(self.ol) < self.atmost:
            if isinstance(so[1], float):
                self.ol.append(so)
                self.redraw()
            else:
                il = [(opt[0], self.newsubopt, (opt,)) for opt in so[1]]
                ui.automenu(il, spill="keymenu", colour=ui.colour_input, title=so[0])

    def finish(self):
        if len(self.ol) < self.atleast:
            return
        self.func(self.itemfunc, self.ol)
        self.dismiss()

def print_food_order(driver, number, ol, verbose=True, tablenumber=None, footer="",
                     transid=None, print_total=True, user=None):
    """This function prints a food order to the _specified_ printer.
    """
    with driver as d:
        if verbose:
            d.printline(f"\t{tillconfig.pubname}", emph=1)
            for i in tillconfig.pubaddr:
                d.printline(f"\t{i}",colour=1)
            d.printline(f"\tTel. {tillconfig.pubnumber}")
            d.printline()
        if tablenumber is not None:
            d.printline(f"\tTable number {tablenumber}", colour=1, emph=1)
            d.printline()
        if transid is not None:
            d.printline(f"\tTransaction {transid}")
            d.printline()
        if user:
            d.printline(f"\t{user}")
            d.printline()
        d.printline(f"\tFood order {number}", colour=1, emph=1)
        d.printline()
        d.printline(f"\t{ui.formattime(datetime.datetime.now())}")
        d.printline()
        tot = zero
        for item in ol:
            d.printline(f"{item.ltext}\t\t{item.rtext}")
            tot += item.price
        if print_total:
            d.printline(f"\t\tTotal {tillconfig.fc(tot)}", emph=1)
        d.printline()
        d.printline(f"\tFood order {number}", colour=1, emph=1)
        if tablenumber is not None:
            d.printline()
            d.printline(f"\tTable number {tablenumber}", colour=1, emph=1)
        if verbose:
            d.printline()
            d.printline(f"\t{footer}")
        else:
            d.printline()
            d.printline()


class tablenumber(ui.dismisspopup):
    """Request a table number and call a function with it.
    """
    def __init__(self, func):
        super().__init__(5, 20, title="Table number",
                         dismiss=keyboard.K_CLEAR,
                         colour=ui.colour_line)
        self.addstr(2, 2, "Table number:")
        self.numberfield = ui.editfield(
            2, 16, 5, keymap={keyboard.K_CASH: (self.enter, None)})
        self.func = func
        self.numberfield.focus()

    def enter(self):
        self.dismiss()
        self.func(self.numberfield.f)

class edititem(ui.dismisspopup):
    """Allow the user to edit the text of a food order item.
    """
    def __init__(self, item, func):
        super().__init__(5, 66, title="Edit line",
                         dismiss=keyboard.K_CLEAR,
                         colour=ui.colour_line)
        self.addstr(2, 2, "Edit this line:")
        self.linefield = ui.editfield(3, 2, 62, f=item.name, flen=240,
                                      keymap={keyboard.K_CASH: (self.enter, None)})
        self.func = func
        self.item = item
        self.linefield.focus()

    def enter(self):
        if len(self.linefield.f) > 0:
            self.item.update(self.linefield.f, self.item.price)
        self.dismiss()
        self.func()

class popup(user.permission_checked, ui.basicpopup):
    """Ask the user for a food order
    """
    permission_required = ('kitchen-order', 'Send an order to the kitchen')
    menu_hash = None
    menu_module = None

    def __init__(self, func, transid, menuurl, kitchenprinters,
                 ordernumberfunc=td.foodorder_ticket):
        self.kitchenprinters = kitchenprinters
        g = None
        with ui.exception_guard("reading the menu"):
            f = urllib.request.urlopen(menuurl)
            g = f.read()
            f.close()
        if not g:
            return
        hash = hashlib.sha1(g).hexdigest()
        if hash != self.menu_hash:
            log.debug("creating new menu module - oldhash %s, newhash %s",
                      self.menu_hash, hash)
            try:
                self.__class__.menu_module = ModuleType("foodmenu")
                exec(g, self.menu_module.__dict__)
                self.__class__.menu_hash = hash
            except:
                self.__class__.menu_hash = None
                self.__class__.menu_module = None
                ui.popup_exception("There is a problem with the menu")
                return
        foodmenu = self.menu_module
        if "menu" not in foodmenu.__dict__:
            ui.infopopup(["The menu file was read succesfully, but did not "
                          "contain a menu definition."],
                         title="No menu defined")
            return
        if "footer" not in foodmenu.__dict__:
            ui.infopopup(["The recipt footer definition is missing from "
                          "the menu file."], title="Footer missing")
            return
        if "dept" not in foodmenu.__dict__:
            ui.infopopup(["The department for food is missing from the "
                          "menu file."], title="Department missing")
            return
        self.footer = foodmenu.footer
        self.dept = foodmenu.dept
        self.print_total = foodmenu.__dict__.get("print_total", True)
        self.func = func
        self.transid = transid
        self.ordernumberfunc = ordernumberfunc
        self.h = 20
        self.w = 64
        kpprob = self._kitchenprinter_problem()
        rpprob = printer.driver.offline()
        if kpprob and rpprob:
            ui.infopopup(
                ["Both the kitchen printer and receipt printer report "
                 "problems.  You will not be able to print a food order "
                 "until these are fixed.", "",
                 f"Kitchen printer problem: {kpprob}",
                 f"Receipt printer problem: {rpprob}"],
                title="Printer problems")
            return
        super().__init__(self.h, self.w, title="Food Order",
                         colour=ui.colour_input)
        self.addstr(self.h - 1, 3, "Clear: abandon order   Print: finish   "
                    "Cancel:  delete item")
        # Split the top level menu into lines for display, and add the
        # options to the keymap
        possible_keys = [
            "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "00", "."]
        # If we have more options than keys, split them into a submenu.
        if len(foodmenu.menu) > len(possible_keys):
            menu = foodmenu.menu[:len(possible_keys) - 1] + \
                [("More...", simplemenu(foodmenu.menu[len(possible_keys) - 1:]))]
        else:
            menu = foodmenu.menu
        tlm = [""]
        for i in menu:
            key = possible_keys.pop(0)
            label = str(key)
            ls = f"{label}: {i[0]}"
            trial = f"{tlm[-1]}{('','  ')[len(tlm[-1]) > 0]}{ls}"
            if len(trial) > self.w - 4:
                tlm.append(ls)
            else:
                tlm[-1] = trial
            self.keymap[key] = (handle_option, (self.insert_item, i), False)
        maxy = self.h - len(tlm) - 2
        y = maxy + 1
        for i in tlm:
            self.addstr(y, 2, i)
            y = y + 1
        self.ml = [] # list of chosen items
        self.order = ui.scrollable(2, 2, self.w - 4, maxy - 1, self.ml,
                                   lastline=ui.emptyline())
        self.order.focus()
        if kpprob:
            ui.infopopup(
                ["The kitchen printer might not be connected or "
                 "turned on.  Please check it!", "",
                 "You can continue anyway if you like; if the kitchen "
                 "printer isn't working when you try to print the "
                 "order then their copy will be printed on the "
                 "receipt printer.", "",
                 f"The kitchen printer says: {kpprob}"],
                title="No connection to kitchen printer")
        if rpprob:
            ui.infopopup(
                ["The receipt printer is reporting a problem.  Please fix it "
                 "before trying to print the order.", "",
                 f"The problem is: {rpprob}"],
                title="Receipt printer problem")

    def insert_item(self, item):
        self.unsaved_data = "food order"
        self.ml.insert(self.order.cursor, item)
        self.order.cursor_down()
        self.order.redraw()

    def duplicate_item(self):
        if len(self.ml) == 0:
            return
        if self.order.cursor >= len(self.ml):
            self.insert_item(self.ml[-1].copy())
        else:
            self.insert_item(self.ml[self.order.cursor].copy())

    def edit_item(self):
        if len(self.ml) == 0:
            return
        if self.order.cursor_at_end():
            return
        edititem(self.ml[self.order.cursor], self.order.redraw)

    def delete_item(self):
        """Delete the item under the cursor.

        If there is no item under the cursor, delete the last item.
        The cursor stays in the same place.
        """
        if len(self.ml) == 0:
            return # Nothing to delete
        if self.order.cursor_at_end():
            self.ml.pop()
            self.order.cursor_up()
        else:
            del self.ml[self.order.cursor]
        self.order.redraw()

    def printkey(self):
        if len(self.ml) == 0:
            ui.infopopup(["You haven't entered an order yet!"], title="Error")
            return
        tablenumber(self.finish)

    def finish(self, tablenumber):
        # Check on the printer before we do any work...
        rpprob = printer.driver.offline()
        if rpprob:
            ui.infopopup(
                ["The receipt printer is reporting a problem.  Please fix it "
                 "before trying to print the order.", "",
                 f"The problem is: {rpprob}"],
                title="Receipt printer problem")
            return
        tot = sum((x.price for x in self.ml), zero)
        number = self.ordernumberfunc()
        # We need to prepare a list of (dept, text, items, amount)
        # tuples for the register.  We enter these into the register
        # before printing, so that we can avoid printing if there is a
        # register problem.
        rl = [(self.dept if x.dept is None else x.dept, x.name,
               1 if x.price >= 0 else -1, x.price if x.price >= 0 else -x.price)
              for x in self.ml]
        if tablenumber:
            rl.insert(0, (self.dept, f"Food order {number} (table {tablenumber}):",
                          1, zero))
        else:
            rl.insert(0, (self.dept, f"Food order {number}:", 1, zero))
        r = self.func(rl) # Return values: True=success; string or None=failure

        # If r is None then a window will have been popped up telling the
        # user what's happened to their transaction.  It will have popped
        # up on top of us; we can't do anything else at this point other than
        # exit and let the user try again.
        if r == None:
            return
        self.dismiss()
        if r == True:
            user = ui.current_user()
            with ui.exception_guard("printing the customer copy"):
                print_food_order(printer.driver, number, self.ml,
                                 verbose=True, tablenumber=tablenumber,
                                 footer=self.footer, transid=self.transid,
                                 print_total=self.print_total)
            try:
                for kp in self.kitchenprinters:
                    print_food_order(
                        kp, number, self.ml,
                        verbose=False, tablenumber=tablenumber,
                        footer=self.footer, transid=self.transid,
                        user=user.shortname if user else None)
            except:
                e = traceback.format_exception_only(
                    sys.exc_info()[0], sys.exc_info()[1])
                try:
                    print_food_order(
                        printer.driver, number, self.ml,
                        verbose=False, tablenumber=tablenumber,
                        footer=self.footer, transid=self.transid,
                        user=user.shortname if user else None)
                except:
                    pass
                ui.infopopup(
                    ["There was a problem sending the order to the "
                     "printer in the kitchen, so the kitchen copy has been "
                     "printed here.  You must now take it to the kitchen "
                     "so that they can make it.  Check that the printer "
                     "in the kitchen has paper, is turned on, and is plugged "
                     "in to the network.", "", "The error message from the "
                     "printer is:"] + e, title="Kitchen printer error")
                return
        else:
            if r:
                ui.infopopup([r], title="Error")

    def _kitchenprinter_problem(self):
        for kp in self.kitchenprinters:
            x = kp.offline()
            if x:
                return x

    def keypress(self, k):
        if k == keyboard.K_CLEAR:
            # Maybe ask for confirmation?
            self.dismiss()
        elif k == keyboard.K_CANCEL:
            self.delete_item()
        elif k == keyboard.K_QUANTITY:
            self.duplicate_item()
        elif k == keyboard.K_PRINT:
            self.printkey()
        elif k == keyboard.K_CASH:
            self.edit_item()
        else:
            super().keypress(k)

class message(user.permission_checked, ui.dismisspopup):
    """Send a printed message to the kitchen.
    """
    permission_required = ('kitchen-message','Send a message to the kitchen')

    def __init__(self, kitchenprinters):
        self.kitchenprinters = kitchenprinters
        problem = self._kitchenprinter_problem()
        if problem:
            ui.infopopup(["There is a problem with the kitchen printer:", "",
                          problem], title="Kitchen printer problem")
            return
        ui.dismisspopup.__init__(self, 6, 78, title="Message to kitchen",
                                 colour=ui.colour_input)
        self.addstr(2, 2, "Order number:")
        self.onfield = ui.editfield(2, 16, 5, keymap={
                keyboard.K_CLEAR: (self.dismiss, None)})
        self.addstr(2, 23, "(may be blank)")
        self.addstr(3, 2, "     Message:")
        self.messagefield = ui.editfield(
            3, 16, 60, flen=160,
            keymap={keyboard.K_CASH: (self.finish, None)})
        ui.map_fieldlist([self.onfield, self.messagefield])
        self.onfield.focus()
        self.unsaved_data = "message to kitchen"

    def _kitchenprinter_problem(self):
        for kp in self.kitchenprinters:
            x = kp.offline()
            if x:
                return x

    def finish(self):
        if not self.onfield.f and not self.messagefield.f:
            return
        problem = self._kitchenprinter_problem()
        if problem:
            ui.infopopup(["There is a problem with the kitchen printer:", "",
                          problem], title="Kitchen printer problem")
            return
        self.dismiss()
        with ui.exception_guard("printing the message in the kitchen"):
            for kp in self.kitchenprinters:
                with kp as d:
                    if self.onfield.f:
                        d.printline(
                            "\tMessage about order {}".format(self.onfield.f),
                            colour=1, emph=1)
                    else:
                        d.printline("\tMessage", colour=1, emph=1)
                    d.printline()
                    d.printline("\t%s" % ui.formattime(datetime.datetime.now()))
                    d.printline()
                    user = ui.current_user()
                    if user:
                        d.printline("\t{}".format(user.shortname))
                        d.printline()
                    if self.messagefield.f:
                        d.printline("\t{}".format(self.messagefield.f))
                        d.printline()
                    d.printline()
            ui.infopopup(["The message has been printed in the kitchen."],
                         title="Message sent",
                         colour=ui.colour_info, dismiss=keyboard.K_CASH)

class FoodOrderPlugin(register.RegisterPlugin):
    """Create an instance of this plugin to enable food ordering
    """
    def __init__(self, menuurl, printers, order_key, message_key):
        self._menuurl = menuurl
        self._printers = printers
        self._order_key = order_key
        self._message_key = message_key
        for p in printers:
            lockscreen.CheckPrinter("Kitchen printer", p)

    def keypress(self, reg, k):
        if k == self._order_key:
            trans = reg.get_open_trans()
            if trans:
                if reg.transaction_locked:
                    reg.transaction_lock_popup()
                else:
                    popup(reg.deptlines, trans.id, self._menuurl,
                          self._printers)
            return True
        elif k == self._message_key:
            message(self._printers)
            return True
