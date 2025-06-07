from quicktill.foodorder import simplemenu, subopts
from quicktill.models import zero, penny
from decimal import Decimal, ROUND_UP

footer = "This is a footer"
dept = 10


def staffdiscount(tablenumber, item):
    if tablenumber != 1234:
        return zero
    discount = item.price * Decimal("0.4")
    if discount > Decimal("3.00"):
        discount = Decimal("3.00")
    discount = discount.quantize(Decimal("0.1"), rounding=ROUND_UP)
    discount = discount.quantize(penny)
    return discount


class ices(subopts):
    """A special version of the subopts class that understands how
    ice-cream is priced.  It's very simple: ice cream costs 3 pounds
    for two scoops, and 1 pound for every extra scoop.
    """
    def __init__(self, options):
        # We initialise the subopts class with zero prices for the
        # item and all its suboptions; this is because we override the
        # "price" method below.
        super().__init__("Ice Cream / Sorbet", 0.00,
                         [(x, 0.00) for x in options],
                         atleast=1, nameconnector=": ",
                         connector=", ")

    def price(self, chosen_options):
        # Find out how many scoops were entered.
        scoops = len(chosen_options)
        # All scoops after number 2 are considered "extra" - how many of
        # these are there?  The max() function is used to make sure we
        # don't end up with a negative number of extra scoops!
        extrascoops = max(scoops - 2, 0)
        # Finally, calculate the price
        return 3.00 + (1.00 * extrascoops)


# A convenience function that saves some typing for the common case where
# you want to specify some options for a dish that don't affect its price.
# "options" is a list of strings.
def with_options(name, price, options):
    return (name,
            subopts(name, price, [(x, 0.00) for x in options],
                    connector=", ", nameconnector=" "))


lunchPloughmans = simplemenu(
    [
        ("Lunch menu: Cheddar Ploughmans", 4.20),
        ("Lunch menu: Stilton Ploughmans", 4.20),
    ], title="Ploughmans")

lunchOmelette = simplemenu(
    [
        ("Lunch menu: Cheese Omelette", 4.20),
        ("Lunch menu: Tomato Omelette", 4.20),
        ("Lunch menu: Mushroom Omelette", 4.20),
    ], title="Omelettes")

lunchmenu = simplemenu(
    [
        ("Lunch menu: Soup", 3.50),
        ("Lunch menu: Pork Pie", 4.20),
        ("Lunch menu: Salmon and Egg", 4.20),
        ("Lunch menu: Beef Burger", 4.20),
        ("Lunch menu: Ploughman's", lunchPloughmans),
        ("Lunch menu: Sausages", 4.20),
        ("Lunch menu: Eggs Benedict", 4.20),
        ("Lunch menu: Chicken Salad", 4.20),
        ("Lunch menu: Omelette", lunchOmelette),
    ], title="Lunch menu")

starters = simplemenu(
    [
        ("Carrot & Coriander Soup", 3.50),
        ("Pork Pie and Salad", 4.50),
        ("Smoked Trout Salad", 4.50),
        ("Chicken Pasty", 4.50),
        ("Chorizo & Artichoke Salad", 4.50),
    ], title="Starters")

steak = simplemenu(
    [
        ("Blue Steak", 10.50),
        ("Rare Steak", 10.50),
        ("Medium Rare Steak", 10.50),
        ("Medium Steak", 10.50),
        ("Medium Well Done Steak", 10.50),
        ("Well Done Steak", 10.50),
        ("Charcoal Steak", 10.50),
    ], title="Steak")

sausages = subopts(
    "Sausages", 7.50,
    [
        ("Cumberland", 0.00),
        ("Pork & Leek", 0.00),
        ("Boerwars", 0.00),
    ], atmost=3, atleast=1, connector=", ")

maincourses = simplemenu(
    [
        with_options(
            "Ploughman's", 7.50,
            ["without Ardrahan", "without Stilton", "without Golden Cross",
             "without Cheddar", "with Ardrahan instead", "with Stilton instead",
             "with Golden Cross instead", "with Cheddar instead",
             "filler", "filler 2", "filler 3", "filler 4", "filler 5",
             "filler 6"]),
        ("Nut Burger", 7.50),
        ("Sausages", sausages),
        ("Beef Burger", 7.50),
        ("Lamb & Apricot Stew", 7.50),
        ("Tagliatelle", 7.50),
        ("Aubergine Bake", 7.50),
        ("Beef & Rauchbier Pie", 8.50),
        with_options("Grey Mullet Fillet", 8.50, ["with chips instead"]),
        ("Steak", steak),
    ], title="Main courses")

snacks = simplemenu(
    [
        ("Bowl of chips", 2.50),
        ("Bowl of olives", 1.50),
    ], title="Snacks")

# This makes use of the "ices" class defined at the top of this file.
icecream = ices(["Vanilla", "Chocolate", "Strawberry", "Chilli",
                 "Lemon", "Mango", "Blackcurrant"])

desserts = simplemenu(
    [
        ("Fruit Salad", 3.50),
        ("Ice Cream", icecream),
        ("Banana and Toffee Pancakes", 4.50),
        ("Chocolate Fudge Cake", 4.50),
        ("Treacle Sponge", 4.50),
        ("Apple Pie", 4.50),
        ("Apple & Blackberry Pie", 4.50),
        ("Cheese & Biscuits", 7.50),
    ], title="Desserts")

# We're going to do something special here so that we don't have to
# type in the list of fillings twice.
sandwichfillings = [
    "Tuna Mayo", "Ham & Mustard", "Cheddar & Onion",
    "Stilton", "Roast Chicken", "Sausage", "BLT"]

sandwiches = simplemenu(
    [
        ("White bread",
         simplemenu([("%s on white bread" % filling, 3.50)
                     for filling in sandwichfillings],
                    title="Sandwiches")),
        ("Malted grain bread",
         simplemenu([("%s on malted grain bread" % filling, 3.50)
                     for filling in sandwichfillings],
                    title="Sandwiches")),
    ], title="Sandwiches")

jackets = subopts(
    "Jacket potato", 3.25,
    [
        ("Tuna Mayo", 0.75),
        ("Bacon", 0.75),
        ("Stilton", 0.75),
        ("Cheddar", 0.75),
        ("Ham", 0.75),
        ("Baked Beans", 0.75),
        ("More", [("More 1", 0.01), ("More 2", 0.02)]),
    ], connector=", ", nameconnector=" with ", atleast=1)

courses = simplemenu(
    [
        ("First course...", 0.00),
        ("Second course...", 0.00),
        ("Third course...", 0.00),
        ("More to come...", 0.00),
        ("Special instructions", 0.00),
        # Extra options to test that this is correctly spilled into a menu
        # rather than a keymenu when we run out of numeric keypad keys:
        ("Six...", 0.00),
        ("Seven...", 0.00),
        ("Eight...", 0.00),
        ("Nine...", 0.00),
        ("Ten...", 0.00),
        ("Eleven...", 0.00),
        ("Twelve...", 0.00),
    ])

roast = simplemenu(
    [
        ("Roast Chicken", 7.50),
        ("Roast Lamb", 7.50),
        ("Nut Roast", 7.50),
    ], title="Sunday Roast")

menu = [
    ('Lunch menu', lunchmenu),
    ('Starters', starters),
    ('Main courses', maincourses),
    # ('Sunday Roast', roast),
    ('Snacks', snacks),
    ('Desserts', desserts),
    ('Sandwiches', sandwiches),
    ('Jacket potatos', jackets),
    ('Courses / misc', courses),
    ("more", 0.00),
    ("more", 0.00),
    ("more", 0.00),
    ("more", 0.00),
]
