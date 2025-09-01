from decimal import Decimal
from django.http import Http404
from django.http import HttpResponseRedirect
from django.http import HttpResponseForbidden
from django.http import JsonResponse
from django import forms
from django.contrib import messages
from sqlalchemy import inspect
from sqlalchemy.sql import desc
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import undefer
import sqlalchemy.exc
from quicktill.models import StockType
from quicktill.models import StockTake
from quicktill.models import StockItem
from quicktill.models import StockTakeSnapshot
from quicktill.models import StockTakeAdjustment
from quicktill.models import FinishCode
from quicktill.models import RemoveCode
from quicktill.models import qty_max_digits, qty_decimal_places

from .views import tillweb_view
from .views import td
from .views import user
from .forms import StringIDChoiceField


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
                    .options(undefer(StockTake.snapshot_count))\
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
        st.summary_adjustments = {rc: st.unit.format_stock_qty(qty)
                                  for rc, qty in st.adjustments.items()}
        st.detail_adjustments = {rc: st.unit.format_adjustment_qty(qty)
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
    st_id = stocktake.id
    may_edit = info.user_has_perm('stocktake')

    # The page may POST on a checkbox being toggled or a new
    # finishcode being selected for a stocktype or a stock item; deal
    # with these as quickly as possible here
    if may_edit and request.method == 'POST' and (
            "toggle-item-checked" in request.POST
            or "item-finish" in request.POST):
        item = request.POST["item-id"]
        if item.startswith("si"):
            stockid = int(item[2:])
            snapshots = [td.s.query(StockTakeSnapshot).get(
                (st_id, stockid))]
        elif item.startswith("st"):
            stocktype_id = int(item[2:])
            snapshots = \
                td.s.query(StockTakeSnapshot)\
                    .join(StockItem)\
                    .filter(StockTakeSnapshot.stocktake_id == st_id)\
                    .filter(StockItem.stocktype_id == stocktype_id)\
                    .all()
        else:
            return JsonResponse({
                "error": f"bad item-id parameter '{item}'",
            })
        if not snapshots:
            return JsonResponse({
                "error": f"{item} not in stock take",
            })
        if "toggle-item-checked" in request.POST:
            checked = all(ss.checked for ss in snapshots)
            for ss in snapshots:
                ss.checked = not checked
            td.s.commit()
            return JsonResponse({"checked": not checked})
        if "item-finish" in request.POST:
            for ss in snapshots:
                ss.checked = True
                ss.finishcode_id = request.POST["finishcode"] or None
            td.s.commit()
            return JsonResponse({"checked": True})

    # We want to end up with a list of stocktypes that have snapshots
    # in this stocktake.  This could possibly be done as a query for
    # StockType and StockTakeSnapshot suitably joined and filtered,
    # but it's going to be simpler and faster to query snapshots (with
    # a joinedload of their adjustments) and then process to obtain
    # the list of stocktypes.

    finishcodes = td.s.query(FinishCode).all()

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
                            bestbefore=si.bestbefore,
                            newbestbefore=si.bestbefore,
                            finishcode=si.finishcode))
                        try:
                            td.s.commit()
                            messages.success(
                                request,
                                f"Stock item {new_stockid} [{si.stocktype}] "
                                "added to stock take.")
                        except sqlalchemy.exc.IntegrityError:
                            td.s.rollback()
                            messages.error(
                                request,
                                f"Stock item {new_stockid} [{si.stocktype}] "
                                f"is already present in this stock take.")
                    else:
                        messages.error(
                            request,
                            f"Stock item {new_stockid} [{si.stocktype}] is "
                            "not in scope for this stock take.")
                else:
                    messages.error(
                        request,
                        f"Stock item {new_stockid} does not exist")

        if 'submit_abandon' in request.POST:
            checked = any(ss.checked for ss in snapshots)
            if checked:
                messages.error(
                    request,
                    "You must uncheck all items before you "
                    "can abandon this stock take.")
            else:
                user.log(
                    f"Abandoned stock take in progress {stocktake.logref}")
                messages.success(
                    request, f"Stock take {stocktake.id} abandoned.")
                td.s.delete(stocktake)
                td.s.commit()
                return HttpResponseRedirect(info.reverse("tillweb-stocktakes"))

        if 'submit_finish' in request.POST:
            unchecked = any(not ss.checked for ss in snapshots)
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
        'form': form,
    })


class StockAdjustmentForm(forms.Form):
    def __init__(self, *args, unit=None, **kwargs):
        super().__init__(*args, **kwargs)
        if unit is not None:
            self.fields["adjust_to"].label += \
                f" (in {unit.stock_unit_name_plural})"

    waste_type = StringIDChoiceField(
        RemoveCode, 'id',
        query_filter=lambda x: x.order_by(RemoveCode.reason)
        .filter(RemoveCode.id != 'sold'),
        empty_label="Choose the type of waste to record",
        required=True,
    )
    adjust_to = forms.DecimalField(
        max_digits=qty_max_digits, decimal_places=qty_decimal_places,
        required=False, label="Adjust qty in stock to",
    )


class StockItemAdjustmentForm(StockAdjustmentForm):
    note = forms.CharField(required=False)
    best_before = forms.DateField(required=False)


@tillweb_view
def stockitem_detail(request, info, stocktake_id, stock_id):
    ss = td.s.get(StockTakeSnapshot, (stocktake_id, stock_id), options=[
        undefer(StockTakeSnapshot.newqty),
        joinedload(StockTakeSnapshot.adjustments),
        joinedload(StockTakeSnapshot.stockitem)
        .joinedload(StockItem.stocktype)
        .joinedload(StockType.unit),
        joinedload(StockTakeSnapshot.stockitem)
        .joinedload(StockItem.stockline),
        joinedload(StockTakeSnapshot.stocktake),
    ])
    if not ss:
        raise Http404
    stocktake = ss.stocktake
    if stocktake.state != "in progress":
        return HttpResponseRedirect(stocktake.get_absolute_url())
    if not info.user_has_perm('stocktake'):
        return HttpResponseRedirect(stocktake.get_absolute_url())

    if request.method == 'POST':
        form = StockItemAdjustmentForm(
            request.POST, unit=ss.stockitem.stocktype.unit)
        if form.is_valid():
            cd = form.cleaned_data
            ss.checked = True
            ss.note = cd["note"]
            ss.newbestbefore = cd["best_before"]
            if "submit_adjust" in request.POST \
               and cd["waste_type"] and cd["adjust_to"] is not None:
                try:
                    # Convert from stock units to base units
                    ss_adjustqty = cd["adjust_to"] * \
                        ss.stockitem.stocktype.unit.base_units_per_stock_unit
                    # Convert between absolute adjustment and relative
                    ss_adjustqty = ss.newqty - ss_adjustqty
                except Exception:
                    ss_adjustqty = None
                with td.s.no_autoflush:
                    adjustment = (
                        td.s.get(StockTakeAdjustment,
                                 (stocktake.id, ss.stock_id,
                                  cd["waste_type"].id))
                        or StockTakeAdjustment(
                            snapshot=ss, removecode=cd["waste_type"],
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
            if "submit_reset" in request.POST:
                ss.checked = False
                ss.newbestbefore = ss.bestbefore
                ss.newdisplayqty = ss.displayqty
                ss.note = ""
                td.s.query(StockTakeAdjustment)\
                    .filter(StockTakeAdjustment.snapshot == ss)\
                    .delete()
            td.s.commit()
            return HttpResponseRedirect(
                stocktake.get_absolute_url() + f"#si{ss.stockitem.id}")
    else:
        form = StockItemAdjustmentForm(
            unit=ss.stockitem.stocktype.unit,
            initial={
                "note": ss.note,
                "waste_type": "missing",  # XXX should be a config option
                "best_before": ss.newbestbefore,
            })

    return ('stocktake-stockitem-detail.html', {
        'tillobject': ss,
        'stocktake': stocktake,
        'ss': ss,
        'form': form,
    })


@tillweb_view
def stocktype_detail(request, info, stocktake_id, stocktype_id):
    # Fetch all the snapshots of this stocktype
    snapshots = td.s.query(StockTakeSnapshot)\
                    .join(StockItem)\
                    .options(
                        undefer(StockTakeSnapshot.newqty),
                        joinedload(StockTakeSnapshot.adjustments),
                        joinedload(StockTakeSnapshot.stockitem)
                        .joinedload(StockItem.stocktype)
                        .joinedload(StockType.unit),
                        joinedload(StockTakeSnapshot.stockitem)
                        .joinedload(StockItem.stockline),
                        joinedload(StockTakeSnapshot.stocktake))\
                    .filter(StockTakeSnapshot.stocktake_id == stocktake_id)\
                    .filter(StockItem.stocktype_id == stocktype_id)\
                    .all()

    # stocktake and stocktype should now be in the orm session if there
    # were any snapshots
    stocktake = td.s.get(StockTake, stocktake_id)
    if not stocktake:
        raise Http404
    if stocktake.state != "in progress":
        return HttpResponseRedirect(stocktake.get_absolute_url())
    if not info.user_has_perm('stocktake'):
        return HttpResponseRedirect(stocktake.get_absolute_url())

    stocktype = td.s.get(StockType, stocktype_id)
    if not stocktype:
        raise Http404

    # Must be in scope for this stock take
    if stocktype.stocktake != stocktake:
        raise Http404

    # Annotate the stocktype with snapshots and adjustments
    _snapshots_to_stocktypes(snapshots)

    if request.method == 'POST':
        form = StockAdjustmentForm(request.POST, unit=stocktype.unit)
        if form.is_valid():
            cd = form.cleaned_data
            if "submit_adjust" in request.POST \
               and cd["waste_type"] and cd["adjust_to"] is not None:
                st_adjustqty = stocktype.snapshot_newqty
                try:
                    # Convert from stock units to base units
                    st_adjustqty = cd["adjust_to"] * \
                        stocktype.unit.base_units_per_stock_unit
                    # Convert between absolute adjustment and relative
                    st_adjustqty = stocktype.snapshot_newqty - st_adjustqty
                except Exception:
                    pass
                st_adjustreason = cd["waste_type"]
                for ss in stocktype.snapshots:
                    # We are making a whole-stocktype adjustment: ensure
                    # we check each stockitem of the stocktype, even those
                    # that don't end up being adjusted
                    ss.checked = True
                    with td.s.no_autoflush:
                        adjustment = (
                            td.s.get(StockTakeAdjustment,
                                     (stocktake.id, ss.stock_id,
                                      st_adjustreason.id))
                            or StockTakeAdjustment(
                                removecode=st_adjustreason,
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
                    adjustment.qty = adjustment.qty + adjust_by
                    st_adjustqty -= adjust_by
                    if adjustment.qty == Decimal(0):
                        i = inspect(adjustment)
                        if i.persistent:
                            td.s.delete(adjustment)
                        elif i.pending:
                            td.s.expunge(adjustment)
                    else:
                        adjustment.snapshot = ss
                        td.s.add(adjustment)
            if "submit_reset" in request.POST:
                for ss in stocktype.snapshots:
                    ss.checked = False
                    td.s.query(StockTakeAdjustment)\
                        .filter(StockTakeAdjustment.snapshot == ss)\
                        .delete()
            td.s.commit()
            return HttpResponseRedirect(
                stocktake.get_absolute_url() + f"#st{stocktype.id}")
    else:
        form = StockAdjustmentForm(unit=stocktype.unit, initial={
            "waste_type": "missing",  # XXX should be a config option
        })

    return ('stocktake-stocktype-detail.html', {
        'tillobject': stocktake,
        'stocktake': stocktake,
        'stocktype': stocktype,
        'form': form,
        'nav': stocktake.tillweb_nav() + [
            (stocktype.format(), stocktype.get_view_url(
                "tillweb-stocktake-stocktype",
                stocktake_id=stocktake.id,
                stocktype_id=stocktype.id))],
    })
