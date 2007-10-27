from foodorder import simplemenu,subopts

# A convenience function that saves some typing for the common case where
# you want to specify some options for a dish that don't affect its price.
# "options" is a list of strings.
def with_options(name,price,options):
    return (name,
            subopts(name,price,[(x,0.00) for x in options],
                    connector=", ",nameconnector=" "))

# Another convenience function: currys all have the same options
def curry(name,price):
    return (name,
            subopts(name,price,[("extra poppadum",0.40),
                                ("no poppadum",0.00)],
                    connector=", ",nameconnector=" with "))

# Yet another, this time for burgers.  Changing this list of
# suboptions affects all the burgers.  This saves us from having to
# type it out four times!
def burger(name,price):
    return (name,
            subopts(name,price,[
        ("cheddar cheese",0.40),
        ("Other cheeses",[("cheddar cheese (not melted)",0.40),
                          ("mozzarella",0.60),
                          ("brie",0.60),
                          ("gorgonzola",0.60),
                          ("stilton",0.60)]),
        ("mushroom",0.40),
        ("egg",0.50),
        ("bacon",0.50),
        ("onion",0.00),
        ("without salad",0.00),
        ("without relish",0.00),
        ("nuclear",0.00),
        ("takeaway",0.00)],
                    connector=", ",nameconnector=" with "))
    
courses=simplemenu([
    ("First course...",0.00),
    ("Second course...",0.00),
    ("Third course...",0.00),
    ("More to come...",0.00),
    ("Special instructions",0.00),
    ])

sandwichoptions=[
    ("Cheeses",[("cheddar cheese",0.40),
                ("mozzarella",0.60,),
                ("brie",0.60),
                ("gorgonzola",0.60),
                ("stilton",0.60)]),
    ("Veg",[("pickle",0.40),
            ("onion",0.40),
            ("tomato",0.40),
            ("mushroom",0.40),
            ("olives",0.40)]),
    ("ham",0.40),
    ("bacon",0.50),
    ("fried egg",0.50),
    ("without salad",0.00),
    ("takeaway",0.00)]

sandwich=subopts("Sandwich",1.40,sandwichoptions,
                 connector=", ",nameconnector=" with ")
toastedsandwich=subopts("Toasted Sandwich",1.40,sandwichoptions,
                        connector=", ",nameconnector=" with ")

currys=simplemenu([
    curry("Beef a la Oaky",5.00),
    curry("Chicken Vindaloo",5.00),
    curry("South Indian Potatoes",4.00),
    curry("Chicken Karhai",5.00),
    curry("Gobi Korma",4.00)
    ],title="Currys")

burgers=simplemenu([
    burger("Quarter pound beef burger",2.50),
    burger("Half pound beef burger",4.00),
    burger("Quarter pound lamb burger",2.40),
    burger("Half pound lamb burger",4.00)
    ],title="Burgers")

omelette=subopts("Omelette",2.50,[
    ("Cheeses",[("cheddar cheese",0.40),
                ("mozzarella",0.60,),
                ("brie",0.60),
                ("gorgonzola",0.60),
                ("stilton",0.60)]),
    ("ham",0.40),
    ("mushrooms",0.40),
    ("onions",0.40),
    ("tomato",0.40),
    ("bacon",0.40),
    ("no salad",0.00)],
                 connector=", ", nameconnector=" with ")

steak=simplemenu([
    #("Blue Steak",7.00),
    ("Rare Steak",7.00),
    ("Medium Rare Steak",7.00),
    ("Medium Steak",7.00),
    ("Medium Well Done Steak",7.00),
    ("Well Done Steak",7.00),
    ("Charcoal Steak",7.00)],title="Steak")

menu=[
    ("Burger",burgers),
    ("Sandwich",sandwich),
    ("Toasted sandwich",toastedsandwich),
    ("Omelette",omelette),
    ("Curry",currys),
    ("Steak",steak),
    ("Pie",5.00),
    ("Big Breakfast",5.00),
    ("Courses / misc",courses),
    ]
