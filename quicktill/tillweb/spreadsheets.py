# -*- coding: utf-8 -*-
from django.http import HttpResponse
from quicktill.models import *
from sqlalchemy.orm import undefer
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

    def _add_datestyle(self, name="Date"):
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

def sessionrange(ds, start=None, end=None, tillname="Till"):
    """A spreadsheet summarising sessions between the start and end date.
    """
    depts = ds.query(Department).order_by(Department.id).all()
    depttotals = ds.query(Session, Department, func.sum(
        Transline.items * Transline.amount))\
                   .select_from(Session)\
                   .options(undefer('actual_total'))\
                   .filter(Session.endtime != None)\
                   .filter(select([func.count(SessionTotal.sessionid)],
                                  whereclause=SessionTotal.sessionid == Session.id)\
                           .correlate(Session.__table__)\
                           .as_scalar() != 0)\
                   .join(Transaction, Transline, Department)\
                   .order_by(Session.id, Department.id)\
                   .group_by(Session, Department)
    if start:
        depttotals = depttotals.filter(Session.date >= start)
    if end:
        depttotals = depttotals.filter(Session.date <= end)

    filename = "{}-summary".format(tillname)
    if start:
        filename = filename + "-from-{}".format(start)
    if end:
        filename = filename + "-to-{}".format(end)
    filename = filename + ".ods"

    doc = Document(filename=filename)

    table = Sheet(tillname)

    widthshort = doc.colwidth("2.0cm")
    widthtotal = doc.colwidth("2.2cm")
    widthgap = doc.colwidth("0.5cm")

    # Columns 0 and 1 are Session ID and date
    table.colstyle(0, widthshort)
    table.colstyle(1, widthshort)
    # Columns 2 and 3 are till total and actual total
    table.colstyle(2, widthtotal)
    table.colstyle(3, widthtotal)
    # Column 4 is the difference between till total and actual total
    table.colstyle(4, widthshort)
    # Column 5 is a gap
    table.colstyle(5, widthgap)
    # Columns 6+ are departments
    deptscol = 6
    for c in range(deptscol, deptscol + len(depts)):
        table.colstyle(c, widthshort)

    # Row 0 is headers
    table.cell(0, 0, doc.headercell("ID"))
    table.cell(1, 0, doc.headercell("Date"))
    table.cell(2, 0, doc.headercell("Till Total"))
    table.cell(3, 0, doc.headercell("Actual Total"))
    table.cell(4, 0, doc.headercell("Error"))
    col = deptscol
    for d in depts:
        table.cell(col, 0, doc.headercell(d.description))
        col += 1

    row = 0
    prev_s = None
    for s, d, t in depttotals:
        if s != prev_s:
            prev_s = s
            row += 1
            table.cell(0, row, doc.intcell(s.id))
            table.cell(1, row, doc.datecell(s.date))
            table.cell(2, row, doc.moneycell(
                None, formula="oooc:=SUM([.{}:.{}])".format(
                    table.ref(deptscol, row),
                    table.ref(deptscol + len(depts) - 1, row))))
            table.cell(3, row, doc.moneycell(s.actual_total))
            table.cell(4, row, doc.moneycell(
                None, formula="oooc:=[.{}]-[.{}]".format(
                    table.ref(3, row),
                    table.ref(2, row))))
            di = iter(depts)
            col = deptscol - 1
        while True:
            col += 1
            dept = next(di)
            if dept == d:
                table.cell(col, row, doc.moneycell(t))
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
    for dept, total, paid, pending in s.dept_totals_closed:
        if not paid and not pending:
            continue
        dsheet.cell(0, row, doc.intcell(dept.id))
        dsheet.cell(1, row, doc.textcell(dept.description))
        if not s.endtime:
            if paid:
                dsheet.cell(2, row, doc.moneycell(paid))
            if pending:
                dsheet.cell(3, row, doc.moneycell(pending))
        dsheet.cell(tcol, row, doc.moneycell(total))
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
