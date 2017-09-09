from django.conf.urls import include, url
from quicktill.tillweb.views import *

tillurls = [
    url(r'^$', pubroot, name="tillweb-pubroot"),

    url(r'^session/$', sessionfinder, name="tillweb-sessions"),
    url(r'^session/(?P<sessionid>\d+)/', include([
        url(r'^$', session, name="tillweb-session"),
        url(r'^spreadsheet.ods$', session_spreadsheet,
            name="tillweb-session-spreadsheet"),
        url(r'^takings-by-dept.html$', session_takings_by_dept,
            name="tillweb-session-takings-by-dept"),
        url(r'^takings-by-user.html$', session_takings_by_user,
            name="tillweb-session-takings-by-user"),
        url(r'^stock-sold.html$', session_stock_sold,
            name="tillweb-session-stock-sold"),
        url(r'^transactions.html$', session_transactions,
            name="tillweb-session-transactions"),
        url(r'^sales-pie-chart.svg$', session_sales_pie_chart,
            name="tillweb-session-sales-pie-chart"),
        url(r'^users-pie-chart.svg$', session_users_pie_chart,
            name="tillweb-session-users-pie-chart"),
        url(r'^dept(?P<dept>\d+)/$', sessiondept,
            name="tillweb-session-department"),
        ])),

    url(r'^transaction/deferred/$', transactions_deferred,
        name="tillweb-deferred-transactions"),
    url(r'^transaction/(?P<transid>\d+)/$', transaction,
        name="tillweb-transaction"),

    url(r'^transline/(?P<translineid>\d+)/$', transline,
        name="tillweb-transline"),

    url(r'^supplier/$', supplierlist, name="tillweb-suppliers"),
    url(r'^supplier/(?P<supplierid>\d+)/$', supplier,
        name="tillweb-supplier"),

    url(r'^delivery/$', deliverylist, name="tillweb-deliveries"),
    url(r'^delivery/(?P<deliveryid>\d+)/$', delivery,
        name="tillweb-delivery"),

    url(r'^stocktype/$', stocktypesearch, name="tillweb-stocktype-search"),
    url(r'^stocktype/(?P<stocktype_id>\d+)/$', stocktype,
        name="tillweb-stocktype"),

    url(r'^stock/$', stocksearch, name="tillweb-stocksearch"),
    url(r'^stock/(?P<stockid>\d+)/$', stock,
        name="tillweb-stock"),

    url(r'^stockline/$', stocklinelist, name="tillweb-stocklines"),
    url(r'^stockline/(?P<stocklineid>\d+)/$', stockline,
        name="tillweb-stockline"),

    url(r'^plu/$', plulist, name="tillweb-plus"),
    url(r'^plu/(?P<pluid>\d+)/$', plu, name="tillweb-plu"),

    url(r'^location/$', locationlist, name="tillweb-locations"),
    url(r'^location/(?P<location>[\w\- ]+)/$', location,
        name="tillweb-location"),

    url(r'^department/$', departmentlist, name="tillweb-departments"),
    url(r'^department/(?P<departmentid>\d+)/$', department,
        name="tillweb-department"),
    url(r'^department/(?P<departmentid>\d+)/spreadsheet.ods$', department,
        {'as_spreadsheet': True}, name="tillweb-department-sheet"),

    url(r'^stockcheck/$', stockcheck, name="tillweb-stockcheck"),

    url(r'^user/$', userlist, name="tillweb-till-users"),
    url(r'^user/(?P<userid>\d+)/$', user, name="tillweb-till-user"),
]

urls = [
    # Index page
    url(r'^$', publist, name="tillweb-publist"),
    url(r'^(?P<pubname>[\w\-]+)/', include(tillurls)),
]
