# Guess the selling price for a unit of a stock item given its type,
# cost price/unit and ABV.  Return None if we don't have a decent
# guess.

import math

def guess(dept,cost,abv):
    if dept==1:
        return guessbeer(cost,abv)
    if dept==2:
        return 2.50
    if dept==3:
        return 2.40
    if dept==5:
        return guesssnack(cost)
    return None

# Unit is a pint
def guessbeer(cost,abv):
    if abv is None: return None
    if abv<3.2: r=1.70
    elif abv<3.6: r=1.80
    elif abv<4.0: r=1.90
    elif abv<4.4: r=2.00
    elif abv<4.9: r=2.10
    elif abv<5.3: r=2.20
    elif abv<5.7: r=2.30
    elif abv<6.0: r=2.40
    else: return None
    # If the cost per pint is greater than that of Milton plus fiddle-factor,
    # add on the excess and round up to nearest 10p
    idealcost=((abv*10.0)+13.0)/72.0
    if cost>idealcost:
        r=r+cost-idealcost
        r=math.ceil(r*10.0)/10.0
    return r

def guesssnack(cost):
    return math.ceil(cost*2.0*1.175*10.0)/10.0
