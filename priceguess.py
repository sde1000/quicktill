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
    if abv<3.2:
        return 1.70
    if abv<3.6:
        return 1.80
    if abv<4.0:
        return 1.90
    if abv<4.4:
        return 2.00
    if abv<4.9:
        return 2.10
    if abv<5.3:
        return 2.20
    if abv<5.7:
        return 2.30
    if abv<6.0:
        return 2.40
    return None

def guesssnack(cost):
    return math.ceil(cost*2.0*1.175*10.0)/10.0
