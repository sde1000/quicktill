# -*- coding: iso-8859-1 -*-

# Keycodes

K_ALICE=1001
K_BOB=1002
K_CHARLIE=1003
K_DAVE=1004
K_EDWARD=1005
K_FRED=1006
K_GILL=1007
K_HELEN=1008
K_IVY=1009
K_JANET=1010
K_KEITH=1011
K_LARRY=1012
K_MARY=1013
K_NICK=1014

K_USESTOCK=1051
K_MANAGESTOCK=1052
K_WASTE=1053
K_MANAGETILL=1054
K_CANCEL=1055
K_CLEAR=1056
K_PRICECHECK=1057
K_PRINT=1058
K_RECALLTRANS=1059

K_PINT1=1061
K_PINT2=1062
K_PINT3=1063
K_PINT4=1064
K_PINT5=1065
K_PINT6=1066
K_PINT7=1067
K_PINT8=1068
K_PINTLAGER=1069
K_PINTCIDER=1070

K_HALF1=1071
K_HALF2=1072
K_HALF3=1073
K_HALF4=1074
K_HALF5=1075
K_HALF6=1076
K_HALF7=1077
K_HALF8=1078
K_HALFLAGER=1079
K_HALFCIDER=1080

K_SPIRITS=1091
K_MISC=1092
K_WINE=1093
K_SOFT=1094
K_FOOD=1095
K_BOTTLES=1096

K_ONE=1101
K_TWO=1102
K_THREE=1103
K_FOUR=1104
K_FIVE=1105
K_SIX=1106
K_SEVEN=1107
K_EIGHT=1108
K_NINE=1109
K_ZERO=1110
K_ZEROZERO=1111
K_POINT=1112
K_QUANTITY=1113

K_LEFT=1121
K_RIGHT=1122
K_UP=1123
K_DOWN=1124

K_CASH=1131
K_TWENTY=1132
K_TENNER=1133
K_FIVER=1134

K_PLAINCRISPS=1141
K_CHEESEANDONION=1142
K_SALTANDVINEGAR=1143
K_SALTANDPEPPER=1144
K_ROASTOX=1145
K_SALTEDNUTS=1146
K_DRYROASTNUTS=1147
K_CHILLINUTS=1148
K_FRUITANDNUTS=1149
K_HONEYNUTS=1150
K_PISTACHIONUTS=1151
K_TWIGLETS=1152
K_MINICHEDDARS=1153
K_WHEATCRUNCHIES=1154
K_PICKLES=1155
K_SCAMPIFRIES=1156
K_BACONFRIES=1157
K_CHEESEMOMENTS=1158
K_PORKSCRATCHINGS=1159
K_PEPERAMI=1160
K_CHOCOLATE=1161
K_COCKLES=1162

# For each key on the keyboard we record
# (location, legend, keycode)
layout=(
    ("G01","Alice",K_ALICE),
    ("F01","Bob",K_BOB),
    ("E01","Charlie",K_CHARLIE),
    ("C01","Clear",K_CLEAR),
    ("D01","Cancel",K_CANCEL),
    ("D02","Use Stock",K_USESTOCK),
    ("C02","Manage Stock",K_MANAGESTOCK),
    ("D03","Record Waste",K_WASTE),
    ("C03","Manage Till",K_MANAGETILL),
    ("G02","Print",K_PRINT),
    ("F02","Recall Trans",K_RECALLTRANS),
    ("E02","Price Check",K_PRICECHECK),
    ("C07","Left",K_LEFT),
    ("D08","Up",K_UP),
    ("C08","Down",K_DOWN),
    ("C09","Right",K_RIGHT),
    ("C10",".",K_POINT),
    ("C11","0",K_ZERO),
    ("C12","00",K_ZEROZERO),
    ("D10","1",K_ONE),
    ("D11","2",K_TWO),
    ("D12","3",K_THREE),
    ("E10","4",K_FOUR),
    ("E11","5",K_FIVE),
    ("E12","6",K_SIX),
    ("F10","7",K_SEVEN),
    ("F11","8",K_EIGHT),
    ("F12","9",K_NINE),
    ("D09","Quantity",K_QUANTITY),
    ("B11","Cash/Enter",K_CASH),
    ("G10","£20",K_TWENTY),
    ("G11","£10",K_TENNER),
    ("G12","£5",K_FIVER),
    ("A01","Pint 1",K_PINT1),
    ("A02","Pint 2",K_PINT2),
    ("A03","Pint 3",K_PINT3),
    ("A04","Pint 4",K_PINT4),
    ("A05","Pint 5",K_PINT5),
    ("A06","Pint 6",K_PINT6),
    ("A07","Pint 7",K_PINT7),
    ("A08","Pint 8",K_PINT8),
    ("A09","Pint Lager",K_PINTLAGER),
    ("A10","Pint Cider",K_PINTCIDER),
    ("B01","Half 1",K_HALF1),
    ("B02","Half 2",K_HALF2),
    ("B03","Half 3",K_HALF3),
    ("B04","Half 4",K_HALF4),
    ("B05","Half 5",K_HALF5),
    ("B06","Half 6",K_HALF6),
    ("B07","Half 7",K_HALF7),
    ("B08","Half 8",K_HALF8),
    ("B09","Half Lager",K_HALFLAGER),
    ("B10","Half Cider",K_HALFCIDER),
    ("G08","Spirits",K_SPIRITS),
    ("G09","Misc",K_MISC),
    ("F08","Wine",K_WINE),
    ("F09","Soft",K_SOFT),
    ("E08","Food",K_FOOD),
    ("E09","Bottles",K_BOTTLES),
    ("G03","Plain Crisps",K_PLAINCRISPS),
    ("G04","Cheese & Onion",K_CHEESEANDONION),
    ("G05","Salt & Vinegar",K_SALTANDVINEGAR),
    ("G06","Salt & Pepper",K_SALTANDPEPPER),
    ("G07","Roast Ox Crisps",K_ROASTOX),
    ("F03","Salted Nuts",K_SALTEDNUTS),
    ("F04","Dry Roast Nuts",K_DRYROASTNUTS),
    ("F05","Chilli Nuts",K_CHILLINUTS),
    ("F06","Fruit & Nuts",K_FRUITANDNUTS),
    ("F07","Honey Nuts",K_HONEYNUTS),
    ("E03","Pistachio Nuts",K_PISTACHIONUTS),
    ("E04","Twiglets",K_TWIGLETS),
    ("E05","Mini Cheddars",K_MINICHEDDARS),
    ("E06","Wheat Crunchies",K_WHEATCRUNCHIES),
    ("E07","Pickles",K_PICKLES),
    ("D04","Scampi Fries",K_SCAMPIFRIES),
    ("D05","Bacon Fries",K_BACONFRIES),
    ("D06","Cheese Moments",K_CHEESEMOMENTS),
    ("D07","Pork Scratchings",K_PORKSCRATCHINGS),
    ("C04","Peperami",K_PEPERAMI),
    ("C05","Chocolate",K_CHOCOLATE),
    ("C06","Cockles",K_COCKLES),
)

# How keys correspond to lines and quantities; if a list is given then
# pressing the key yields a pop-up menu of lines

lines={
    K_PINT1:('Pump 1',1,1),
    K_PINT2:('Pump 2',1,1),
    K_PINT3:('Pump 3',1,1),
    K_PINT4:('Pump 4',1,1),
    K_PINT5:('Pump 5',1,1),
    K_PINT6:('Pump 6',1,1),
    K_PINT7:('Pump 7',1,1),
    K_PINT8:('Pump 8',1,1),
    K_PINTLAGER:('Lager',1,2),
    K_PINTCIDER:('Cider',1,3),
    K_HALF1:('Pump 1',0.5,1),
    K_HALF2:('Pump 2',0.5,1),
    K_HALF3:('Pump 3',0.5,1),
    K_HALF4:('Pump 4',0.5,1),
    K_HALF5:('Pump 5',0.5,1),
    K_HALF6:('Pump 6',0.5,1),
    K_HALF7:('Pump 7',0.5,1),
    K_HALF8:('Pump 8',0.5,1),
    K_HALFLAGER:('Lager',0.5,2),
    K_HALFCIDER:('Cider',0.5,3),

    K_PLAINCRISPS:('Plain Crisps',1,5),
    K_CHEESEANDONION:('Cheese and Onion Crisps',1,5),
    K_SALTANDVINEGAR:('Salt and Vinegar Crisps',1,5),
    K_SALTANDPEPPER:('Salt and Pepper Crisps',1,5),
    K_ROASTOX:('Roast Ox Crisps',1,5),
    K_SALTEDNUTS:('Salted Nuts',1,5),
    K_DRYROASTNUTS:('Dry Roast Nuts',1,5),
    K_CHILLINUTS:('Chilli Nuts',1,5),
    K_FRUITANDNUTS:('Mixed Fruit and Nuts',1,5),
    K_HONEYNUTS:('Honey Nuts',1,5),
    K_PISTACHIONUTS:('Pistachio Nuts',1,5),
    K_TWIGLETS:('Twiglets',1,5),
    K_MINICHEDDARS:('Mini Cheddars',1,5),
    K_WHEATCRUNCHIES:('Wheat Crunchies',1,5),
    K_PICKLES:[('Pickled Eggs',1,5),('Pickled Onions',1,5)],
    K_SCAMPIFRIES:('Scampi Fries',1,5),
    K_BACONFRIES:('Bacon Fries',1,5),
    K_CHEESEMOMENTS:('Cheese Moments',1,5),
    K_PORKSCRATCHINGS:('Pork Scratchings',1,5),
    K_PEPERAMI:('Green Peperami',1,5),
    K_CHOCOLATE:('Chocolate',1,5),
    K_COCKLES:('Cockles',1,5),
}

depts={
    K_SPIRITS: 4,
    K_MISC: 8,
    K_WINE: 9,
    K_SOFT: 7,
    K_FOOD: 10,
    K_BOTTLES: 6,
    }

notes={
    K_FIVER: 500,
    K_TENNER: 1000,
    K_TWENTY: 2000,
    }

# Used for menus, etc.
numberkeys=(
    K_ONE, K_TWO, K_THREE, K_FOUR, K_FIVE,
    K_SIX, K_SEVEN, K_EIGHT, K_NINE, K_ZERO,
    K_ZEROZERO, K_POINT)
