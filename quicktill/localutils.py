# Various region-specific utility functions
import datetime
from dateutil.easter import easter, EASTER_WESTERN
from dateutil.relativedelta import relativedelta, MO, FR

def is_england_banking_day(d):
    """Is a day a likely England banking day?

    Returns True if it is, or False if it is not.

    Not completely guaranteed to be correct; the government may insert
    or delete bank holidays at will.  Only covers bank holidays from
    1st December 2016.
    """
    # If it is a Saturday or Sunday, is definitely not a banking day
    if d.isoweekday() in (6, 7):
        return False

    # Bank holidays with fixed dates: New Years Day, Christmas Day,
    # Boxing Day
    if d.month == 1 and d.day == 1:
        return False
    if d.month == 12 and d.day == 25:
        return False
    if d.month == 12 and d.day == 26:
        return False

    # Substitute bank holidays if fixed date bank holidays fall on a
    # Saturday or Sunday
    if d.month == 1 and d.day == 2:
        if datetime.date(d.year, 1, 1).isoweekday() in (6, 7):
            return False
    if d.month == 12 and d.day == 27:
        # Bank holiday if either the 25th or 26th was a Saturday or Sunday
        if datetime.date(d.year, 12, 25).isoweekday() in (6, 7) \
           or datetime.date(d,year, 12, 26).isoweekday() in (6, 7):
            return False
    if d.month == 12 and d.day == 28:
        # Bank holiday if thr 25th was a Saturday and the 26th was a Sunday
        if datetime.date(d.year, 12, 25).isoweekday() == 6 \
           and datetime.date(d.year, 12, 26).isoweekday() == 7:
            return False

    # Good Friday and Easter Monday both depend on the date of Easter.
    easter_sunday = easter(d.year, method=EASTER_WESTERN)
    good_friday = easter_sunday - datetime.timedelta(days=2)
    easter_monday = easter_sunday + datetime.timedelta(days=1)
    if d == good_friday or d == easter_monday:
        return False

    # The early May bank holiday is the first Monday of May
    start_of_may = datetime.date(d.year, 5, 1)
    first_monday_of_may = start_of_may + relativedelta(weekday=MO)
    if d == first_monday_of_may:
        return False
    # The Spring bank holiday is the last Monday of May
    last_monday_of_may = start_of_may + relativedelta(day=31, weekday=MO(-1))
    if d == last_monday_of_may:
        return False

    # The Summer bank holiday is the last Monday of August in England,
    # Wales and Northern Ireland (and the first Monday of August in
    # Scotland, although we're not going to calculate that).
    start_of_august = datetime.date(d.year, 8, 1)
    last_monday_of_august = start_of_august \
                            + relativedelta(day=31, weekday=MO(-1))
    if d == last_monday_of_august:
        return False

    # That's it, unless the government introduce any non-standard bank
    # holidays.  If we've got this far, the day is a banking day.
    return True

def delta_england_banking_days(date, n):
    """Return the date plus a number of banking days

    Given any date, return the date of the nth banking day after it.
    """
    if n < 1:
        raise ValueError("It doesn't make sense to ask for the {}th banking "
                         "day after a date!".format(n))
    while n > 0:
        date = date + datetime.timedelta(days=1)
        if is_england_banking_day(date):
            n = n - 1
    return date
