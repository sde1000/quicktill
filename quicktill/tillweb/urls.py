from django.urls import include, path, re_path
from quicktill.tillweb import views
from quicktill.tillweb import stocktake
from quicktill.tillweb import datatable

tillurls = [
    path('', views.pubroot, name="tillweb-pubroot"),

    path('session/', views.sessions, name="tillweb-sessions"),
    path('session/<int:sessionid>/', include([
        path('', views.session, name="tillweb-session"),
        path('spreadsheet.ods', views.session_spreadsheet,
             name="tillweb-session-spreadsheet"),
        path('discounts.html', views.session_discounts,
             name="tillweb-session-discounts"),
        path('stock-sold.html', views.session_stock_sold,
             name="tillweb-session-stock-sold"),
    ])),

    path('transaction/', views.transactions, name="tillweb-transactions"),
    path('transaction/<int:transid>/', views.transaction,
         name="tillweb-transaction"),

    path('transline/', views.translines, name="tillweb-translines"),
    path('transline/<int:translineid>/', views.transline,
         name="tillweb-transline"),

    path('payment/', views.payments, name="tillweb-payments"),
    path('payment/<int:paymentid>/', views.payment,
         name="tillweb-payment"),

    path('supplier/', views.supplierlist, name="tillweb-suppliers"),
    path('supplier/<int:supplierid>/', views.supplier,
         name="tillweb-supplier"),
    path('new/supplier/', views.create_supplier,
         name="tillweb-create-supplier"),

    path('delivery/', views.deliverylist, name="tillweb-deliveries"),
    path('delivery/<int:deliveryid>/', views.delivery,
         name="tillweb-delivery"),
    path('new/delivery/', views.create_delivery,
         name="tillweb-create-delivery"),

    path('stocktake/', stocktake.stocktakelist, name="tillweb-stocktakes"),
    path('stocktake/<int:stocktake_id>/', stocktake.stocktake,
         name="tillweb-stocktake"),
    path('new/stocktake/', stocktake.create_stocktake,
         name="tillweb-create-stocktake"),

    path('stocktype/', views.stocktypesearch, name="tillweb-stocktype-search"),
    path('stocktype/<int:stocktype_id>/', views.stocktype,
         name="tillweb-stocktype"),
    path('stocktype/<int:stocktype_id>/logo.png', views.stocktype_logo,
         name="tillweb-stocktype-logo"),
    path('new/stocktype/', views.create_stocktype,
         name="tillweb-create-stocktype"),
    path('stocktype/search.json', views.stocktype_search_json,
         name="tillweb-stocktype-search-json"),
    path('stocktype/search-with-stockunits.json', views.stocktype_search_json,
         name="tillweb-stocktype-search-stockunits-json",
         kwargs={'include_stockunits': True}),
    path('stocktype/info.json', views.stocktype_info_json,
         name="tillweb-stocktype-info-json"),

    path('stock/', views.stocksearch, name="tillweb-stocksearch"),
    path('stock/<int:stockid>/', views.stock, name="tillweb-stock"),

    path('unit/', views.units, name="tillweb-units"),
    path('unit/<int:unit_id>/', views.unit, name="tillweb-unit"),
    path('new/unit/', views.create_unit, name="tillweb-create-unit"),

    path('stockunit/', views.stockunits, name="tillweb-stockunits"),
    path('stockunit/<int:stockunit_id>/', views.stockunit,
         name="tillweb-stockunit"),
    path('new/stockunit/', views.create_stockunit,
         name="tillweb-create-stockunit"),

    path('stockline/', views.stocklinelist, name="tillweb-stocklines"),
    path('stockline/<int:stocklineid>/', views.stockline,
         name="tillweb-stockline"),

    path('plu/', views.plulist, name="tillweb-plus"),
    path('plu/<int:pluid>/', views.plu, name="tillweb-plu"),
    path('new/plu/', views.create_plu, name="tillweb-create-plu"),

    path('barcode/', views.barcodelist, name="tillweb-barcodes"),
    path('barcode/<barcode>/', views.barcode, name="tillweb-barcode"),

    path('location/', views.locationlist, name="tillweb-locations"),
    path('location/<location>/', views.location, name="tillweb-location"),

    path('department/', views.departmentlist, name="tillweb-departments"),
    path('department/<int:departmentid>/', views.department,
         name="tillweb-department"),
    path('department/<int:departmentid>/spreadsheet.ods', views.department,
         {'as_spreadsheet': True}, name="tillweb-department-sheet"),
    path('new/department/', views.create_department,
         name="tillweb-create-department"),

    path('paytype/', views.paytypelist, name="tillweb-paytypes"),
    path('paytype/<paytype>/', views.paytype, name="tillweb-paytype"),
    path('new/paytype/', views.create_paytype,
         name="tillweb-create-paytype"),

    path('user/', views.userlist, name="tillweb-till-users"),
    path('user/<int:userid>/', views.userdetail, name="tillweb-till-user"),
    path('new/user/', views.create_user, name="tillweb-create-user"),

    path('group/', views.grouplist, name="tillweb-till-groups"),
    path('group/<groupid>/', views.group, name="tillweb-till-group"),
    path('new/group/', views.create_group, name="tillweb-create-till-group"),

    path('token/', views.tokenlist, name="tillweb-tokens"),

    path('logs/', views.logsindex, name="tillweb-logs"),
    path('logs/<int:logid>', views.logdetail, name="tillweb-logentry"),

    path('config/', views.configindex, name="tillweb-config-index"),
    path('config/<key>/', views.configitem, name="tillweb-config-item"),

    path('reports/', views.reportindex, name="tillweb-reports"),
    path('reports/wasted-stock/', views.waste_report,
         name="tillweb-report-wasted-stock"),
    path('reports/stock-sold/', views.stock_sold_report,
         name="tillweb-report-stock-sold"),
    path('reports/stockcheck/', views.stockcheck, name="tillweb-stockcheck"),
    path('reports/translines/', views.transline_summary_report,
         name="tillweb-report-transline-summary"),
    path('reports/refusals/', views.refusals, name="tillweb-refusals"),

    path('datatable/sessions.json', datatable.sessions,
         name="tillweb-datatable-sessions"),
    path('datatable/sessiontotals.json', datatable.sessiontotals,
         name="tillweb-datatable-sessiontotals"),
    path('datatable/transactions.json', datatable.transactions,
         name="tillweb-datatable-transactions"),
    path('datatable/translines.json', datatable.translines,
         name="tillweb-datatable-translines"),
    path('datatable/payments.json', datatable.payments,
         name="tillweb-datatable-payments"),
    path('datatable/deliveries.json', datatable.deliveries,
         name="tillweb-datatable-deliveries"),
    path('datatable/annotations.json', datatable.annotations,
         name="tillweb-datatable-annotations"),
    path('datatable/logs.json', datatable.logs,
         name="tillweb-datatable-logs"),
    path('datatable/users.json', datatable.users,
         name="tillweb-datatable-users"),
    path('datatable/tokens.json', datatable.tokens,
         name="tillweb-datatable-tokens"),
    path('datatable/depttotals.json', datatable.depttotals,
         name="tillweb-datatable-depttotals"),
    path('datatable/usertotals.json', datatable.usertotals,
         name="tillweb-datatable-usertotals"),
    path('datatable/refusals-log.json', datatable.refusals,
         name="tillweb-datatable-refusals"),
]

urls = [
    # Index page
    path('', views.publist, name="tillweb-publist"),
    re_path(r'^(?P<pubname>[\w\-]+)/', include(tillurls)),
]
