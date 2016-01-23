# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django.http import HttpResponse
from quicktill.models import *
from sqlalchemy.orm import undefer
from odf.opendocument import OpenDocumentSpreadsheet
from odf.style import Style, TextProperties, ParagraphProperties
from odf.style import TableColumnProperties
from odf.text import P
from odf.table import Table, TableColumn, TableRow, TableCell
import odf.number as number

def dateStyle(doc):
    slash=number.Text()
    slash.addText('/')
    ds=number.DateStyle(name="Date", automaticorder="true",
                        formatsource="language")
    ds.addElement(number.Day())
    ds.addElement(slash)
    ds.addElement(number.Month())
    ds.addElement(slash)
    ds.addElement(number.Year())
    doc.styles.addElement(ds)
    datestyle=Style(name="Date",family="table-cell",parentstylename="Default",
                    datastylename="Date")
    doc.styles.addElement(datestyle)
    return datestyle

def currencyStyle(doc):
    cs=number.CurrencyStyle(name="Pounds")
    symbol=number.CurrencySymbol(language="en", country="GB")
    symbol.addText("£")
    cs.addElement(symbol)
    n=number.Number(decimalplaces=2, minintegerdigits=1, grouping="true")
    cs.addElement(n)
    doc.styles.addElement(cs)
    currencystyle=Style(name="Pounds",family="table-cell",
                        parentstylename="Default",datastylename="Pounds")
    doc.styles.addElement(currencystyle)
    return currencystyle

def sessionrange(ds,start=None,end=None,tillname="Till"):
    """
    A spreadsheet summarising sessions between the start and end date.

    """
    depts=ds.query(Department).order_by(Department.id).all()
    depttotals=ds.query(Session,Department,func.sum(
            Transline.items*Transline.amount)).\
        select_from(Session).\
        options(undefer('total')).\
        options(undefer('actual_total')).\
        filter(Session.endtime!=None).\
        filter(select([func.count(SessionTotal.sessionid)],
                      whereclause=SessionTotal.sessionid==Session.id).\
                   correlate(Session.__table__).as_scalar()!=0).\
        join(Transaction,Transline,Department).\
        order_by(Session.id,Department.id).\
        group_by(Session,Department)
    if start: depttotals=depttotals.filter(Session.date>=start)
    if end: depttotals=depttotals.filter(Session.date<=end)

    doc=OpenDocumentSpreadsheet()

    datestyle=dateStyle(doc)
    currencystyle=currencyStyle(doc)

    header=Style(name="ColumnHeader",family="table-cell")
    header.addElement(
        ParagraphProperties(textalign="center"))
    header.addElement(
        TextProperties(fontweight="bold"))
    doc.automaticstyles.addElement(header)

    def colwidth(w):
        if not hasattr(colwidth,'num'): colwidth.num=0
        colwidth.num+=1
        width=Style(name="W{}".format(colwidth.num),family="table-column")
        width.addElement(TableColumnProperties(columnwidth=w))
        doc.automaticstyles.addElement(width)
        return width

    widthshort=colwidth("2.0cm")
    widthtotal=colwidth("2.2cm")
    widthgap=colwidth("0.5cm")

    table=Table(name=tillname)

    # Session ID and date
    table.addElement(TableColumn(numbercolumnsrepeated=2,stylename=widthshort))
    # Totals
    table.addElement(TableColumn(numbercolumnsrepeated=2,stylename=widthtotal))
    # Gap
    table.addElement(TableColumn(stylename=widthgap))
    # Departments
    table.addElement(TableColumn(numbercolumnsrepeated=len(depts),
                                 stylename=widthshort))

    tr=TableRow()
    table.addElement(tr)
    def tcheader(text):
        tc=TableCell(valuetype="string",stylename=header)
        tc.addElement(P(stylename=header,text=text))
        return tc
    tr.addElement(tcheader("ID"))
    tr.addElement(tcheader("Date"))
    tr.addElement(tcheader("Till Total"))
    tr.addElement(tcheader("Actual Total"))
    tr.addElement(TableCell())
    for d in depts:
        tr.addElement(tcheader(d.description))

    def tcint(i):
        """
        Integer table cell

        """
        return TableCell(valuetype="float",value=i)

    def tcdate(d):
        """
        Date table cell

        """
        return TableCell(valuetype="date",datevalue=d,stylename=datestyle)

    def tcmoney(m):
        """
        Money table cell

        """
        return TableCell(valuetype="currency",currency="GBP",value=str(m),
                         stylename=currencystyle)

    tr=None
    prev_s=None
    for s,d,t in depttotals:
        if s!=prev_s:
            prev_s=s
            tr=TableRow()
            table.addElement(tr)
            tr.addElement(tcint(s.id))
            tr.addElement(tcdate(s.date))
            tr.addElement(tcmoney(s.total))
            tr.addElement(tcmoney(s.actual_total))
            tr.addElement(TableCell())
            di=iter(depts)
        while True:
            dept=next(di)
            if dept==d:
                tr.addElement(tcmoney(t))
                break
            else:
                tr.addElement(TableCell())

    doc.spreadsheet.addElement(table)

    filename="{}-summary".format(tillname)
    if start: filename=filename+"-from-{}".format(start)
    if end: filename=filename+"-to-{}".format(end)
    filename=filename+".ods"

    r=HttpResponse(content_type='application/vnd.oasis.opendocument.spreadsheet')
    r['Content-Disposition']='attachment; filename={}'.format(filename)
    doc.write(r)
    return r
