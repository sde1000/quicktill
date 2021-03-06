quicktill — cash register software
==================================

Upgrade v18.x to v19
--------------------

What's new:

 * configuration stored in database

 * secrets stored in database

 * Xero integration updated to OAuth2 with PKCE

There are database changes this release.  The changes are not
backwards-compatible with v18, so install the new version before
making the changes.

To upgrade the database:

 - run "runtill syncdb" to create the new config table

 - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE log
	ADD COLUMN config_id character varying;

ALTER TABLE log
	ADD CONSTRAINT log_config_fkey FOREIGN KEY (config_id) REFERENCES public.config(key) ON DELETE SET NULL;

COMMIT;
```

  - run "runtill checkdb" to check that no other database changes are
    required.

If you are using the Xero integration, you must add `quicktill.xero`
to `/etc/quicktill/default-imports` to enable the xero-connect
subcommand, and edit your config file to specify a secret store for
Xero.  Run the command `runtill generate-secret-key` to generate a
suitable key for this store.  For example:

```
xapi = quicktill.xero.XeroIntegration(
    secrets=quicktill.secretstore.Secrets(
        'xero-live', b'output-of-runtill-generate-secret-key I5DI='),
    sales_contact_id=".....",
    ...)
```

After doing this, you can run the command `runtill xero-connect` to
connect the till to Xero. The first time you do this it will prompt
you to set config keys using the `runtill config` command to specify
your Xero integration client-id and tenant-id.

Upgrade v17.x to v18
--------------------

What's new:

 * stock take system

 * transaction metadata usable by register plugins

This release is somewhat premature, lacking some database model test
functions, but it's being rushed out for pub re-opening on July 4th.
Expect a lengthy v18.x series fixing small and medium size bugs!

There are database changes this release.  The changes are not
backwards-compatible with v17, so install the new version before
making the changes.

To upgrade the database:

  - run "runtill syncdb" to create the new activity log table

  - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE log
	ADD COLUMN stocktakes_id integer;

ALTER TABLE stock
	ADD COLUMN stocktake_id integer,
	ALTER COLUMN deliveryid DROP NOT NULL;

ALTER TABLE stockout
	ADD COLUMN stocktake_id integer;

ALTER TABLE stocktypes
	ADD COLUMN stocktake_id integer,
	ADD COLUMN stocktake_by_items boolean DEFAULT true NOT NULL;

ALTER TABLE log
	ADD CONSTRAINT log_stocktake_fkey FOREIGN KEY (stocktakes_id) REFERENCES public.stocktakes(id) ON DELETE SET NULL;

ALTER TABLE stock
	ADD CONSTRAINT only_one_of_delivery_or_stocktake CHECK (((deliveryid IS NULL) <> (stocktake_id IS NULL)));

ALTER TABLE stock
	ADD CONSTRAINT stock_stocktake_id_fkey FOREIGN KEY (stocktake_id) REFERENCES public.stocktakes(id);

ALTER TABLE stockout
	ADD CONSTRAINT be_unambiguous_constraint CHECK (((translineid IS NULL) OR (stocktake_id IS NULL)));

ALTER TABLE stockout
	ADD CONSTRAINT stockout_stocktake_id_fkey FOREIGN KEY (stocktake_id) REFERENCES public.stocktakes(id) ON DELETE CASCADE;

ALTER TABLE stocktypes
	ADD CONSTRAINT stocktypes_stocktake_id_fkey FOREIGN KEY (stocktake_id) REFERENCES public.stocktakes(id) ON DELETE SET NULL;

COMMIT;
```

  - run "runtill checkdb" to check that no other database changes are
    required.

Upgrade v16.x to v17
--------------------

What's new:

 * duplicate stocktypes are now prevented at the database level

 * stock annotations are removed via cascade in the database when a
   stock item is deleted

 * there is a new activity log system

**Before installing this release**, you must run "runtill
remove-duplicate-stocktypes" using v16.x to ensure that there will be
no problems during the database update.

There are database changes this release.  The changes are not
backwards-compatible with v16, so install the new version before
making the changes.

To upgrade the database:

  - run "runtill syncdb" to create the new activity log table

  - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE stock_annotations
	DROP CONSTRAINT stock_annotations_stockid_fkey;

ALTER TABLE stock_annotations
	ADD CONSTRAINT stock_annotations_stockid_fkey FOREIGN KEY (stockid) REFERENCES public.stock(stockid) ON DELETE CASCADE;

ALTER TABLE stocktypes
	ADD CONSTRAINT stocktypes_ambiguity_key UNIQUE (dept, manufacturer, name, abv, unit_id);

COMMIT;
```

  - run "runtill checkdb" to check that no other database changes are
    required.

Upgrade v15.x to v16
--------------------

What's new:

 * session notes table has been removed and replaced with 'accinfo'
   column in sessions table; this is a simplification

 * "link to accounts" buttons in the web interface for sessions and
   deliveries!

 * the way StockType.saleprice_units is handled has changed: this is
   now part of the units table.  This makes defining new types of wine
   and soft drink carton much simpler - no need for the user to enter
   "magic" sizes.

 * the StockUnits table is now a list of defaults for entering new
   stock; actual stock sizes have moved to the StockItems table.

 * the code to migrate from the old permissions system has been
   removed.

There are database changes this release.  These changes are not
backward-compatible to v15, so install the new version before making
the changes.

Modifiers declared in the configuration file must be updated:

 * if you refer to `sale.stocktype.unit_id`, refer to
   `sale.stocktype.unit.name` instead.

 * if you refer to `sale.stocktype.saleprice_units`, refer to
   `sale.stocktype.unit.units_per_item` instead.

To upgrade the database:

  - run psql and give the following commands to the database:

```
BEGIN;

/* sessions / session_notes table changes */
ALTER TABLE sessions
      ADD COLUMN accinfo character varying;

UPDATE sessions s SET accinfo=(
       SELECT text FROM session_notes n
       WHERE n.sessionid = s.sessionid
       AND time=(
         SELECT MAX(time) FROM session_notes nn
         WHERE nn.sessionid = n.sessionid
         GROUP BY n.sessionid));

DROP TABLE session_notes;

DROP SEQUENCE session_note_seq;

DROP TABLE session_note_types;

/* unittypes table changes */

CREATE SEQUENCE units_seq
       START WITH 1
       INCREMENT BY 1
       NO MAXVALUE
       NO MINVALUE
       CACHE 1;

ALTER TABLE unittypes
      ADD COLUMN id integer NOT NULL DEFAULT nextval('units_seq'),
      ADD COLUMN description character varying,
      ADD COLUMN item_name character varying,
      ADD COLUMN item_name_plural character varying,
      ADD COLUMN units_per_item numeric(8,1) NOT NULL DEFAULT 1.0,
      ALTER COLUMN name TYPE character varying USING name::character varying;

UPDATE unittypes SET description=name,
                 item_name=name,
                 item_name_plural=CONCAT(name,'s');

/* Two special entries to enable migration of wine and soft drink cartons */
INSERT INTO unittypes (unit, description, name, item_name, item_name_plural, units_per_item)
       VALUES
       ('wineml', 'Wine (bottles)', 'ml', 'bottle', 'bottles', 750),
       ('softml', 'Soft drink (cartons)', 'ml', 'pint', 'pints', 568);
UPDATE stocktypes
       SET unit = 'wineml'
       WHERE saleprice_units in (250, 750);
UPDATE stocktypes
       SET unit = 'softml'
       WHERE saleprice_units=568;
UPDATE stockunits
       SET unit='wineml' WHERE size IN (750, 4500, 9000, 20000);
UPDATE stockunits
       SET unit='softml' WHERE size IN (1000, 6000, 8000, 12000);
DELETE FROM unittypes WHERE unit='ml';

ALTER TABLE stocktypes
      ADD COLUMN unit_id integer;
UPDATE stocktypes
       SET unit_id = unittypes.id
       FROM unittypes
       WHERE stocktypes.unit = unittypes.unit;
ALTER TABLE stocktypes
      DROP CONSTRAINT stocktypes_unit_fkey,
      DROP COLUMN unit,
      ALTER COLUMN unit_id SET NOT NULL;

ALTER TABLE stockunits
      ADD COLUMN unit_id integer,
      ALTER COLUMN name TYPE character varying USING name::character varying;
UPDATE stockunits
       SET unit_id = unittypes.id
       FROM unittypes
       WHERE stockunits.unit = unittypes.unit;
ALTER TABLE stockunits
      DROP CONSTRAINT stockunits_unit_fkey,
      DROP COLUMN unit,
      ALTER COLUMN unit_id SET NOT NULL;

ALTER TABLE unittypes
      DROP CONSTRAINT unittypes_pkey,
      DROP COLUMN unit,
      ADD CONSTRAINT unittypes_pkey PRIMARY KEY (id),
      ALTER COLUMN id DROP DEFAULT,
      ALTER COLUMN description SET NOT NULL,
      ALTER COLUMN item_name SET NOT NULL,
      ALTER COLUMN item_name_plural SET NOT NULL,
      ALTER COLUMN units_per_item DROP DEFAULT;

ALTER TABLE stocktypes
      ADD CONSTRAINT stocktypes_unit_id_fkey
          FOREIGN KEY (unit_id) REFERENCES unittypes(id),
      DROP COLUMN saleprice_units;

ALTER TABLE stockunits
      ADD CONSTRAINT stockunits_unit_id_fkey
          FOREIGN KEY (unit_id) REFERENCES unittypes(id);

/* Move stockunits info into stock table */

ALTER TABLE stock
      ADD COLUMN description character varying,
      ADD COLUMN "size" numeric(8,1),
      ADD CONSTRAINT stock_size_check CHECK ((size > 0.0));

UPDATE stock
       SET description = su.name,
           size = su.size
       FROM stockunits su
       WHERE stock.stockunit = su.stockunit;

ALTER TABLE stock
      DROP COLUMN stockunit,
      ALTER COLUMN description SET NOT NULL,
      ALTER COLUMN "size" SET NOT NULL;

ALTER TABLE stockunits
      DROP CONSTRAINT stockunits_pkey;

CREATE SEQUENCE stockunits_seq
       START WITH 1
       INCREMENT BY 1
       NO MAXVALUE
       NO MINVALUE
       CACHE 1;

ALTER TABLE stockunits
      DROP COLUMN stockunit,
      ADD COLUMN "merge" boolean DEFAULT false NOT NULL,
      ADD COLUMN id integer NOT NULL DEFAULT nextval('stockunits_seq');

ALTER TABLE stockunits
      ADD CONSTRAINT stockunits_pkey PRIMARY KEY (id);

ALTER TABLE stockunits
      ALTER COLUMN id DROP DEFAULT;

/* Remove old permissions table */

DROP TABLE permission_grants;

COMMIT;
```

  - run "runtill checkdb" to check that no other database changes are
    required.

After installing this version, you may find it useful to set the
"merge" flag on wine bottles and soft drink carton stockunits, and
remove stockunits for cases of wine and soft drink cartons.

Upgrade v14.x to v15
--------------------

There are database changes this release relating to users, groups and
permissions.  The changes are not backwards-compatible with v14, so
install the new version before making the changes.

To upgrade the database:

  - run "runtill syncdb" to create new tables

  - run "runtill migrate-permissions" to migrate permissions to groups

After installing this version, you may find it useful to use the web
interface to rationalise the set of groups.

Upgrade v0.13.x to v14
----------------------

Honesty in version numbering: there will never be a version 1.0!

There are database changes this release.  The changes are
backwards-compatible with v0.13 so can be made before installing the
new version.

To upgrade the database:

  - run psql and give the following commands to the database:

```
BEGIN;
ALTER TABLE transactions
      ADD COLUMN discount_policy character varying;

ALTER TABLE translines
      ADD COLUMN discount numeric(10,2) DEFAULT 0.00 NOT NULL,
      ADD COLUMN discount_name character varying;

ALTER TABLE transactions
      ADD CONSTRAINT discount_policy_closed_constraint CHECK (((NOT closed) OR (discount_policy IS NULL)));

ALTER TABLE translines
      ADD CONSTRAINT discount_name_constraint CHECK (((discount = 0.00) = (discount_name IS NULL)));

ALTER TABLE translines
      ADD CONSTRAINT translines_discount_check CHECK ((discount >= 0.00));

COMMIT;
```

Alternatively install the new release, run "runtill checkdb" and paste
the output into psql if it looks sensible.


Upgrade v0.12.x to v0.13
------------------------

There are major database changes this release.

To upgrade the database:

 - run "runtill add-transline-text" while v0.12.x is still installed

 - install the new release

 - run "runtill syncdb"

 - run psql and give the following commands to the database:

```
BEGIN;
-- Ensure all amounts in transaction lines are non-negative
SET session_replication_role = replica;
UPDATE translines SET items=-items, amount=-amount WHERE amount<0;
SET session_replication_role = default;
ALTER TABLE translines
      ADD CONSTRAINT translines_amount_check CHECK ((amount >= 0.00));

-- Check that all transactions still balance
-- This re-runs the close_only_if_balanced trigger on all closed transactions
UPDATE transactions SET closed=true WHERE closed=true;
COMMIT;
```

 - run "runtill checkdb", check that the output looks sensible, then
   pipe it or paste it in to psql
 - run "runtill checkdb" again and check it produces no output

Upgrade v0.11.x to v0.12
------------------------

There are major database and config file changes this release.

Update the configuration file first, followed by the database.

In the configuration file you must make the following changes:

 - Replace K_ONE, K_TWO, ... K_ZERO, K_ZEROZERO, K_POINT with "1",
   "2", ... "0", "00", "."
 - Remove all deptkey() calls; deptkeys can now be expressed as PLUs
   with no price set
 - Rewrite modifiers to use the new interface
 - Replace ord('x') with 'x' in hotkeys
 - Replace usestock_hook with a subclass of usestock.UseStockHook
 - Replace priceguess with a subclass of stocktype.PriceGuessHook
 - Remove references to curseskeyboard() - they are no longer necessary

To upgrade the database:

 - install the new release
 - run "runtill syncdb"
 - run psql and give the following commands to the database:

```
BEGIN;
-- Remove UNIQUE constraint on stockout.translineid
ALTER TABLE stockout DROP CONSTRAINT stockout_translineid_key;

-- Rename K_ONE to 1 etc. in keyboard.menukey
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

-- Add NOT NULL constraint to transaction notes
UPDATE transactions SET notes='' WHERE notes IS NULL;
ALTER TABLE transactions ALTER COLUMN notes SET NOT NULL;

-- Add new columns to stocklines table and figure out line types
ALTER TABLE stocklines
	ADD COLUMN linetype character varying(20),
	ADD COLUMN stocktype integer,
	ALTER COLUMN dept DROP NOT NULL;

UPDATE stocklines SET linetype='regular' WHERE capacity IS NULL;
UPDATE stocklines SET linetype='display' WHERE capacity IS NOT NULL;
ALTER TABLE stocklines ALTER COLUMN linetype SET NOT NULL;
-- For display stocklines, guess the stocktype of the existing
-- display stock.  Display stocklines with no stock get a random stocktype,
-- which the user will have to change later.
UPDATE stocklines SET stocktype=(
  SELECT st.stocktype FROM stock s
    LEFT JOIN stocktypes st ON s.stocktype=st.stocktype
    WHERE stocklines.stocklineid=s.stocklineid
    LIMIT 1)
  WHERE linetype='display';
UPDATE stocklines SET stocktype=(
  SELECT stocktype FROM stocktypes LIMIT 1)
  WHERE linetype='display' AND stocktype IS NULL;
UPDATE stocklines SET dept=null WHERE linetype='display';

-- Add the saleprice_units column to stocktypes
ALTER TABLE stocktypes
        ADD COLUMN saleprice_units numeric(8,1);
UPDATE stocktypes SET saleprice_units=1.0;
ALTER TABLE stocktypes
        ALTER COLUMN saleprice_units SET NOT NULL;

COMMIT;
```

 - run "runtill checkdb", check that the output looks sensible, then
   pipe it or paste it in to psql
 - run "runtill checkdb" again and check it produces no output


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
