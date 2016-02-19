quicktill — cash register software
==================================

Upgrade v0.11.x to v0.12
------------------------

There are major database and config file changes this release.

To upgrade the database:

 - install the new release
 - run "runtill syncdb"
 - run psql and give the following commands to the database:

```
BEGIN;
# Remove UNIQUE constraint on stockout.translineid
# Rename K_ONE to 1 etc. in keyboard.menukey
UPDATE keyboard SET menukey='1' WHERE menukey='K_ONE';
UPDATE keyboard SET menukey='2' WHERE menukey='K_TWO';
UPDATE keyboard SET menukey='3' WHERE menukey='K_THREE';
UPDATE keyboard SET menukey='4' WHERE menukey='K_FOUR';
UPDATE keyboard SET menukey='5' WHERE menukey='K_FIVE';
UPDATE keyboard SET menukey='6' WHERE menukey='K_SIX';
UPDATE keyboard SET menukey='7' WHERE menukey='K_SEVEN';
UPDATE keyboard SET menukey='8' WHERE menukey='K_EIGHT';
UPDATE keyboard SET menukey='9' WHERE menukey='K_NINE';
UPDATE keyboard SET menukey='0' WHERE menukey='K_ZERO';
UPDATE keyboard SET menukey='00' WHERE menukey='K_ZEROZERO';
UPDATE keyboard SET menukey='.' WHERE menukey='K_POINT';
COMMIT;
```

In the configuration file you must make the following changes:

 - Replace K_ONE, K_TWO, ... K_ZERO, K_ZEROZERO, K_POINT with "1",
   "2", ... "0", "00", "."
 - Rewrite modifiers to use the new interface
 - Replace ord('x') with 'x' in hotkeys


Upgrade v0.10.57 to v0.11.0
---------------------------

There are major database and config file changes this release.

To upgrade the database:

 - install the new release
 - run "runtill syncdb"
 - run psql and give the following commands to the database:
```
BEGIN;
ALTER TABLE keyboard ALTER COLUMN stocklineid DROP NOT NULL;
ALTER TABLE keyboard ADD COLUMN pluid INTEGER REFERENCES pricelookups(id) ON DELETE CASCADE;
ALTER TABLE keyboard ADD COLUMN modifier VARCHAR;
ALTER TABLE keyboard ADD CONSTRAINT "be_unambiguous_constraint" CHECK (stocklineid IS NULL OR pluid IS NULL);
ALTER TABLE keyboard ADD CONSTRAINT "be_useful_constraint" CHECK (stocklineid IS NOT NULL OR pluid IS NOT NULL OR modifier IS NOT NULL);
UPDATE keyboard SET modifier='Half' WHERE qty=0.5;
UPDATE keyboard SET modifier='Double' WHERE qty=2.0;
ALTER TABLE keyboard DROP COLUMN qty;
COMMIT;
```

In the configuration file you must make the following changes:

 - remove all modkey() definitions and replace them with line keys
 - remove the pricepolicy function
 - remove the deptkeycheck function if you have not already done so
 - add definitions for all the modifier keys you plan to use; follow
   the Haymakers example config file where possible
 - change "from quicktill.plu import popup as plu" to "from
   quicktill.pricecheck import popup as plu"
