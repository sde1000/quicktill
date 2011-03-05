#!/bin/bash

set -e

db=$1

echo "Sanity checks for ${db}:"

psql ${db} <<EOF
\echo Stocktypes with missing ABVs:
SELECT stocktype,dept,manufacturer,name,shortname,abv,unit 
FROM stocktypes WHERE abv IS NULL AND dept IN (1,2,3,4,6,9)
ORDER BY dept,manufacturer,name;

\echo Unused stock lines:
SELECT * FROM stocklines WHERE stocklineid NOT IN (
 SELECT stocklineid FROM stockonsale) ORDER BY dept,location,name;

\echo Stock on sale that has not sold recently:
SELECT stockid,manufacturer,name,to_char(onsale,'YYYY-MM-DD') AS onsale,
size-used AS remaining,
to_char((SELECT max(time) FROM stockout so WHERE so.stockid=si.stockid),'YYYY-MM-DD') AS lastused
FROM stockinfo si WHERE si.onsale IS NOT NULL AND finished IS NULL
AND ((SELECT max(time) FROM stockout so WHERE so.stockid=si.stockid)+'7 days')<now()
ORDER BY lastused;

\echo Stocktypes in stock and not on sale:
SELECT * FROM stocktypes st WHERE st.stocktype NOT IN (
 SELECT stocktype FROM stockonsale sos LEFT JOIN stock s 
 ON s.stockid=sos.stockid) AND st.stocktype IN (
 SELECT stocktype FROM stock WHERE finished IS NULL)
ORDER BY dept,manufacturer,name;

\echo Unused stocktypes:
SELECT * FROM stocktypes WHERE stocktype NOT IN (
 SELECT stocktype FROM stock);

\echo Stock lines with 'capacity' that probably should not have it:
SELECT * FROM stocklines WHERE capacity IS NOT NULL AND dept IN (1,2,3,4);

\echo Stock lines with 'pullthru' that probably should not have it:
SELECT * FROM stocklines WHERE pullthru IS NOT NULL AND dept NOT IN (1,2,3);

\echo Closed sessions that have no takings recorded:
SELECT * FROM sessions WHERE endtime IS NOT NULL AND sessionid NOT IN (
 SELECT sessionid FROM sessiontotals) ORDER BY sessionid;

EOF
