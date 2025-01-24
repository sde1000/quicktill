from decimal import Decimal
from django.http import Http404
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django import forms
from django.contrib import messages
from sqlalchemy import inspect
from sqlalchemy.sql import desc
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
from .views import user


class StockTakeSetupForm(forms.Form):
    description = forms.CharField()


@tillweb_view
def stocktakelist(request, info):
    may_start = info.user_has_perm("stocktake")

    pending = td.s.query(StockTake)\
                  .filter(StockTake.start_time == None)\
                  .order_by(StockTake.id)\
                  .options(joinedload(StockTake.scope))\
                  .all()

    in_progress = td.s.query(StockTake)\
                      .filter(StockTake.start_time != None)\
                      .filter(StockTake.commit_time == None)\
                      .order_by(StockTake.start_time)\
                      .options(joinedload(StockTake.scope))\
                      .all()

    # XXX going to need a pager on this
    completed = td.s.query(StockTake)\
                    .filter(StockTake.commit_time != None)\
                    .order_by(desc(StockTake.commit_time))\
                    .options(joinedload(StockTake.snapshots))\
                    .all()

    return ('stocktakes.html', {
        'pending': pending,
        'in_progress': in_progress,
        'completed': completed,
        'may_start': may_start,
        'nav': [("Stock takes", info.reverse("tillweb-stocktakes"))],
    })


@tillweb_view
def create_stocktake(request, info):
    if not info.user_has_perm("stocktake"):
        return HttpResponseForbidden(
            "You don't have permission to start a stock take")

    if request.method == "POST":
        form = StockTakeSetupForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data
            st = StockTake(description=cd['description'],
                           create_user=info.user)
            td.s.add(st)
            td.s.flush()
            user.log(f"Created stock take {st.logref}")
            td.s.commit()
            messages.success(request, "Stock take created.")
            return HttpResponseRedirect(st.get_absolute_url())
    else:
        form = StockTakeSetupForm()

    return ('new-stocktake.html', {
        'nav': [("Stock takes", info.reverse("tillweb-stocktakes")),
                ("New", info.reverse("tillweb-create-stocktake"))],
        'form': form,
    })


@tillweb_view
def stocktake(request, info, stocktake_id):
    stocktake = td.s.get(StockTake, stocktake_id)
    if not stocktake:
        raise Http404
    if stocktake.state == "pending":
        return stocktake_pending(request, info, stocktake)
    elif stocktake.state == "in progress":
        return stocktake_in_progress(request, info, stocktake)

    snapshots = td.s.query(StockTakeSnapshot)\
        .filter(StockTakeSnapshot.stocktake == stocktake)\
        .options(undefer(StockTakeSnapshot.newqty))\
        .options(joinedload(StockTakeSnapshot.adjustments)
                 .joinedload(StockTakeAdjustment.removecode))\
        .options(joinedload(StockTakeSnapshot.stockitem)
                 .joinedload(StockItem.stocktype))\
        .order_by(StockTakeSnapshot.stock_id)\
        .all()

    stocktypes = _snapshots_to_stocktypes(snapshots)

    more_details_available = False in (
        st.unit.stocktake_by_items for st in stocktypes)

    return ('stocktake.html', {
        'tillobject': stocktake,
        'stocktake': stocktake,
        'stocktypes': stocktypes,
        'more_details_available': more_details_available,
    })


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
        st.adjustments = {rc: st.unit.format_stock_qty(qty)
                          for rc, qty in st.adjustments.items()}
        st.snapshot_qty_in_stockunits = \
            st.unit.format_stock_qty(st.snapshot_qty)
        st.snapshot_newqty_in_stockunits = \
            st.unit.format_stock_qty(st.snapshot_newqty)

    # Sort the stocktypes by department, manufacturer and name
    stocktypes.sort(key=lambda x: (x.dept_id, x.manufacturer, x.name))

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
    # XXX the "sold" removecode should be read from the
    # register:sold_stock_removecode_id configuration setting
    removecodes = td.s.query(RemoveCode)\
                      .filter(RemoveCode.id != "sold")\
                      .all()

    snapshots = td.s.query(StockTakeSnapshot)\
        .filter(StockTakeSnapshot.stocktake == stocktake)\
        .options(undefer(StockTakeSnapshot.newqty),
                 joinedload(StockTakeSnapshot.adjustments),
                 joinedload(StockTakeSnapshot.stockitem)
                 .joinedload(StockItem.stocktype)
                 .joinedload(StockType.unit),
                 joinedload(StockTakeSnapshot.stockitem)
                 .joinedload(StockItem.stockline))\
        .order_by(StockTakeSnapshot.stock_id)\
        .all()

    # dicts of finishcode and removecode
    finishcode_dict = {x.id: x for x in finishcodes}
    removecode_dict = {x.id: x for x in removecodes}

    # XXX this should be a configuration setting too
    default_adjustreason = 'missing' if 'missing' in removecode_dict else None

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
                si = td.s.get(StockItem, new_stockid)
                if si:
                    if si.stocktype.stocktake == stocktake:
                        # Take snapshot of item
                        td.s.add(StockTakeSnapshot(
                            stocktake=stocktake,
                            stockitem=si,
                            qty=si.remaining,
                            finishcode=si.finishcode))
                        messages.success(
                            request,
                            f"Stock item {new_stockid} [{si.stocktype}] "
                            "added to stock take.")
                    else:
                        messages.error(
                            request,
                            f"Stock item {new_stockid} [{si.stocktype}] is "
                            "not in scope for this stock take.")
                else:
                    messages.error(
                        request,
                        f"Stock item {new_stockid} does not exist")
        for stocktype in stocktypes:
            if stocktype.unit.stocktake_by_items:
                st_checkbox_changed = False
                st_finishcode_changed = False
            else:
                st_checkbox = f'st{stocktype.id}-checked' in request.POST
                st_checkbox_changed = st_checkbox != stocktype.snapshot_checked
                st_finishcode = lookup_code(
                    finishcode_dict, f'st{stocktype.id}-finishcode')
                st_finishcode_changed = (
                    st_finishcode != stocktype.snapshot_finishcode)
            st_adjusting = False
            try:
                st_adjustqty = Decimal(request.POST.get(
                    f'st{stocktype.id}-adjustqty', None))
                # Convert from stock units to base units
                st_adjustqty = \
                    st_adjustqty * stocktype.unit.base_units_per_stock_unit
                # Convert from relative adjustment to absolute
                st_adjustqty = stocktype.snapshot_newqty - st_adjustqty
            except Exception:
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
                    # Convert from stock units to base units
                    ss_adjustqty = \
                        ss_adjustqty * stocktype.unit.base_units_per_stock_unit
                    # Convert from relative adjustment to absolute
                    ss_adjustqty = ss.newqty - ss_adjustqty
                except Exception:
                    ss_adjustqty = None
                ss_adjustreason = lookup_code(
                    removecode_dict, f'ss{ss.stock_id}-adjustreason')
                if stocktype.unit.stocktake_by_items:
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

                if st_adjustqty and st_adjustreason:
                    # We are making a whole-stocktype adjustment: ensure
                    # we check each stockitem of the stocktype, even those
                    # that don't end up being adjusted
                    st_adjusting = True
                    with td.s.no_autoflush:
                        adjustment = (
                            td.s.get(StockTakeAdjustment,
                                     (stocktake.id, ss.stock_id,
                                      st_adjustreason.id))
                            or StockTakeAdjustment(
                                snapshot=ss, removecode=st_adjustreason,
                                qty=Decimal(0))
                        )
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

                if st_adjusting:
                    ss.checked = True

                if ss_adjustqty and ss_adjustreason:
                    ss.checked = True
                    with td.s.no_autoflush:
                        adjustment = (
                            td.s.get(StockTakeAdjustment,
                                     (stocktake.id, ss.stock_id,
                                      ss_adjustreason.id))
                            or StockTakeAdjustment(
                                snapshot=ss, removecode=ss_adjustreason,
                                qty=Decimal(0))
                        )
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

    return ('stocktake-in-progress.html', {
        'tillobject': stocktake,
        'stocktake': stocktake,
        'stocktypes': stocktypes,
        'finishcodes': finishcodes,
        'removecodes': removecodes,
        'default_adjustreason': default_adjustreason,
        'form': form,
    })
