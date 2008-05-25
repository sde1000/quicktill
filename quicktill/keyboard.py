# Keycodes
fixed_keycodes=(
    # Pages
    "ALICE","BOB","CHARLIE","DORIS","EDDIE","FRANK","GILES","HELEN",
    "IAN","JANE","KATE","LIZ","MALLORY","NIGEL","OEDIPUS",
    
    # Till management keys
    "USESTOCK","MANAGESTOCK","WASTE","MANAGETILL","CANCEL",
    "CLEAR","PRICECHECK","PRINT","RECALLTRANS","MANAGETRANS","QUANTITY",
    "HALF","DOUBLE","4JUG","FOODORDER","CANCELFOOD","EXTRAS",

    # Numeric keypad
    "ONE","TWO","THREE","FOUR","FIVE","SIX","SEVEN","EIGHT","NINE","TEN",
    "ZERO","ZEROZERO","POINT",
    
    # Cursor keys
    "LEFT","RIGHT","UP","DOWN",

    # Tendering keys
    "CASH","CARD","CHEQUE","VOUCHER","TWENTY","TENNER","FIVER","DRINKIN",

    # Magnetic stripe metakeys
    "M1H","M1T","M2H","M2T","M3H","M3T"
    )

numdepts=20
numlines=100

__all__=["kcnames","notes","numberkeys","depts"]

kcnames={}
keycodes={}
def add_keycode(name,num):
    add_keycode.func_globals[name]=num
    __all__.append(name)
    keycodes[name]=num
    kcnames[num]=name

kc=1001
for i in fixed_keycodes:
    add_keycode('K_'+i,kc)
    kc=kc+1
depts={}
for i in range(1,numdepts+1):
    add_keycode('K_DEPT%d'%i,kc)
    depts[kc]=i
    kc=kc+1
lines={}
for i in range(1,numlines+1):
    add_keycode('K_LINE%d'%i,kc)
    lines[kc]=i
    kc=kc+1

notes={
    K_FIVER: 500,
    K_TENNER: 1000,
    K_TWENTY: 2000,
    }

numberkeys=(
    K_ONE, K_TWO, K_THREE, K_FOUR, K_FIVE,
    K_SIX, K_SEVEN, K_EIGHT, K_NINE, K_ZERO,
    K_ZEROZERO, K_POINT)

del numdepts,numlines,i,kc,fixed_keycodes,add_keycode
