from django.urls import include, path, re_path
from quicktill.tillweb.views import *

tillurls = [
    path('', pubroot, name="tillweb-pubroot"),

    path('session/', sessionfinder, name="tillweb-sessions"),
    path('session/<int:sessionid>/', include([
        path('', session, name="tillweb-session"),
        path('spreadsheet.ods', session_spreadsheet,
             name="tillweb-session-spreadsheet"),
        path('takings-by-dept.html', session_takings_by_dept,
             name="tillweb-session-takings-by-dept"),
        path('takings-by-user.html', session_takings_by_user,
             name="tillweb-session-takings-by-user"),
        path('discounts.html', session_discounts,
             name="tillweb-session-discounts"),
        path('stock-sold.html', session_stock_sold,
             name="tillweb-session-stock-sold"),
        path('transactions.html', session_transactions,
             name="tillweb-session-transactions"),
        path('sales-pie-chart.svg', session_sales_pie_chart,
             name="tillweb-session-sales-pie-chart"),
        path('users-pie-chart.svg', session_users_pie_chart,
             name="tillweb-session-users-pie-chart"),
        path('dept<int:dept>/', sessiondept,
             name="tillweb-session-department"),
        ])),

    path('transaction/deferred/', transactions_deferred,
         name="tillweb-deferred-transactions"),
    path('transaction/<int:transid>/', transaction, name="tillweb-transaction"),

    path('transline/<int:translineid>/', transline, name="tillweb-transline"),

    path('supplier/', supplierlist, name="tillweb-suppliers"),
    path('supplier/<int:supplierid>/', supplier, name="tillweb-supplier"),
    path('new/supplier/', create_supplier, name="tillweb-create-supplier"),

    path('delivery/', deliverylist, name="tillweb-deliveries"),
    path('delivery/<int:deliveryid>/', delivery, name="tillweb-delivery"),

    path('stocktype/', stocktypesearch, name="tillweb-stocktype-search"),
    path('stocktype/<int:stocktype_id>/', stocktype, name="tillweb-stocktype"),

    path('stock/', stocksearch, name="tillweb-stocksearch"),
    path('stock/<int:stockid>/', stock, name="tillweb-stock"),

    path('unit/', units, name="tillweb-units"),
    path('unit/<int:unit_id>/', unit, name="tillweb-unit"),
    path('new/unit/', create_unit, name="tillweb-create-unit"),

    path('stockunit/', stockunits, name="tillweb-stockunits"),
    path('stockunit/<int:stockunit_id>/', stockunit, name="tillweb-stockunit"),
    path('new/stockunit/', create_stockunit, name="tillweb-create-stockunit"),

    path('stockline/', stocklinelist, name="tillweb-stocklines"),
    path('stockline/<int:stocklineid>/', stockline, name="tillweb-stockline"),

    path('plu/', plulist, name="tillweb-plus"),
    path('plu/<int:pluid>/', plu, name="tillweb-plu"),
    path('new/plu/', create_plu, name="tillweb-create-plu"),

    path('location/', locationlist, name="tillweb-locations"),
    re_path(r'^location/(?P<location>[\w\- ]+)/$', location,
            name="tillweb-location"),

    path('department/', departmentlist, name="tillweb-departments"),
    path('department/<int:departmentid>/', department,
         name="tillweb-department"),
    path('department/<int:departmentid>/spreadsheet.ods', department,
         {'as_spreadsheet': True}, name="tillweb-department-sheet"),

    path('stockcheck/', stockcheck, name="tillweb-stockcheck"),

    path('user/', userlist, name="tillweb-till-users"),
    path('user/<int:userid>/', user, name="tillweb-till-user"),

    path('group/', grouplist, name="tillweb-till-groups"),
    re_path('^group/(?P<groupid>[\w\- ]+)/$', group, name="tillweb-till-group"),
    path('new/group/', create_group, name="tillweb-create-till-group"),

    path('reports/', reportindex, name="tillweb-reports"),
]

urls = [
    # Index page
    path('', publist, name="tillweb-publist"),
    re_path(r'^(?P<pubname>[\w\-]+)/', include(tillurls)),
]
