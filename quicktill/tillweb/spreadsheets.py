# -*- coding: utf-8 -*-
from django.http import HttpResponse
from quicktill.models import *
from sqlalchemy.orm import undefer
from sqlalchemy.orm import contains_eager
from sqlalchemy.sql import select
from sqlalchemy.sql.expression import literal
from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TextProperties, ParagraphProperties
from odf.style import TableColumnProperties
from odf.text import P
from odf.table import Table, TableColumn, TableRow, TableCell
import odf.number as number

class Sheet:
    """A table in a spreadsheet"""

    _LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def __init__(self, name):
        self.name = name
        # Indexed by tuples of (col, row)
        self._contents = {}
        # Indexed by col
        self._columnstyles = {}

    def cell(self, col, row, contents):
        self._contents[(col, row)] = contents
        return contents

    def colstyle(self, col, style):
        self._columnstyles[col] = style

    def ref(self, col, row, scol=False, srow=False):
        """Reference to a cell.

        If scol is set then makes a specific reference to that column;
        if srow is set then makes a specific reference to that row.
        Otherwise makes a relative reference.
        """
        c = col + 1
        cv = []
        while c:
            c, r = divmod(c-1, len(self._LETTERS))
            cv[:0] = self._LETTERS[r]
        return "{}{}{}{}".format("$" if scol else "",
                                 "".join(cv),
                                 "$" if srow else "",
                                 row + 1)

    def as_table(self):
        """Convert to a odf.table.Table object"""
        t = Table(name=self.name)
        # Find out max row and col
        maxcol = max(col for col, row in self._contents.keys())
        maxrow = max(row for col, row in self._contents.keys())
        # Add column styles
        for c in range(0, maxcol + 1):
            s = self._columnstyles.get(c, None)
            if s:
                t.addElement(TableColumn(stylename=s))
            else:
                t.addElement(TableColumn())
        for row in range(0, maxrow + 1):
            tr = TableRow()
            t.addElement(tr)
            for col in range(0, maxcol + 1):
                cell = self._contents.get((col, row), None)
                if cell:
                    tr.addElement(cell)
                else:
                    tr.addElement(TableCell())
        return t

class Document:
    """An OpenDocumentSpreadsheet under construction"""

    mimetype = 'application/vnd.oasis.opendocument.spreadsheet'

    def __init__(self, filename=None):
        self.doc = OpenDocumentSpreadsheet()
        self.filename = filename

        # Add some common styles
        self.tablecontents = Style(name="Table Contents", family="paragraph")
        self.tablecontents.addElement(
            ParagraphProperties(numberlines="false", linenumber="0"))
        self.doc.styles.addElement(self.tablecontents)

        self.currencystyle = self._add_currencystyle()

        self.boldcurrencystyle = Style(name="BoldPounds", family="table-cell",
                                       parentstylename=self.currencystyle)
        self.boldcurrencystyle.addElement(
            TextProperties(fontweight="bold"))
        self.doc.styles.addElement(self.boldcurrencystyle)

        self.boldtextstyle = Style(name="BoldText", family="table-cell",
                                   parentstylename=self.tablecontents)
        self.boldtextstyle.addElement(TextProperties(fontweight="bold"))
        self.doc.styles.addElement(self.boldtextstyle)

        self._widthstyles = {}

    def intcell(self, val):
        return TableCell(valuetype="float", value=val)

    numbercell = intcell

    def textcell(self, text):
        tc = TableCell(valuetype="string")
        tc.addElement(P(text=text))
        return tc

    @property
    def datestyle(self):
        if not hasattr(self, "_datestyle"):
            self._datestyle = self._add_datestyle()
        return self._datestyle

    @property
    def datetimestyle(self):
        if not hasattr(self, "_datetimestyle"):
            self._datetimestyle = self._add_datestyle(
                name="DateTime", include_time=True)
        return self._datetimestyle

    def _add_datestyle(self, name="Date", include_time=False):
        """Construct a date style"""
        slash = number.Text()
        slash.addText('/')
        ds = number.DateStyle(name="Date", automaticorder="true",
                              formatsource="language")
        ds.addElement(number.Day())
        ds.addElement(slash)
        ds.addElement(number.Month())
        ds.addElement(slash)
        ds.addElement(number.Year())
        if include_time:
            space = number.Text()
            space.addText(' ')
            colon = number.Text()
            colon.addText(':')
            ds.addElement(space)
            ds.addElement(number.Hours())
            ds.addElement(colon)
            ds.addElement(number.Minutes())
        self.doc.styles.addElement(ds)
        datestyle = Style(name=name, family="table-cell",
                          parentstylename="Default",
                          datastylename=name)
        self.doc.styles.addElement(datestyle)
        return datestyle

    def datecell(self, date, style=None):
        if not style:
            style = self.datestyle
        return TableCell(
            valuetype="date", datevalue=date.isoformat(), stylename=style)

    def datetimecell(self, datetime, style=None):
        if not style:
            style = self.datetimestyle
        return TableCell(
            valuetype="date", datevalue=datetime.isoformat(), stylename=style)

    def _add_currencystyle(self, name="Pounds"):
        """Construct a currency style"""
        cs = number.CurrencyStyle(name=name)
        symbol = number.CurrencySymbol(language="en", country="GB")
        symbol.addText("£")
        cs.addElement(symbol)
        n = number.Number(decimalplaces=2, minintegerdigits=1, grouping="true")
        cs.addElement(n)
        self.doc.styles.addElement(cs)
        currencystyle = Style(name=name, family="table-cell",
                              parentstylename="Default", datastylename=name)
        self.doc.styles.addElement(currencystyle)
        return currencystyle

    def moneycell(self, m, formula=None, style=None):
        a = { "valuetype": "currency",
              "currency": "GBP",
              "stylename": style if style else self.currencystyle,
        }
        if m is not None:
            a["value"] = str(m)
        if formula is not None:
            a["formula"] = formula
        return TableCell(**a)

    @property
    def headerstyle(self):
        if not hasattr(self, "_headerstyle"):
            self._headerstyle = self._add_headerstyle()
        return self._headerstyle

    def _add_headerstyle(self):
        header = Style(name="ColumnHeader", family="table-cell")
        header.addElement(
            ParagraphProperties(textalign="center"))
        header.addElement(
            TextProperties(fontweight="bold"))
        self.doc.styles.addElement(header)
        return header

    def headercell(self, text, style=None):
        if not style:
            style = self.headerstyle
        tc = TableCell(valuetype="string", stylename=style)
        tc.addElement(P(stylename=style, text=text))
        return tc

    def colwidth(self, width):
        if width not in self._widthstyles:
            w = Style(name="W{}".format(width), family="table-column")
            w.addElement(TableColumnProperties(columnwidth=width))
            self.doc.automaticstyles.addElement(w)
            self._widthstyles[width] = w
        return self._widthstyles[width]

    def add_table(self, table):
        self.doc.spreadsheet.addElement(table.as_table())

    def as_response(self):
        r = HttpResponse(content_type=self.mimetype)
        if self.filename:
            r['Content-Disposition'] = 'attachment; filename={}'.format(
                self.filename)
        self.doc.write(r)
        return r

def sessionrange(ds, start=None, end=None, rows="Sessions", tillname="Till"):
    """A spreadsheet summarising sessions between the start and end date.
    """
    depts = ds.query(Department).order_by(Department.id).all()
    tf = func.sum(Transline.items * Transline.amount).label("depttotal")
    # I believe weeks run Monday to Sunday!
    weeks = func.div(Session.date - datetime.date(2002, 8, 5), 7)

    if start is None:
        start = ds.query(func.min(Session.date)).scalar()
    if end is None:
        end = ds.query(func.max(Session.date)).scalar()

    if rows == "Sessions":
        depttotals = ds.query(Session, Department.id, tf)\
                       .select_from(Session)\
                       .options(undefer('actual_total'))\
                       .order_by(Session.id, Department.id)\
                       .group_by(Session.id, Department.id)\
                       .filter(select([func.count(SessionTotal.sessionid)],
                                      whereclause=SessionTotal.sessionid == Session.id)\
                               .correlate(Session.__table__)\
                               .as_scalar() != 0)\
                       .filter(Session.endtime != None)\
                       .filter(Session.date >= start)\
                       .filter(Session.date <= end)\
                       .join(Transaction, Transline, Department)
    else:
        dateranges = ds.query(func.min(Session.date).label("start"),
                              func.max(Session.date).label("end"))\
                       .filter(Session.date >= start)\
                       .filter(Session.date <= end)\
                       .filter(Session.endtime != None)

        if rows == "Days":
            dateranges = dateranges.group_by(Session.date)
        else:
            dateranges = dateranges.group_by(weeks)
        dateranges = dateranges.cte(name="dateranges")

        depttotals = ds.query(
            dateranges.c.start,
            dateranges.c.end,
            Transline.dept_id,
            tf)\
                       .select_from(dateranges.join(Session, and_(
                           Session.date >= dateranges.c.start,
                           Session.date <= dateranges.c.end))
                                    .join(Transaction)\
                                    .join(Transline))\
                       .group_by(dateranges.c.start,
                                 dateranges.c.end,
                                 Transline.dept_id)\
                       .order_by(dateranges.c.start, Transline.dept_id)

        acttotals = ds.query(
            dateranges.c.start, dateranges.c.end,
            select([func.sum(SessionTotal.amount)])\
            .correlate(dateranges)\
            .where(and_(
                Session.date >= dateranges.c.start,
                Session.date <= dateranges.c.end))\
            .select_from(Session.__table__.join(SessionTotal))\
            .label('actual_total'))\
                      .select_from(dateranges)\
                      .group_by(dateranges.c.start,
                                dateranges.c.end)\
                      .order_by(dateranges.c.start)

        acttotal_dict = {}
        for start, end, total in acttotals:
            acttotal_dict[(start, end)] = total

    filename = "{}-summary".format(tillname)

    if start:
        filename += "-from-{}".format(start)
    if end:
        filename += "-to-{}".format(end)
    if rows == "Days":
        filename += "-daily"
    if rows == "Weeks":
        filename += "-weekly"
    filename = filename + ".ods"

    doc = Document(filename=filename)

    table = Sheet(tillname)

    widthshort = doc.colwidth("2.0cm")
    widthtotal = doc.colwidth("2.2cm")
    widthgap = doc.colwidth("0.5cm")

    col = 0
    if rows == "Sessions":
        table.colstyle(col, widthshort)
        table.cell(col, 0, doc.headercell("ID"))
        idcol = col
        col += 1
    if rows == "Sessions" or rows == "Days":
        table.colstyle(col, widthshort)
        table.cell(col, 0, doc.headercell("Date"))
        datecol = col
        col += 1
    else:
        table.colstyle(col, widthshort)
        table.cell(col, 0, doc.headercell("From"))
        startdatecol = col
        col += 1
        table.colstyle(col, widthshort)
        table.cell(col, 0, doc.headercell("To"))
        enddatecol = col
        col += 1

    # Till total and actual total
    table.colstyle(col, widthtotal)
    table.cell(col, 0, doc.headercell("Till Total"))
    tilltotalcol = col
    col += 1
    table.colstyle(col, widthtotal)
    table.cell(col, 0, doc.headercell("Actual Total"))
    actualtotalcol = col
    col += 1

    # Difference between till total and actual total
    table.colstyle(col, widthshort)
    table.cell(col, 0, doc.headercell("Error"))
    errorcol = col
    col += 1

    table.colstyle(col, widthgap)
    col += 1

    deptscol = col

    for c in range(deptscol, deptscol + len(depts)):
        table.colstyle(c, widthshort)
    for d in depts:
        table.cell(col, 0, doc.headercell(d.description))
        col += 1

    row = 0
    prev_row = None
    for x in depttotals:
        if rows == "Sessions":
            session, dept, total = x
            actual_total = session.actual_total
            rowspec = session.id
        else:
            startdate, enddate, dept, total = x
            rowspec = (startdate, enddate)
            actual_total = acttotal_dict[rowspec]
        if rowspec != prev_row:
            prev_row = rowspec
            row += 1
            if rows == "Sessions":
                table.cell(idcol, row, doc.intcell(session.id))
                table.cell(datecol, row, doc.datecell(session.date))
            elif rows == "Days":
                table.cell(datecol, row, doc.datecell(startdate))
            else:
                table.cell(startdatecol, row, doc.datecell(startdate))
                table.cell(enddatecol, row, doc.datecell(enddate))

            table.cell(tilltotalcol, row, doc.moneycell(
                None, formula="oooc:=SUM([.{}:.{}])".format(
                    table.ref(deptscol, row),
                    table.ref(deptscol + len(depts) - 1, row))))
            table.cell(actualtotalcol, row, doc.moneycell(actual_total))
            table.cell(errorcol, row, doc.moneycell(
                None, formula="oooc:=[.{}]-[.{}]".format(
                    table.ref(actualtotalcol, row),
                    table.ref(tilltotalcol, row))))
            di = iter(depts)
            col = deptscol - 1
        while True:
            col += 1
            if next(di).id == dept:
                if total:
                    table.cell(col, row, doc.moneycell(total))
                break

    doc.add_table(table)

    return doc.as_response()

def session(ds, s, tillname="Till"):
    """A spreadsheet giving full details for a session
    """
    filename = "{}-session-{}{}.ods".format(
        tillname, s.id, "" if s.endtime else "-incomplete")
    doc = Document(filename)

    dsheet = Sheet("Departments")
    dsheet.cell(0, 0, doc.headercell("Dept"))
    dsheet.cell(1, 0, doc.headercell("Description"))
    if not s.endtime:
        dsheet.cell(2, 0, doc.headercell("Paid"))
        dsheet.cell(3, 0, doc.headercell("Pending"))
        tcol = 4
    else:
        tcol = 2
    dsheet.cell(tcol, 0, doc.headercell("Total"))

    row = 1
    for x in s.dept_totals_closed:
        if not x.paid and not x.pending:
            continue
        dsheet.cell(0, row, doc.intcell(x.Department.id))
        dsheet.cell(1, row, doc.textcell(x.Department.description))
        if not s.endtime:
            if x.paid:
                dsheet.cell(2, row, doc.moneycell(x.paid))
            if x.pending:
                dsheet.cell(3, row, doc.moneycell(x.pending))
        dsheet.cell(tcol, row, doc.moneycell(x.total))
        row += 1
    dsheet.cell(1, row, doc.headercell("Total:"))
    if not s.endtime:
        dsheet.cell(2, row, doc.moneycell(
            None, formula="oooc:=SUM([.{}:.{}])".format(
                dsheet.ref(2, 1), dsheet.ref(2, row - 1))))
        dsheet.cell(3, row, doc.moneycell(
            None, formula="oooc:=SUM([.{}:.{}])".format(
                dsheet.ref(3, 1), dsheet.ref(3, row - 1))))
    dsheet.cell(tcol, row, doc.moneycell(
        None, formula="oooc:=SUM([.{}:.{}])".format(
            dsheet.ref(tcol, 1), dsheet.ref(tcol, row - 1)),
        style=doc.boldcurrencystyle))

    doc.add_table(dsheet)

    sheet = Sheet("Users")
    sheet.colstyle(0, doc.colwidth("4.0cm"))
    sheet.cell(0, 0, doc.headercell("User"))
    sheet.cell(1, 0, doc.headercell("Items"))
    sheet.cell(2, 0, doc.headercell("Total"))
    row = 1
    for user, items, total in s.user_totals:
        sheet.cell(0, row, doc.textcell(user.fullname))
        sheet.cell(1, row, doc.intcell(items))
        sheet.cell(2, row, doc.moneycell(total))
        row = row + 1
    doc.add_table(sheet)

    sheet = Sheet("Stock sold")
    sheet.colstyle(0, doc.colwidth("8.5cm"))
    sheet.cell(0, 0, doc.headercell("Type"))
    sheet.cell(1, 0, doc.headercell("Quantity"))
    sheet.cell(2, 0, doc.headercell("Unit"))
    row = 1
    for st, q in s.stock_sold:
        sheet.cell(0, row, doc.textcell(st.format()))
        sheet.cell(1, row, doc.numbercell(q))
        sheet.cell(2, row, doc.textcell(st.unit.name))
        row += 1
    doc.add_table(sheet)

    tsheet = Sheet("Transactions")
    tsheet.cell(0, 0, doc.headercell("Transaction"))
    tsheet.cell(1, 0, doc.headercell("Amount"))
    tsheet.cell(2, 0, doc.headercell("Note"))
    tsheet.cell(3, 0, doc.headercell("State"))
    row = 1
    for t in s.transactions:
        tsheet.cell(0, row, doc.intcell(t.id))
        tsheet.cell(1, row, doc.moneycell(t.total))
        tsheet.cell(2, row, doc.textcell(t.notes))
        tsheet.cell(3, row, doc.textcell(
            "Closed" if t.closed else "Open"))
        row += 1

    doc.add_table(tsheet)

    return doc.as_response()

def stock(ds, stocklist, tillname="Till", filename=None):
    """A list of stock items as a spreadsheet
    """
    if not filename:
        filename = "{}-stock.ods".format(tillname)

    doc = Document(filename)
    sheet = Sheet("{} stock".format(tillname))

    sheet.cell(0, 0, doc.headercell("Stock ID"))
    sheet.cell(1, 0, doc.headercell("Manufacturer"))
    sheet.cell(2, 0, doc.headercell("Name"))
    sheet.cell(3, 0, doc.headercell("ABV"))
    sheet.cell(4, 0, doc.headercell("Cost Price"))
    sheet.cell(5, 0, doc.headercell("Sale Price"))
    sheet.cell(6, 0, doc.headercell("Used"))
    sheet.cell(7, 0, doc.headercell("Sold"))
    sheet.cell(8, 0, doc.headercell("Size"))
    sheet.cell(9, 0, doc.headercell("Remaining"))
    sheet.cell(10, 0, doc.headercell("Unit"))
    sheet.cell(11, 0, doc.headercell("Finish code"))
    sheet.cell(12, 0, doc.headercell("Finish date"))

    sheet.colstyle(0, doc.colwidth("1.8cm"))
    sheet.colstyle(1, doc.colwidth("3.4cm"))
    sheet.colstyle(2, doc.colwidth("5.0cm"))
    sheet.colstyle(3, doc.colwidth("1.2cm"))
    sheet.colstyle(4, doc.colwidth("2.1cm"))
    sheet.colstyle(5, doc.colwidth("2.1cm"))
    sheet.colstyle(6, doc.colwidth("1.4cm"))
    sheet.colstyle(7, doc.colwidth("1.4cm"))
    sheet.colstyle(8, doc.colwidth("1.4cm"))
    sheet.colstyle(12, doc.colwidth("2.7cm"))

    row = 1

    for s in stocklist:
        sheet.cell(0, row, doc.numbercell(s.id))
        sheet.cell(1, row, doc.textcell(s.stocktype.manufacturer))
        sheet.cell(2, row, doc.textcell(s.stocktype.name))
        if s.stocktype.abv:
            sheet.cell(3, row, doc.numbercell(s.stocktype.abv))
        if s.costprice:
            sheet.cell(4, row, doc.moneycell(s.costprice))
        if s.stocktype.saleprice:
            sheet.cell(5, row, doc.moneycell(s.stocktype.saleprice))
        sheet.cell(6, row, doc.numbercell(s.used))
        sheet.cell(7, row, doc.numbercell(s.sold))
        sheet.cell(8, row, doc.numbercell(s.size))
        sheet.cell(9, row, doc.numbercell(s.remaining))
        sheet.cell(10, row, doc.textcell(str(s.stocktype.unit.name)))
        if s.finishcode:
            sheet.cell(11, row, doc.textcell(str(s.finishcode)))
        if s.finished:
            sheet.cell(12, row, doc.datetimecell(s.finished))
        row += 1

    doc.add_table(sheet)
    return doc.as_response()

def daterange(start, end):
    """Produce a list of dates between start and end, inclusive
    """
    n = start
    while n <= end:
        yield n
        n += datetime.timedelta(days=1)

def waste(ds, start=None, end=None, cols="depts", tillname="Till"):
    """A report on waste

    Rows are dates.  Columns can be departments or waste types.

    Separate sheets are used for whichever of departments or waste
    types is not a column.

    The first row of each sheet is headers.
    """
    depts = ds.query(Department).order_by(Department.id).all()
    wastes = ds.query(RemoveCode).order_by(RemoveCode.id).all()
    wastes = wastes + [RemoveCode(id="unaccounted", reason="Unaccounted")]

    date = func.date(StockOut.time)
    data = ds.query(date,
                    StockType.dept_id,
                    StockOut.removecode_id,
                    func.sum(StockOut.qty))\
             .select_from(StockOut)\
             .join(StockItem, StockType)
    if start:
        data = data.filter(date >= start)
    else:
        start = ds.query(func.min(date)).scalar()
    if end:
        data = data.filter(date <= end)
    else:
        end = ds.query(func.max(date)).scalar()
    data = data.group_by(date, StockType.dept_id, StockOut.removecode_id).all()

    date = func.date(StockItem.finished)
    unaccounted = ds.query(date,
                           StockType.dept_id,
                           literal("unaccounted"),
                           func.sum(StockItem.size - StockItem.used))\
                    .select_from(StockItem)\
                    .join(StockType)\
                    .filter(StockItem.finished != None)\
                    .filter(StockItem.finished <= end)\
                    .filter(StockItem.finished >= start)\
                    .group_by(date, StockType.dept_id)\
                    .all()

    data = data + unaccounted

    filename = "{}-waste.ods".format(tillname)
    doc = Document(filename)

    def date_to_row(date):
        return (date - start).days + 1

    def add_dates(table):
        row = 1
        for date in daterange(start, end):
            table.cell(0, row, doc.datecell(date))
            row += 1

    if cols == "depts":
        # Sheets are remove codes
        dept_cols = {} # Column indexed by dept_id
        col = 1
        for dept in depts:
            dept_cols[dept.id] = col
            col += 1
        waste_sheets = {} # Sheet indexed by removecode_id
        for rc in wastes:
            table = Sheet(rc.reason)
            waste_sheets[rc.id] = table
            add_dates(table)
            for dept in depts:
                table.cell(dept_cols[dept.id], 0,
                           doc.headercell(dept.description))
    else:
        # Sheets are departments
        waste_cols = {} # Column indexed by removecode_id
        col = 1
        for rc in wastes:
            waste_cols[rc.id] = col
            col += 1
        dept_sheets = {} # Sheet indexed by dept_id
        for dept in depts:
            table = Sheet(dept.description)
            dept_sheets[dept.id] = table
            add_dates(table)
            for rc in wastes:
                table.cell(waste_cols[rc.id], 0,
                           doc.headercell(rc.reason))

    for date, dept_id, removecode_id, qty in data:
        row = date_to_row(date)
        if cols == "depts":
            table = waste_sheets[removecode_id]
            table.cell(dept_cols[dept_id], row, doc.numbercell(qty))
        else:
            table = dept_sheets[dept_id]
            table.cell(waste_cols[removecode_id], row, doc.numbercell(qty))

    if cols == "depts":
        for rc in wastes:
            doc.add_table(waste_sheets[rc.id])
    else:
        for dept in depts:
            doc.add_table(dept_sheets[dept.id])

    return doc.as_response()

def stocksold(ds, start=None, end=None, dates="transaction", tillname="Till"):
    sold = ds.query(StockType, func.sum(StockOut.qty))\
             .options(contains_eager(StockType.department))\
             .join(Department)\
             .options(contains_eager(StockType.unit))\
             .join(UnitType)\
             .join(StockItem, StockOut)\
             .group_by(StockType, Department, UnitType)\
             .order_by(StockType.dept_id,
                       func.sum(StockOut.qty).desc())

    if dates == "transaction":
        sold = sold.join(Transline, Transaction, Session)
        if start:
            sold = sold.filter(Session.date >= start)
        if end:
            sold = sold.filter(Session.date <= end)
    else:
        sold = sold.filter(StockOut.removecode_id == 'sold')
        if start:
            sold = sold.filter(StockOut.time >= start)
        if end:
            sold = sold.filter(
                StockOut.time < (end + datetime.timedelta(days=1)))

    filename = "{}-stock-sold.ods".format(tillname)
    doc = Document(filename)

    sheet = Sheet("Stock sold")
    # Columns are:
    # Manufacturer  Name  ABV  Dept  qty  UnitType
    sheet.cell(0, 0, doc.headercell("Manufacturer"))
    sheet.cell(1, 0, doc.headercell("Name"))
    sheet.cell(2, 0, doc.headercell("ABV"))
    sheet.cell(3, 0, doc.headercell("Dept"))
    sheet.cell(4, 0, doc.headercell("Qty"))
    sheet.cell(5, 0, doc.headercell("Unit"))

    row = 1
    for st, qty in sold.all():
        sheet.cell(0, row, doc.textcell(st.manufacturer))
        sheet.cell(1, row, doc.textcell(st.name))
        if st.abv:
            sheet.cell(2, row, doc.numbercell(st.abv))
        sheet.cell(3, row, doc.textcell(st.department.description))
        sheet.cell(4, row, doc.numbercell(qty))
        sheet.cell(5, row, doc.textcell(st.unit.name))
        row += 1

    doc.add_table(sheet)
    return doc.as_response()
