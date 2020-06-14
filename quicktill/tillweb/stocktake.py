from decimal import Decimal
import datetime
from django.http import Http404
from django.http import HttpResponseRedirect
from django import forms
from django.contrib import messages
from sqlalchemy import inspect
from sqlalchemy.sql import desc
from sqlalchemy.orm import subqueryload
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import undefer
from quicktill.models import StockType
from quicktill.models import StockTake
from quicktill.models import StockItem
from quicktill.models import StockTakeSnapshot
from quicktill.models import StockTakeAdjustment
from quicktill.models import FinishCode
from quicktill.models import RemoveCode

from .views import tillweb_view
from .views import td
from .views import stocktype_widget_label
from .views import user

@tillweb_view
def stocktakelist(request, info):
    may_start = info.user_has_perm("stocktake")

    if may_start and request.method == 'POST':
        if 'submit_new' in request.POST:
            st = StockTake(description=f'{info.user} {datetime.datetime.now():%Y-%m-%d %H:%M}',
                           create_user=info.user)
            td.s.add(st)
            td.s.commit()
            return HttpResponseRedirect(st.get_absolute_url())

    pending = td.s.query(StockTake)\
                  .filter(StockTake.start_time == None)\
                  .order_by(StockTake.id)\
                  .options(joinedload('scope'))\
                  .all()

    in_progress = td.s.query(StockTake)\
                      .filter(StockTake.start_time != None)\
                      .filter(StockTake.commit_time == None)\
                      .order_by(StockTake.start_time)\
                      .options(joinedload('scope'))\
                      .all()

    # XXX going to need a pager on this
    completed = td.s.query(StockTake)\
                    .filter(StockTake.commit_time != None)\
                    .order_by(desc(StockTake.commit_time))\
                    .options(joinedload('snapshots'))\
                    .all()

    return ('stocktakes.html', {
        'pending': pending,
        'in_progress': in_progress,
        'completed': completed,
        'may_start': may_start,
        'nav': [("Stock takes", info.reverse("tillweb-stocktakes"))],
    })

@tillweb_view
def stocktake(request, info, stocktake_id):
    stocktake = td.s.query(StockTake).get(stocktake_id)
    if not stocktake:
        raise Http404
    if stocktake.state == "pending":
        return stocktake_pending(request, info, stocktake)
    elif stocktake.state == "in progress":
        return stocktake_in_progress(request, info, stocktake)

    snapshots = td.s.query(StockTakeSnapshot)\
        .filter(StockTakeSnapshot.stocktake == stocktake)\
        .options(undefer('newqty'))\
        .options(joinedload('adjustments').joinedload('removecode'))\
        .options(joinedload('stockitem').joinedload('stocktype'))\
        .order_by(StockTakeSnapshot.stock_id)\
        .all()

    stocktypes = _snapshots_to_stocktypes(snapshots)
    return ('stocktake.html', {
        'tillobject': stocktake,
        'stocktake': stocktake,
        'stocktypes': stocktypes,
    })

class StockTakeSetupForm(forms.Form):
    description = forms.CharField()

def stocktake_pending(request, info, st):
    may_edit = info.user_has_perm('stocktake')

    initial = {'description': st.description}

    form = None

    if may_edit:
        if request.method == 'POST':
            form = StockTakeSetupForm(request.POST, initial=initial)
            if 'submit_delete' in request.POST:
                user.log(f"Abandoned pending stock take {st.logref}")
                messages.success(request,
                                 f"Pending stock take {st.id} abandoned")
                td.s.delete(st)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-stocktakes"))
            if 'submit_update' in request.POST:
                if form.is_valid():
                    st.description = form.cleaned_data['description']
                    td.s.commit()
                    messages.success(request, "Description updated")
                    return HttpResponseRedirect(st.get_absolute_url())
            if 'submit_start' in request.POST:
                if form.is_valid():
                    st.description = form.cleaned_data['description']
                    st.take_snapshot()
                    td.s.commit()
                    messages.success(request, "Stock take started")
                    return HttpResponseRedirect(st.get_absolute_url())
        else:
            form = StockTakeSetupForm(initial=initial)

    return ('stocktake-pending.html', {
        'tillobject': st,
        'stocktake': st,
        'form': form,
    })

def _snapshots_to_stocktypes(snapshots):
    stocktypes = []
    for s in snapshots:
        st = s.stockitem.stocktype
        if not hasattr(s.stockitem.stocktype, 'snapshots'):
            st.snapshots = [s]
            st.snapshot_qty = s.qty
            st.snapshot_newqty = s.newqty
            st.snapshot_finishcode = s.finishcode
            st.snapshot_checked = s.checked
            st.adjustments = {}
            stocktypes.append(st)
        else:
            st.snapshots.append(s)
            st.snapshot_qty += s.qty
            st.snapshot_newqty += s.newqty
            if s.finishcode != st.snapshot_finishcode:
                st.snapshot_finishcode = None
            if not s.checked:
                st.snapshot_checked = False
        for a in s.adjustments:
            q = st.adjustments.setdefault(a.removecode, Decimal(0))
            st.adjustments[a.removecode] = q + a.qty
    for st in stocktypes:
        st.snapshot_qty_in_saleunits = \
            st.unit.format_qty(st.snapshot_qty)
        st.snapshot_newqty_in_saleunits = \
            st.unit.format_qty(st.snapshot_newqty)
    return stocktypes

class StockTakeInProgressForm(forms.Form):
    stockid = forms.IntegerField(
        label="Stock ID to add to stock take", min_value=1, required=False)

def stocktake_in_progress(request, info, stocktake):
    may_edit = info.user_has_perm('stocktake')

    # We want to end up with a list of stocktypes that have snapshots
    # in this stocktake.  This could possibly be done as a query for
    # StockType and StockTakeSnapshot suitably joined and filtered,
    # but it's going to be simpler and faster to query snapshots (with
    # a joinedload of their adjustments) and then process to obtain
    # the list of stocktypes.

    finishcodes = td.s.query(FinishCode).all()
    removecodes = td.s.query(RemoveCode)\
                      .filter(RemoveCode.id != "sold")\
                      .all()

    snapshots = td.s.query(StockTakeSnapshot)\
        .filter(StockTakeSnapshot.stocktake == stocktake)\
        .options(undefer('newqty'),
                 joinedload('adjustments'),
                 joinedload('stockitem').joinedload('stocktype'))\
        .order_by(StockTakeSnapshot.stock_id)\
        .all()

    # dicts of finishcode and removecode
    finishcode_dict = {x.id: x for x in finishcodes}
    removecode_dict = {x.id: x for x in removecodes}

    def lookup_code(d, k):
        code = request.POST.get(k, "")
        return d.get(code, None)

    stocktypes = _snapshots_to_stocktypes(snapshots)

    form = StockTakeInProgressForm()

    if may_edit and request.method == 'POST':
        form = StockTakeInProgressForm(request.POST)
        if form.is_valid():
            new_stockid = form.cleaned_data['stockid']
            if new_stockid:
                si = td.s.query(StockItem).get(new_stockid)
                if si:
                    if si.stocktype.stocktake == stocktake:
                        # Take snapshot of item
                        td.s.add(StockTakeSnapshot(
                            stocktake=stocktake,
                            stockitem=si,
                            qty=si.remaining,
                            finishcode=si.finishcode))
                        messages.success(
                            request, f"Stock item {new_stockid} [{si.stocktype}] "
                                         "added to stock take.")
                    else:
                        messages.error(
                            request, f"Stock item {new_stockid} [{si.stocktype}] is "
                                       "not in scope for this stock take.")
                else:
                    messages.error(request, f"Stock item {new_stockid} does "
                                   "not exist")
        for stocktype in stocktypes:
            st_checkbox = f'st{stocktype.id}-checked' in request.POST
            st_checkbox_changed = st_checkbox != stocktype.snapshot_checked
            st_finishcode = lookup_code(
                finishcode_dict, f'st{stocktype.id}-finishcode')
            st_finishcode_changed = st_finishcode != stocktype.snapshot_finishcode
            try:
                st_adjustqty = Decimal(request.POST.get(
                    f'st{stocktype.id}-adjustqty', None))
                # Convert from sale units to base units
                st_adjustqty = st_adjustqty * stocktype.unit.units_per_item
                # Convert from relative adjustment to absolute
                st_adjustqty = stocktype.snapshot_newqty - st_adjustqty
            except:
                st_adjustqty = None
            st_adjustreason = lookup_code(
                removecode_dict, f'st{stocktype.id}-adjustreason')

            for ss in stocktype.snapshots:
                ss_checkbox = f'ss{ss.stock_id}-checked' in request.POST
                ss_finishcode = lookup_code(
                    finishcode_dict, f'ss{ss.stock_id}-finishcode')
                try:
                    ss_adjustqty = Decimal(request.POST.get(
                        f'ss{ss.stock_id}-adjustqty', None))
                except:
                    ss_adjustqty = None
                ss_adjustreason = lookup_code(
                    removecode_dict, f'ss{ss.stock_id}-adjustreason')
                if stocktype.stocktake_by_items:
                    ss_checkbox_changed = ss_checkbox != ss.checked
                    ss_finishcode_changed = ss_finishcode != ss.finishcode
                else:
                    ss_checkbox_changed = False
                    ss_finishcode_changed = False

                if st_finishcode_changed:
                    ss.finishcode = st_finishcode
                    ss.checked = True
                if ss_finishcode_changed:
                    ss.finishcode = ss_finishcode
                    ss.checked = True

                if st_adjustreason:
                    ss.checked = True
                if st_adjustqty and st_adjustreason:
                    with td.s.no_autoflush:
                        adjustment = \
                            td.s.query(StockTakeAdjustment)\
                                .get((stocktake.id, ss.stock_id,
                                      st_adjustreason.id)) \
                                or \
                                StockTakeAdjustment(
                                    snapshot=ss, removecode=st_adjustreason,
                                    qty=Decimal(0))
                    adjust_by = st_adjustqty
                    if ss.newqty - adjust_by < 0:
                        adjust_by = ss.newqty
                    # If this is not the last snapshot for the stocktype,
                    # don't exceed its original size
                    if ss != stocktype.snapshots[-1]:
                        if ss.newqty - adjust_by > ss.stockitem.size:
                            adjust_by = ss.newqty - ss.stockitem.size
                    print(f"Adjust {ss.stockitem} by {adjust_by}")
                    adjustment.qty = adjustment.qty + adjust_by
                    st_adjustqty -= adjust_by
                    if adjustment.qty == Decimal(0):
                        i = inspect(adjustment)
                        if i.persistent:
                            td.s.delete(adjustment)
                        elif i.pending:
                            td.s.expunge(adjustment)
                    else:
                        td.s.add(adjustment)

                if ss_adjustqty and ss_adjustreason:
                    ss.checked = True
                    with td.s.no_autoflush:
                        adjustment = \
                            td.s.query(StockTakeAdjustment)\
                                .get((stocktake.id, ss.stock_id,
                                      ss_adjustreason.id)) \
                                or \
                                StockTakeAdjustment(
                                    snapshot=ss, removecode=ss_adjustreason,
                                    qty=Decimal(0))
                    adjustment.qty = adjustment.qty + ss_adjustqty
                    if adjustment.qty == Decimal(0):
                        i = inspect(adjustment)
                        if i.persistent:
                            td.s.delete(adjustment)
                        elif i.pending:
                            td.s.expunge(adjustment)
                    else:
                        td.s.add(adjustment)

                if st_checkbox_changed:
                    ss.checked = st_checkbox
                if ss_checkbox_changed:
                    ss.checked = ss_checkbox

            # expand and collapse must be processed after all other
            # options because processing of individual snapshots
            # depends on the state of the page as originally rendered
            if f'expand-st{stocktype.id}' in request.POST:
                stocktype.stocktake_by_items = True
            if f'collapse-st{stocktype.id}' in request.POST:
                stocktype.stocktake_by_items = False

        if 'submit_abandon' in request.POST:
            checked = [ss for ss in snapshots if ss.checked]
            if checked:
                messages.error(request, "You must uncheck all items before you "
                               "can abandon this stock take.")
            else:
                user.log(f"Abandoned stock take in progress {stocktake.logref}")
                messages.success(
                    request, f"Stock take {stocktake.id} abandoned.")
                td.s.delete(stocktake)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-stocktakes"))

        if 'submit_finish' in request.POST:
            unchecked = [ss for ss in snapshots if not ss.checked]
            if unchecked:
                messages.error(request, "You must check all items before you "
                               "can complete this stock take.")
            else:
                user.log(f"Completed stock take {stocktake.logref}")
                messages.success(
                    request, f"Stock take {stocktake.id} completed.")
                stocktake.commit_snapshot(info.user)

        td.s.commit()
        return HttpResponseRedirect(stocktake.get_absolute_url())

    # Sort the stocktypes by department, manufacturer and name
    stocktypes.sort(key=lambda x:(x.dept_id, x.manufacturer, x.name))

    return ('stocktake-in-progress.html', {
        'tillobject': stocktake,
        'stocktake': stocktake,
        'stocktypes': stocktypes,
        'finishcodes': finishcodes,
        'removecodes': removecodes,
        'form': form,
    })

