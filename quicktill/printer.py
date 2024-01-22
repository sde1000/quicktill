from . import td, ui, tillconfig, payment
from decimal import Decimal
from .models import Delivery, VatBand, Business, Transaction, PayType
from .models import penny, Session
from . import pdrivers
from . import config

import datetime
now = datetime.datetime.now

# Do we print check digits on stock labels?
checkdigit_print = config.BooleanConfigItem(
    'core:checkdigit_print', False, display_name="Print check digits?",
    description="Should check digits be printed on stock labels?")


# All of these functions assume there's a database session in td.s
# This should be the case if called during a keypress!  If being used
# in any other context, use with td.orm_session(): around the call.

def print_receipt(printer, transid):
    trans = td.s.query(Transaction).get(transid)
    if trans is None:
        return
    if not trans.lines:
        return
    with printer as d:
        d.printline(f"\t{tillconfig.pubname}", emph=1)
        for i in tillconfig.pubaddr().splitlines():
            d.printline(f"\t{i}", colour=1)
        d.printline(f"\tTel. {tillconfig.pubnumber}")
        d.printline()
        bandtotals = {}
        for tl in trans.lines:
            bandtotals[tl.department.vatband] = bandtotals.get(
                tl.department.vatband, Decimal("0.00")) + tl.total
        for tl in trans.lines:
            left = tl.description
            right = tl.regtotal(tillconfig.currency())
            if len(bandtotals) > 1 and trans.closed:
                d.printline(
                    f"{left}\t\t{right} {tl.department.vatband}",
                    font=1)
            else:
                d.printline(f"{left}\t\t{right}", font=1)
        totalpad = "  " if len(bandtotals) > 1 else ""
        d.printline(
            f"\t\tSubtotal {tillconfig.fc(trans.total)}{totalpad}",
            colour=1, emph=1)
        for p in trans.payments:
            pl = payment.pline(p)
            d.printline(f"\t\t{pl.text}{totalpad}")
        d.printline("")
        if not trans.closed:
            d.printline("\tThis is not a VAT receipt", colour=1, emph=1)
            d.printline(f"\tTransaction number {trans.id}")
        else:
            # We have a list of VAT bands; we need to look up rate and
            # business information for each of them.  Once we have the
            # list of businesses, we can print out a section per
            # business.  In each section, show the business name and
            # address, VAT number, and then for each VAT band the net
            # amount, VAT and total.

            # Keys are business IDs, values are (band,rate) tuples
            businesses = {}
            for i in list(bandtotals.keys()):
                vr = td.s.query(VatBand).get(i).at(trans.session.date)
                businesses.setdefault(vr.business.id, []).append((i, vr.rate))
            for i in list(businesses.keys()):
                business = td.s.query(Business).get(i)
                bands = businesses[i]
                # Print the business info
                d.printline(f"\t{business.name}")
                # The business address may be stored in the database
                # with either the string "\n" (legacy) or a newline
                # character (current) to separate the lines.
                if "\\n" in business.address:
                    addrlines = business.address.split("\\n")
                else:
                    addrlines = business.address.splitlines()
                for l in addrlines:
                    d.printline(f"\t{l}")
                d.printline()
                d.printline(f"VAT reg no. {business.vatno}")
                for band, rate in bands:
                    # Print the band, amount ex VAT, amount inc VAT, gross
                    gross = bandtotals[band]
                    net = (
                        gross / ((rate / Decimal("100.0")) + Decimal("1.0")))\
                        .quantize(penny)
                    vat = gross - net
                    d.printline(
                        f"{band}: {tillconfig.fc(net)} net, "
                        f"{tillconfig.fc(vat)} VAT @ {rate:0.1f}%\t\t"
                        f"Total {tillconfig.fc(gross)}", font=1)
                d.printline("")

            for p in trans.payments:
                p.paytype.driver.receipt_details(d, p)

            d.printline(f"\tReceipt number {trans.id}")

        d.printline(f"\t{ui.formatdate(trans.session.date)}")


def print_sessioncountup(printer, sessionid):
    s = td.s.query(Session).get(sessionid)
    if s is None:
        return
    with printer as d:
        d.printline(f"\t{tillconfig.pubname}", emph=1)
        d.printline(f"\tSession {s.id}", colour=1)
        d.printline(f"\t{ui.formatdate(s.date)}", colour=1)
        d.printline(f"Started {ui.formattime(s.starttime)}")
        d.printline(f"  Ended {ui.formattime(s.endtime)}")
        d.printline()
        d.printline("Amounts registered:")
        for paytype, total in s.payment_totals:
            d.printline(f"{paytype.description}: {tillconfig.fc(total)}")
        d.printline()
        # Now go through the current payment methods printing out their
        # input fields, with countup totals if necessary
        d.printline("", underline=1)
        for pm in td.s.query(PayType)\
                      .filter(PayType.mode != "disabled")\
                      .order_by(PayType.order, PayType.paytype)\
                      .all():
            for name, validator, print_fields in pm.driver.total_fields:
                if print_fields:
                    d.printline()
                    for i in print_fields:
                        d.printline(f"{i:>10}")
                        d.printline()
                    d.printline("", underline=1)
                if len(pm.driver.total_fields) > 1:
                    d.printline(f"{pm.description} {name}",
                                colour=1, emph=1)
                else:
                    d.printline(pm.description, colour=1, emph=1)
                d.printline()
                d.printline("", underline=1)
        d.printline("Enter totals into till using")
        d.printline("management menu option 1,3.")


def print_sessiontotals(printer, sessionid):
    """Print a session totals report given a Session id.
    """
    s = td.s.query(Session).get(sessionid)
    if s is None:
        return
    printtime = ui.formattime(now())
    depts = s.dept_totals
    # Let's use the payment type as the dict key
    till_totals = dict(s.payment_totals)
    actual_totals = dict((x.paytype, x.amount) for x in s.actual_totals)

    with printer as d:
        d.printline(f"\t{tillconfig.pubname}", emph=1)
        d.printline(f"\tSession {s.id}", colour=1)
        d.printline(f"\t{ui.formatdate(s.date)}", colour=1)
        d.printline(f"Started {ui.formattime(s.starttime)}")
        if s.endtime is None:
            d.printline("Session still in progress")
            d.printline(f"Printed {printtime}")
        else:
            d.printline(f"  Ended {ui.formattime(s.endtime)}")
        d.printline("Till total:\t\tActual total:")
        ttt = Decimal("0.00")
        att = Decimal("0.00")
        for pt in td.s.query(PayType)\
                      .order_by(PayType.order, PayType.paytype)\
                      .all():
            desc = pt.description
            if pt in till_totals:
                tt = tillconfig.fc(till_totals[pt])
                ttt = ttt + till_totals[pt]
            else:
                tt = ""
            if pt in actual_totals:
                at = tillconfig.fc(actual_totals[pt])
                att = att + actual_totals[pt]
            else:
                at = ""
            if tt or at:
                d.printline(f"{desc}: {tt}\t\t{at}")
        tt = tillconfig.fc(ttt)
        if att > Decimal("0.00"):
            at = tillconfig.fc(att)
        else:
            at = ""
        d.printline(f"Total: {tt}\t\t{at}", colour=1, emph=1)
        d.printline()
        dt = Decimal("0.00")
        deptlen = max((len(str(dept.id)) for dept, total in depts), default=0)
        for dept, total in depts:
            d.printline(
                f"{dept.id:{deptlen}} {dept.description}"
                f"\t\t{tillconfig.fc(total)}")
            dt = dt + total
        d.printline(f"\t\tTotal: {tillconfig.fc(dt)}", colour=1, emph=1)
        d.printline()
        d.printline(f"\tPrinted {printtime}")


def print_deferred_payment_wrapper(printer, trans, paytype, amount, user_name):
    """Print a wrapper for a deferred payment

    Print a wrapper for money (cash, etc.) to be set aside to use
    towards paying a part-paid transaction in a future session.
    """
    with printer as d:
        for i in range(4):
            d.printline(f"\t{tillconfig.pubname}", emph=1)
            d.printline(f"\tDeferred transaction {trans.id}", emph=1)
            d.printline()
            d.printline(
                f"This is {tillconfig.fc(amount)} in "
                f"{paytype.description} to be used in part-payment "
                f"of transaction {trans.id} ({trans.notes}) when that "
                f"transaction is ready to be closed.")
            d.printline()
            d.printline(
                f"This part-paid transaction was deferred by {user_name} "
                f"at {datetime.datetime.now():%H:%M} on "
                f"{datetime.date.today()}.")
            d.printline()
            d.printline(
                f"Use this printout to wrap the {paytype.description} "
                "before putting it aside.")
            d.printline()
            d.printline()
            d.printline()
            d.printline()


def label_print_delivery(p, delivery):
    d = td.s.query(Delivery).get(delivery)
    stocklabel_print(p, d.items)


def stock_label(f, d):
    """Draw a stock label (d) on a PDF canvas (f).
    """
    width, height = f.getPageSize()
    fontsize = 12
    margin = 12
    pitch = fontsize + 2
    fontname = "Times-Roman"
    f.setFont(fontname, fontsize)

    def fits(s):
        sw = f.stringWidth(s, fontname, fontsize)
        return sw < (width - (2 * margin))

    s = d.stocktype.format()
    while len(s) > 10:
        sw = f.stringWidth(s, fontname, fontsize)
        if sw < (width - (2 * margin)):
            break
        s = d.stocktype.format(len(s) - 1)

    y = height - margin - fontsize
    f.drawCentredString(width / 2, y, s)
    y = y - pitch
    f.drawCentredString(width / 2, y, d.delivery.supplier.name)
    y = y - pitch
    f.drawCentredString(width / 2, y, ui.formatdate(d.delivery.date))
    y = y - pitch
    f.drawCentredString(width / 2, y, d.description)
    if checkdigit_print():
        y = y - pitch
        f.drawCentredString(width / 2, y, f"Check digits: {d.checkdigits}")
    f.setFont(fontname, y - margin)
    f.drawCentredString(width / 2, margin, str(d.id))
    f.showPage()


def stocklabel_print(p, sl):
    """Print stock labels for a list of stock numbers to the specified
    printer.
    """
    td.s.add_all(sl)
    with p as d:
        for sd in sl:
            stock_label(d, sd)


def print_restock_list(printer, rl):
    """
    Print a list of (stockline,stockmovement) tuples.
    A stockmovement tuple is (stockitem,fetchqty,newdisplayqty,qtyremain).

    We can't assume that any of these objects are in the current
    session.
    """
    with printer as d:
        d.printline(f"\t{tillconfig.pubname}", emph=1)
        d.printline("\tRe-stock list")
        d.printline(f"\tPrinted {ui.formattime(now())}")
        d.printline()
        for sl, sm in rl:
            td.s.add(sl)
            d.printline(f"{sl.name}:")
            d.printline(f"{sl.ondisplay}/{sl.capacity} displayed")
            for item, move, newdisplayqty, stockqty_after_move in sm:
                td.s.add(item)
                if move > 0:
                    d.printline(f" {move} from item {item.id} "
                                f"leaving {stockqty_after_move}")
                if move < 0:
                    d.printline(
                        f" {-move} to item {item.id} "
                        f"making {stockqty_after_move}",
                        colour=1)
        d.printline()
        d.printline("\tEnd of list")


def kickout(drawer):
    """Kick out the cash drawer.

    Returns True if successful.
    """
    with ui.exception_guard("kicking out the cash drawer",
                            title="Printer error"):
        try:
            drawer.kickout()
        except pdrivers.PrinterError as e:
            ui.infopopup([f"Could not kick out the cash drawer: {e.desc}"],
                         title="Printer problem")
            return False
    return True
