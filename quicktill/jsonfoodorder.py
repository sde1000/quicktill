import requests
import sys
import traceback
import datetime
import logging
from . import ui, keyboard, td, tillconfig, user
from .user import log as userlog
from . import lockscreen
from . import register
from .models import zero
from decimal import Decimal

log = logging.getLogger(__name__)

menu_keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]


class Menu:
    def __init__(self, d, allowable_departments):
        self.name = d.get('name', 'Unnamed menu')
        self.footer = d.get('footer', 'Thank you')
        self.sections = [Section(x, allowable_departments)
                         for x in d.get('sections', [])]
        self.sections = [x for x in self.sections if x.ok]


class Section:
    def __init__(self, d, allowable_departments):
        self.title = d.get('title', 'Untitled section')
        self.available = d.get('available', True)
        self.dishes = [Dish(x) for x in d.get('dishes', [])]
        self.dishes = [x for x in self.dishes if x.ok]
        if allowable_departments:
            self.dishes = [x for x in self.dishes
                           if x.department in allowable_departments]

    @property
    def ok(self):
        return self.available and self.dishes

    def select(self, dialog):
        menu = [(dish.name, dish.select, (dialog,)) for dish in self.dishes]
        ui.automenu(menu, spill="keymenu", title=self.title,
                    colour=ui.colour_line)


class Dish:
    def __init__(self, d):
        self.name = d.get('name', 'Unnamed dish')
        self.price = Decimal(d.get('price') or zero)
        self.placeholder = d.get('placeholder', False)
        self.available = d.get('available', False)
        self.department = d.get('department')
        self.option_groups = [OptionGroup(x)
                              for x in d.get('option_groups', [])]
        self.option_groups = [x for x in self.option_groups if x.ok]

    @property
    def ok(self):
        return self.available and not self.placeholder

    def options(self):
        return [opt for og in self.option_groups for opt in og.options]

    def price_with_options(self, options):
        return self.price + sum(opt.price * qty for opt, qty in options)

    def name_with_options(self, options, comment):
        d = self.name
        if options:
            d += f"; {', '.join(opt.name_with_qty(qty) for opt, qty in options)}"  # noqa: E501
        if comment:
            d += f". Comment: {comment}"
        return d

    def select(self, dialog):
        orderline(self).edit(dialog.insert_item)


class OptionGroup:
    def __init__(self, d):
        self.description = d.get('description', 'Unnamed option group')
        self.min_choices = d.get('min_choices', 0)
        self.max_choices = d.get('max_choices')
        self.available = d.get('available', True)
        self.options = [Option(x, self) for x in d.get('options', [])]
        self.options = [x for x in self.options if x.available]

    @property
    def ok(self):
        # NB an option group with no options is still valid and its
        # min_choices must still be respected!
        return self.available


class Option:
    def __init__(self, d, group):
        self.optiongroup = group
        self.name = d.get('name', 'Unnamed option')
        self.price = Decimal(d.get('price') or zero)
        self.max_allowed = d.get('max_allowed', 1)
        self.available = d.get('available', True)

    def name_with_qty(self, qty):
        return self.name if qty == 1 else f"{self.name} (×{qty})"


class optiongroup_selection:
    """Options chosen from an option group
    """
    def __init__(self, option_group):
        self.option_group = option_group
        self.o = []

    def options(self):
        # Return a list of (Option, qty)
        return [(opt, self.o.count(opt)) for opt in self.option_group.options
                if self.o.count(opt)]

    def valid(self):
        return len(self.o) >= self.option_group.min_choices

    def add_option(self, option):
        """Add an option to the group

        Return True if doing so had a visible effect
        """
        count = self.o.count(option)
        if count >= option.max_allowed:
            return False
        self.o.append(option)
        if self.option_group.max_choices \
           and len(self.o) > self.option_group.max_choices:
            removed = self.o.pop(0)
            return removed != option
        return True


class orderline(ui.lrline):
    def __init__(self, dish):
        super().__init__()
        self.dish = dish
        # Options stored as a list of (option, qty)
        self.options = []
        # Options stored as a list, in the order in which the user
        # selected them - only used by the editor
        self.option_selections = []
        self.comment = ""
        self.update()

    @property
    def price(self):
        return self.dish.price_with_options(self.options)

    @property
    def dept(self):
        return self.dish.department

    def update(self):
        self.ltext = self.dish.name_with_options(self.options, self.comment)
        self.rtext = tillconfig.fc(self.price) if self.price else ""
        super().update()

    def edit(self, func):
        orderline_dialog(self, func)

    def copy(self):
        ol = orderline(self.dish)
        ol.options = list(self.options)
        ol.option_selections = list(self.option_selections)
        ol.comment = self.comment
        ol.update()
        return ol


class orderline_dialog(ui.dismisspopup):
    def __init__(self, orderline, func):
        self.orderline = orderline
        self.func = func

        # List of all possible options; may be empty
        self.optionlist = orderline.dish.options()
        # List of options selected by the user, in order
        self.option_selections = list(orderline.option_selections)

        mh, mw = ui.rootwin.size()

        # Height: we need four lines for the "text entry" box at the
        # top, four lines for the top/bottom border, two lines for the
        # prompt (including one blank), one line for the
        # comment/scroll prompt
        h = 4 + 4 + 2 + 1

        available_height = mh - h

        if available_height < 2:
            ui.infopopup(["There is not enough screen height to display this "
                          "dialog."], title="Error")
            return

        # If there are any options, we need a blank line, plus one
        # line for each option key.
        self.option_index = 0  # how far have we scrolled through the options?
        if self.optionlist:
            display_options = min(len(menu_keys), len(self.optionlist))
            if display_options + 1 > available_height:
                display_options = available_height - 1
            self.menu_keys = menu_keys[:display_options]
            h += display_options + 1
        else:
            self.menu_keys = []

        # We could go wider. But would it look odd?
        self.w = 68
        km = {keyboard.K_CASH: (self.finish, None, False)}
        super().__init__(h, self.w, orderline.dish.name + " options",
                         colour=ui.colour_line, keymap=km)
        self.promptlabel = ui.label(7, 2, self.w - 14)
        self.pricelabel = ui.label(7, self.w - 12, 10, align=">")
        self.leftlabel = ui.label(h - 2, 2, 6, align="<")
        self.rightlabel = ui.label(h - 2, self.w - 8, 6, align=">")
        self.commentlabel = ui.label(
            h - 2, 8, self.w - 16, "Press 0 to add a comment", align="^")
        self.update_options()
        self.comment = orderline.comment
        self.draw_option_menu()
        self.redraw()

    def draw_option_menu(self):
        if not self.optionlist:
            return
        y = 9
        self.win.clear(y, 2, len(self.menu_keys), self.w - 4)
        for key, opt in zip(
                self.menu_keys, self.optionlist[self.option_index:]):
            self.win.drawstr(y, 2, 3, f"{key}: ", align=">")
            self.win.drawstr(y, 5, self.w - 7, opt.name)
            y += 1
        self.leftlabel.set("◀ More" if self.option_index > 0 else "")
        self.rightlabel.set(
            "More ▶"
            if self.option_index + len(self.menu_keys) < len(self.optionlist)
            else "")
        self.win.move(2, 2)

    def update_description(self):
        self.win.clear(2, 2, 4, self.w - 4, colour=ui.colour_line.reversed)
        self.win.wrapstr(2, 2, self.w - 4,
                         self.orderline.dish.name_with_options(
                             self.options, self.comment),
                         colour=ui.colour_line.reversed)
        self.win.move(2, 2)

    def update_options(self):
        # Recalculate self.options and self.options_valid from
        # self.option_selections
        ogs = {og: optiongroup_selection(og)
               for og in self.orderline.dish.option_groups}
        self.option_selections = [
            opt for opt in self.option_selections
            if ogs[opt.optiongroup].add_option(opt)]
        valid = [og.valid() for og in ogs.values()]
        self.options = [x for og in self.orderline.dish.option_groups
                        for x in ogs[og].options()]
        self.options_valid = not (False in valid)

    def redraw(self):
        self.update_description()
        p = self.orderline.dish.price_with_options(self.options)
        self.pricelabel.set(tillconfig.fc(p) if p else "")
        if self.options_valid:
            if self.optionlist:
                self.promptlabel.set(
                    "Choose options, and press Cash/Enter to confirm.")
            else:
                self.promptlabel.set(
                    "Press Cash/Enter to confirm.")
        else:
            self.promptlabel.set("Choose options from the list below.")
        self.win.move(2, 2)

    def finish(self):
        if not self.options_valid:
            return
        self.orderline.options = self.options
        self.orderline.option_selections = self.option_selections
        self.orderline.comment = self.comment
        self.orderline.update()
        self.dismiss()
        self.func(self.orderline)

    def update_comment(self, comment):
        self.comment = comment
        self.update_description()

    def keypress(self, k):
        if k == '0':
            editcomment(self.comment, self.orderline.dish.name,
                        self.update_comment)
        elif k == keyboard.K_RIGHT \
             and self.option_index + len(self.menu_keys) \
             < len(self.optionlist):  # noqa: E127
            self.option_index += len(self.menu_keys)
            self.draw_option_menu()
        elif k == keyboard.K_LEFT and self.option_index > 0:
            self.option_index -= len(self.menu_keys)
            self.draw_option_menu()
        elif k in self.menu_keys \
             and self.menu_keys.index(k) + self.option_index \
             < len(self.optionlist):  # noqa: E127
            self.option_selections.append(
                self.optionlist[self.menu_keys.index(k) + self.option_index])
            self.update_options()
            self.redraw()
        elif k == keyboard.K_CLEAR and self.option_selections:
            # Perform an "undo"...
            self.option_selections.pop(-1)
            self.update_options()
            self.redraw()
        else:
            super().keypress(k)


class editcomment(ui.dismisspopup):
    """Allow the user to edit the comment of an order line.
    """
    def __init__(self, comment, description, func):
        super().__init__(7, 66, title="Edit comment",
                         dismiss=keyboard.K_CLEAR,
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 50, f"Edit the comment for {description}:")
        self.commentfield = ui.editfield(
            4, 2, 62, f=comment, flen=240,
            keymap={keyboard.K_CASH: (self.enter, None)})
        self.func = func
        self.commentfield.focus()

    def enter(self):
        self.dismiss()
        self.func(self.commentfield.f)


class tablenumber(ui.dismisspopup):
    """Request a table number and call a function with it.
    """
    def __init__(self, func):
        super().__init__(5, 20, title="Table number",
                         dismiss=keyboard.K_CLEAR,
                         colour=ui.colour_line)
        self.win.drawstr(2, 2, 14, "Table number: ", align=">")
        self.numberfield = ui.editfield(
            2, 16, 5, keymap={keyboard.K_CASH: (self.enter, None)})
        self.func = func
        self.numberfield.focus()

    def enter(self):
        self.dismiss()
        self.func(self.numberfield.f)


def print_food_order(driver, number, ol, verbose=True, tablenumber=None,
                     footer="", transid=None, user=None):
    """This function prints a food order to the specified printer.
    """
    with driver as d:
        if verbose:
            d.printline(f"\t{tillconfig.pubname}", emph=1)
            for i in tillconfig.pubaddr().splitlines():
                d.printline(f"\t{i}", colour=1)
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
        for item in ol:
            d.printline(f"{item.dish.name}\t\t{item.price}")
            for option, qty in item.options:
                for _ in range(qty):
                    d.printline(f"  {option.name}")
            if item.comment:
                d.printline(f"  Comment: {item.comment}")
        d.printline()
        d.printline(f"\tFood order {number}", colour=1, emph=1)
        if tablenumber is not None:
            d.printline()
            d.printline(f"\tTable {tablenumber}", colour=1, emph=1)
        if verbose:
            d.printline()
            d.printline(f"\t{footer}")
        else:
            d.printline()
            d.printline()


class popup(user.permission_checked, ui.basicpopup):
    """Take a food order from the user and print it

    Call func with a list of (dept, text, items, amount) tuples
    """
    permission_required = ('kitchen-order', 'Send an order to the kitchen')

    def __init__(self, func, transid, menuurl, kitchenprinters,
                 message_department, allowable_departments,
                 ordernumberfunc=td.foodorder_ticket,
                 requests_session=None):
        if not tillconfig.receipt_printer:
            ui.infopopup(["This till doesn't have a receipt printer, and "
                          "cannot be used to take food orders. Use a "
                          "till with a printer instead."], title="Error")
            return
        self.kitchenprinters = kitchenprinters
        self.message_department = message_department
        if not requests_session:
            requests_session = requests
        try:
            r = requests_session.get(menuurl, timeout=3)
            if r.status_code != 200:
                ui.infopopup(["Could not read the menu: web request returned "
                              f"status {r.status_code}."],
                             title="Could not read menu")
                return
        except requests.exceptions.ConnectionError:
            ui.infopopup(["Unable to connect to the server to read the menu."],
                         title="Could not read menu")
            return
        except requests.exceptions.ReadTimeout:
            ui.infopopup(["The server did not send the menu quickly enough."],
                         title="Could not read menu")
            return
        self.menu = Menu(r.json(), allowable_departments)
        self.func = func
        self.transid = transid
        self.ordernumberfunc = ordernumberfunc
        self.h = 20
        self.w = 64
        kpprob = self._kitchenprinter_problem()
        rpprob = tillconfig.receipt_printer.offline()
        if kpprob and rpprob:
            ui.infopopup(
                ["Both the kitchen printer and receipt printer report "
                 "problems.  You will not be able to print a food order "
                 "until these are fixed.", "",
                 f"Kitchen printer problem: {kpprob}",
                 f"Receipt printer problem: {rpprob}"],
                title="Printer problems")
            return
        super().__init__(self.h, self.w, title=self.menu.name,
                         colour=ui.colour_input)
        self.win.bordertext("Clear: abandon order", "L<")
        self.win.bordertext("Print: finish", "L^")
        self.win.bordertext("Cancel: delete item", "L>")
        # Split the top level menu into lines for display, and add the
        # options to the keymap
        menu = [(s.title, s.select, (self,)) for s in self.menu.sections]
        # If we have more options than keys, split them into a submenu.
        if len(self.menu.sections) > len(menu_keys):
            menu = menu[:len(menu_keys) - 1] + \
                [("More...", ui.automenu(menu[len(menu_keys) - 1:]))]
        menutext = '  '.join(f"{key}: {i[0]}" for key, i in zip(
            menu_keys, menu))
        for key, i in zip(menu_keys, menu):
            self.keymap[key] = i[1:]
        menuheight = self.win.wrapstr(
            0, 0, self.w - 4, menutext, display=False)
        self.win.wrapstr(self.h - menuheight - 1, 2, self.w - 4, menutext)
        self.ml = []  # list of chosen items
        self.order = ui.scrollable(
            2, 2, self.w - 4, self.h - menuheight - 4, self.ml,
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
        self.ml[self.order.cursor].edit(self.update_item)

    def update_item(self, item):
        self.order.redraw()

    def delete_item(self):
        """Delete the item under the cursor.

        If there is no item under the cursor, delete the last item.
        The cursor stays in the same place.
        """
        if len(self.ml) == 0:
            return  # Nothing to delete
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
        rpprob = tillconfig.receipt_printer.offline()
        if rpprob:
            ui.infopopup(
                ["The receipt printer is reporting a problem.  Please fix it "
                 "before trying to print the order.", "",
                 f"The problem is: {rpprob}"],
                title="Receipt printer problem")
            return
        number = self.ordernumberfunc()
        # We need to prepare a list of (dept, text, items, amount)
        # tuples for the register.  We enter these into the register
        # before printing, so that we can avoid printing if there is a
        # register problem.
        rl = [(x.dish.department, x.ltext, 1, x.price) for x in self.ml]
        if tablenumber:
            rl.insert(0, (self.message_department,
                          f"Food order {number} (table {tablenumber}):",
                          1, zero))
        else:
            rl.insert(0, (self.message_department,
                          f"Food order {number}:", 1, zero))
        # Return values: True=success; string or None=failure
        r = self.func(rl)

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
                print_food_order(tillconfig.receipt_printer, number, self.ml,
                                 verbose=True, tablenumber=tablenumber,
                                 footer=self.menu.footer, transid=self.transid)
            try:
                for kp in self.kitchenprinters:
                    print_food_order(
                        kp, number, self.ml,
                        verbose=False, tablenumber=tablenumber,
                        footer=self.menu.footer, transid=self.transid,
                        user=user.shortname)
            except Exception:
                e = traceback.format_exception_only(
                    sys.exc_info()[0], sys.exc_info()[1])
                try:
                    print_food_order(
                        tillconfig.receipt_printer, number, self.ml,
                        verbose=False, tablenumber=tablenumber,
                        footer=self.menu.footer, transid=self.transid,
                        user=user.shortname)
                except Exception:
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
    permission_required = ('kitchen-message', 'Send a message to the kitchen')

    def __init__(self, kitchenprinters):
        self.kitchenprinters = kitchenprinters
        problem = self._kitchenprinter_problem()
        if problem:
            ui.infopopup(["There is a problem with the kitchen printer:", "",
                          problem], title="Kitchen printer problem")
            return
        super().__init__(6, 78, title="Message to kitchen",
                         colour=ui.colour_input)
        self.win.drawstr(2, 2, 14, "Order number: ", align=">")
        self.onfield = ui.editfield(2, 16, 5, keymap={
            keyboard.K_CLEAR: (self.dismiss, None)})
        self.win.drawstr(2, 23, 14, "(may be blank)")
        self.win.drawstr(3, 2, 14, "Message: ", align=">")
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
                            f"\tMessage about order {self.onfield.f}",
                            colour=1, emph=1)
                    else:
                        d.printline("\tMessage", colour=1, emph=1)
                    d.printline()
                    d.printline(f"\t{ui.formattime(datetime.datetime.now())}")
                    d.printline()
                    user = ui.current_user()
                    if user:
                        d.printline(f"\t{user.shortname}")
                        d.printline()
                    if self.messagefield.f:
                        d.printline(f"\t{self.messagefield.f}")
                        d.printline()
                    d.printline()
            ui.infopopup(["The message has been printed in the kitchen."],
                         title="Message sent",
                         colour=ui.colour_info, dismiss=keyboard.K_CASH)
            if self.onfield.f:
                userlog(f"Message sent to kitchen about table "
                        f"{self.onfield.f}: {self.messagefield.f}")
            else:
                userlog(f"Message sent to kitchen: {self.messagefield.f}")


class FoodOrderPlugin(register.RegisterPlugin):
    """Create an instance of this plugin to enable food ordering

    printers is a list of printers to be treated as printing the
    "kitchen copy" of food orders.  The local receipt printer will
    always be used for the customer copy.

    message_department is the department number to use for zero-price
    message transaction lines, eg. the one stating the order number
    and table number.

    allowable_departments, if set, is a list of departments that are
    permitted in food orders; dishes with other departments will be
    filtered out of the menu when it is loaded.
    """
    def __init__(self, menuurl=None, printers=[],
                 order_key=None, message_key=None,
                 message_department=None, allowable_departments=None):
        self._menuurl = menuurl
        self._printers = printers
        self._order_key = order_key
        self._message_key = message_key
        self._message_department = message_department
        self._allowable_departments = allowable_departments
        if not menuurl:
            raise Exception("FoodOrderPlugin: you must specify menuurl")
        if message_department is None:
            raise Exception("FoodOrderPlugin: you must specify "
                            "message_department")
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
                          self._printers, self._message_department,
                          self._allowable_departments)
            return True
        elif k == self._message_key:
            message(self._printers)
            return True
