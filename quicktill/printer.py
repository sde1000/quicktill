from . import td, ui, tillconfig, payment
from decimal import Decimal
from .models import Delivery, VatBand, Business, Transline, Transaction
from .models import zero,penny
from . import pdrivers

import datetime
now = datetime.datetime.now

# XXX should be in tillconfig?
driver = None
labelprinters = []

# All of these functions assume there's a database session in td.s
# This should be the case if called during a keypress!  If being used
# in any other context, use with td.orm_session(): around the call.

def print_receipt(transid):
    trans = td.s.query(Transaction).get(transid)
    if trans is None:
        return
    if not trans.lines:
        return
    with driver as d:
        d.printline("\t{}".format(tillconfig.pubname), emph=1)
        for i in tillconfig.pubaddr:
            d.printline("\t{}".format(i), colour=1)
        d.printline("\tTel. {}".format(tillconfig.pubnumber))
        d.printline()
        bandtotals = {}
        for tl in trans.lines:
            bandtotals[tl.department.vatband] = bandtotals.get(
                tl.department.vatband, Decimal("0.00")) + tl.total
        for tl in trans.lines:
            left = tl.description
            right = tl.regtotal(tillconfig.currency)
            if len(bandtotals) > 1 and trans.closed:
                d.printline(
                    "{}\t\t{} {}".format(left, right, tl.department.vatband),
                    font=1)
            else:
                d.printline("{}\t\t{}".format(left, right), font=1)
        totalpad = "  " if len(bandtotals) > 1 else ""
        d.printline("\t\tSubtotal {}{}".format(tillconfig.fc(trans.total), totalpad),
                    colour=1, emph=1)
        for p in trans.payments:
            pl = payment.pline(p)
            d.printline("\t\t{}{}".format(pl.text, totalpad))
        d.printline("")
        if not trans.closed:
            d.printline("\tThis is not a VAT receipt", colour=1, emph=1)
            d.printline("\tTransaction number {}".format(trans.id))
        else:
            # We have a list of VAT bands; we need to look up rate and
            # business information for each of them.  Once we have the
            # list of businesses, we can print out a section per
            # business.  In each section, show the business name and
            # address, VAT number, and then for each VAT band the net
            # amount, VAT and total.
            businesses = {} # Keys are business IDs, values are (band,rate) tuples
            for i in list(bandtotals.keys()):
                vr = td.s.query(VatBand).get(i).at(trans.session.date)
                businesses.setdefault(vr.business.id, []).append((i, vr.rate))
            for i in list(businesses.keys()):
                business = td.s.query(Business).get(i)
                bands = businesses[i]
                # Print the business info
                d.printline("\t{}".format(business.name))
                # The business address may be stored in the database
                # with either the string "\n" (legacy) or a newline
                # character (current) to separate the lines.
                if "\\n" in business.address:
                    addrlines = business.address.split("\\n")
                else:
                    addrlines = business.address.splitlines()
                for l in addrlines:
                    d.printline("\t{}".format(l))
                d.printline()
                d.printline("VAT reg no. {}".format(business.vatno))
                for band, rate in bands:
                    # Print the band, amount ex VAT, amount inc VAT, gross
                    gross = bandtotals[band]
                    net = (gross / ((rate / Decimal("100.0")) + Decimal("1.0")))\
                          .quantize(penny)
                    vat = gross - net
                    d.printline("{}: {} net, {} VAT @ {:0.1f}%\t\tTotal {}".format(
                            band, tillconfig.fc(net), tillconfig.fc(vat), rate,
                            tillconfig.fc(gross)), font=1)
                d.printline("")
            d.printline("\tReceipt number {}".format(trans.id))
        d.printline("\t{}".format(ui.formatdate(trans.session.date)))

def print_sessioncountup(s):
    with driver as d:
        d.printline("\t%s"%tillconfig.pubname,emph=1)
        d.printline("\tSession %d"%s.id,colour=1)
        d.printline("\t%s"%ui.formatdate(s.date),colour=1)
        d.printline("Started %s"%ui.formattime(s.starttime))
        d.printline("  Ended %s"%ui.formattime(s.endtime))
        d.printline()
        d.printline("Amounts registered:")
        for paytype, total in s.payment_totals:
            d.printline("%s: %s" % (paytype.description, tillconfig.fc(total)))
        d.printline()
        # Now go through the current payment methods printing out their
        # input fields, with countup totals if necessary
        d.printline("", underline=1)
        for pm in tillconfig.all_payment_methods:
            for name, validator, print_fields in pm.total_fields:
                for i in print_fields if print_fields else []:
                    d.printline("{:>10}".format(i))
                    d.printline()
                if print_fields:
                    d.printline("", underline=1)
                if len(pm.total_fields)>1:
                    d.printline("{} {}".format(pm.description, name),
                                colour=1, emph=1)
                else:
                    d.printline(pm.description, colour=1, emph=1)
                d.printline()
                d.printline("", underline=1)
        d.printline("Enter totals into till using")
        d.printline("management menu option 1,3.")

def print_sessiontotals(s):
    """Print a session totals report given a Session object.
    """
    td.s.add(s)
    depts = s.dept_totals
    # Let's use the payment type (String(8)) as the dict key
    till_totals = dict((x.paytype, y) for x, y in s.payment_totals)
    actual_totals = dict((x.paytype_id, x.amount) for x in s.actual_totals)

    # Use the configured list of payment types so that we print in a
    # consistent order; any payment types not in this list are
    # appended to it and printed last, because they will be for
    # historical payment types not currently configured
    all_paytypes = list(set(list(till_totals.keys()) +
                            list(actual_totals.keys())))
    pms = list(tillconfig.all_payment_methods)
    pts = [pm.paytype for pm in pms]

    for pt in all_paytypes:
        if pt not in pts:
            pms.append(payment.methods[pt])

    with driver as d:
        d.printline("\t%s" % tillconfig.pubname, emph=1)
        d.printline("\tSession %d" % s.id, colour=1)
        d.printline("\t%s" % ui.formatdate(s.date), colour=1)
        d.printline("Started %s" % ui.formattime(s.starttime))
        if s.endtime is None:
            d.printline("Session still in progress")
            d.printline("Printed %s" % ui.formattime(now()))
        else:
            d.printline("  Ended %s" % ui.formattime(s.endtime))
        d.printline("Till total:\t\tActual total:")
        ttt = Decimal("0.00")
        att = Decimal("0.00")
        for pm in pms:
            desc = pm.description
            pt = pm.paytype
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
                d.printline("%s: %s\t\t%s" % (desc, tt, at))
        if len(pms) > 1:
            tt = tillconfig.fc(ttt)
            if att > Decimal("0.00"):
                at = tillconfig.fc(att)
            else:
                at = ""
            d.printline("Total: %s\t\t%s" % (tt, at), colour=1, emph=1)
        d.printline()
        dt = Decimal("0.00")
        for dept, total in depts:
            d.printline("%2d %s\t\t%s" % (dept.id, dept.description,
                                          tillconfig.fc(total)))
            dt = dt + total
        d.printline("\t\tTotal: %s" % tillconfig.fc(dt), colour=1, emph=1)
        d.printline()
        d.printline("\tPrinted %s" % ui.formattime(now()))

def label_print_delivery(p,delivery):
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
        s = d.stocktype.format(len(s)-1)

    y = height - margin - fontsize
    f.drawCentredString(width / 2, y, s)
    y = y - pitch
    f.drawCentredString(width / 2, y, d.delivery.supplier.name)
    y = y - pitch
    f.drawCentredString(width / 2, y, ui.formatdate(d.delivery.date))
    y = y - pitch
    f.drawCentredString(width / 2, y, d.description)
    if tillconfig.checkdigit_print:
        y = y - pitch
        f.drawCentredString(width / 2, y, "Check digits: %s" % (d.checkdigits,))
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

def print_restock_list(rl):
    """
    Print a list of (stockline,stockmovement) tuples.
    A stockmovement tuple is (stockitem,fetchqty,newdisplayqty,qtyremain).

    We can't assume that any of these objects are in the current
    session.
    """
    with driver as d:
        d.printline("\t%s" % tillconfig.pubname, emph=1)
        d.printline("\tRe-stock list")
        d.printline("\tPrinted %s" % ui.formattime(now()))
        d.printline()
        for sl, sm in rl:
            td.s.add(sl)
            d.printline("%s:" % sl.name)
            d.printline("%d/%d displayed" % (sl.ondisplay, sl.capacity))
            for item, move, newdisplayqty, stockqty_after_move in sm:
                td.s.add(item)
                if move > 0:
                    d.printline(" %d from item %d leaving %d" % (
                        move, item.id, stockqty_after_move))
                if move < 0:
                    d.printline(" %d to item %d making %d" % (
                        -move, item.id, stockqty_after_move), colour=1)
        d.printline()
        d.printline("\tEnd of list")

def kickout():
    """Kick out the cash drawer.

    Returns True if successful.
    """
    with ui.exception_guard("kicking out the cash drawer",
                            title="Printer error"):
        try:
            driver.kickout()
        except pdrivers.PrinterError as e:
            ui.infopopup(["Could not kick out the cash drawer: {}".format(
                e.desc)], title="Printer problem")
            return False
    return True
