quicktill — cash register software
==================================

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
