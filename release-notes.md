quicktill — cash register software
==================================

Upgrade v24.x to v25
--------------------

What's new:

 * Sales on continuous stock lines are now faster on systems that have
   many stock items in the database

 * Stock types can now be marked as "archived", meaning that they will
   no longer show up in search results or autocompletions and it will
   not be possible to create any more stock of that type. A note field
   is supported to explain why the stock type has been archived.

To upgrade the database:

 - run psql and give the following commands to the database:

```
BEGIN;

CREATE INDEX stock_stocktype_key ON stock USING btree (stocktype);

ALTER TABLE stocktypes
	ADD COLUMN archived boolean DEFAULT false NOT NULL,
	ADD COLUMN note character varying DEFAULT ''::character varying NOT NULL;

COMMIT;
```

Upgrade v23.x to v24
--------------------

What's new:

 * Users can now set passwords, so that both a user token and password
   are required to log in to the till

 * The till can be configured to allow users to log in with a numeric
   ID and their password

To upgrade the database:

 - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE users
	ADD COLUMN password character varying;

ALTER TABLE usertokens
	ADD COLUMN last_successful_login timestamp without time zone;

COMMIT;
```

Upgrade v22.x to v23
--------------------

What's new:

 * Python 3.8 is required; Python 3.7 is no longer supported.

 * Database and logging configurations are now in TOML rather than YAML.
   See the example database configuration in `examples/dbsetup.toml`

 * The Twitter integration has been removed. A stub remains so that
   till configurations that refer to it will still load.

 * "Last seen" information is stored for each user (as opposed to each
   user token as before), and is shown in the web interface.

 * When a user moves to another terminal their session on the terminal
   they left closes immediately, rather than waiting for a timeout or
   a keypress.

 * Stock type metadata is supported, and the till web interface now
   uses this for tasting notes, product logos and product images.

 * Stock lines now support a "note" field, which is shown on the stock
   terminal and in the web interface

 * Database notifications are sent when stock levels change, which can
   be used to drive a real-time display

To upgrade the database:

 - run "runtill syncdb" to create the new stocktype metadata table
   and registers table

 - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE users
	DROP COLUMN register,
	ADD COLUMN register_id integer,
        ADD COLUMN last_seen timestamp without time zone;

ALTER TABLE users
	ADD CONSTRAINT users_register_id_fkey FOREIGN KEY (register_id) REFERENCES public.registers(id);

ALTER TABLE stocklines
        ADD COLUMN note character varying DEFAULT ''::character varying NOT NULL;

CREATE OR REPLACE FUNCTION notify_user_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  IF NEW.transid IS DISTINCT FROM OLD.transid
    OR NEW.register_id IS DISTINCT FROM OLD.register_id THEN
    PERFORM pg_notify('user_register', CAST(NEW.id AS text));
  END IF;
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION notify_stockitem_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockitem_change', CAST(OLD.stockid AS text));
    IF (OLD.stocklineid IS NOT NULL) THEN
      PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
    END IF;
  ELSIF (TG_OP = 'INSERT') THEN
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
  ELSE
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
    IF (OLD.stocklineid IS DISTINCT FROM NEW.stocklineid) THEN
      IF (OLD.stocklineid IS NOT NULL) THEN
        PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
      END IF;
      IF (NEW.stocklineid IS NOT NULL) THEN
        PERFORM pg_notify('stockline_change', CAST(NEW.stocklineid AS text));
      END IF;
    END IF;
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION notify_stockline_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockline_change', CAST(OLD.stocklineid AS text));
  ELSE
    PERFORM pg_notify('stockline_change', CAST(NEW.stocklineid AS text));
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION notify_stockout_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stockitem_change', CAST(OLD.stockid AS text));
  ELSE
    PERFORM pg_notify('stockitem_change', CAST(NEW.stockid AS text));
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION notify_stocktype_change() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
BEGIN
  IF (TG_OP = 'DELETE') THEN
    PERFORM pg_notify('stocktype_change', CAST(OLD.stocktype AS text));
  ELSE
    PERFORM pg_notify('stocktype_change', CAST(NEW.stocktype AS text));
  END IF;
  RETURN NULL;
END;
$$;

CREATE TRIGGER user_changed
	AFTER UPDATE ON users
	FOR EACH ROW
	EXECUTE PROCEDURE public.notify_user_change();

CREATE TRIGGER stockitem_changed
	AFTER INSERT OR UPDATE OR DELETE ON stock
	FOR EACH ROW
	EXECUTE PROCEDURE public.notify_stockitem_change();

CREATE TRIGGER stockline_changed
	AFTER INSERT OR UPDATE OR DELETE ON stocklines
	FOR EACH ROW
	EXECUTE PROCEDURE public.notify_stockline_change();

CREATE TRIGGER stockout_changed
	AFTER INSERT OR UPDATE OR DELETE ON stockout
	FOR EACH ROW
	EXECUTE PROCEDURE public.notify_stockout_change();

CREATE TRIGGER stocktype_changed
	AFTER INSERT OR UPDATE OR DELETE ON stocktypes
	FOR EACH ROW
	EXECUTE PROCEDURE public.notify_stocktype_change();

COMMIT;
```


Upgrade v21.x to v22
--------------------

(Ensure the update from v21.0 to v21.1 has been performed first.)

Major internal changes to how Payments and payment methods work.

What's new:

 * Payments have been changed to work more like transaction lines: the
   information displayed in the register is stored in a column called
   "text" and it is no longer necessary to refer to the payment method
   to calculate what to display.

 * Pending payment status is now stored in the payments table and not
   calculated from the payment using the payment method.

 * Payment method configuration has moved to the database. Payment
   method configuration in the configuration file will be migrated to
   the database the first time the till is run with v22 installed.

 * A payment driver for Square Terminal is included.

To upgrade the database:

 - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE payments
        ADD COLUMN text text,
        ADD COLUMN pending boolean DEFAULT false NOT NULL;

SET session_replication_role = replica;
UPDATE payments p
        SET text=CASE WHEN p.paytype='CASH' THEN p.ref
                      ELSE pt.description || ' ' || p.ref
                 END
        FROM paytypes pt WHERE p.paytype=pt.paytype;
SET session_replication_role = default;
ALTER TABLE payments
        DROP COLUMN ref,
        ALTER COLUMN text SET NOT NULL;

ALTER TABLE payments
        ADD CONSTRAINT pending_payment_constraint CHECK (((NOT pending) OR (amount = 0.00)));

CREATE OR REPLACE FUNCTION check_no_pending_payments() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.closed=true
    AND EXISTS (SELECT * FROM payments WHERE pending AND transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction % has pending payments', NEW.transid
       USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER close_only_if_no_pending_payments
  AFTER INSERT OR UPDATE ON transactions
  FOR EACH ROW EXECUTE PROCEDURE check_no_pending_payments();

ALTER TABLE paytypes
        ADD COLUMN "order" integer,
        ADD COLUMN driver_name character varying DEFAULT ''::character varying NOT NULL,
        ADD COLUMN mode character varying DEFAULT 'disabled'::character varying NOT NULL,
        ADD COLUMN config text,
        ADD COLUMN state text,
        ADD COLUMN payments_account character varying DEFAULT ''::character varying NOT NULL,
        ADD COLUMN fees_account character varying DEFAULT ''::character varying NOT NULL,
        ADD COLUMN payment_date_policy character varying DEFAULT 'same-day'::character varying NOT NULL;

ALTER TABLE paytypes
        ADD CONSTRAINT paytype_absent_driver_constraint CHECK (((NOT ((driver_name)::text = ''::text)) OR ((mode)::text = 'disabled'::text)));

ALTER TABLE paytypes
        ADD CONSTRAINT paytype_mode_constraint CHECK ((((mode)::text = 'disabled'::text) OR ((mode)::text = 'active'::text) OR ((mode)::text = 'total_only'::text)));

ALTER TABLE sessiontotals
        ADD COLUMN fees numeric(10,2) DEFAULT 0.00 NOT NULL;

COMMIT;
```

 - run the till to migrate the payment method configuration, using
   `runtill start`

 - edit the payment methods in the web interface to set the
   appropriate payment date policies, since these are not migrated
   automatically.

Upgrade v21.0 to v21.1
----------------------

What's new:

 * database trigger updates and additional tests

 * minor bug fixes

To upgrade the database, run psql and give the following
commands. This can be done either before or after upgrading quicktill
since the changes are backwards-compatible.

```
BEGIN;

CREATE OR REPLACE FUNCTION check_max_one_session_open() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (SELECT count(*) FROM sessions WHERE endtime IS NULL)>1 THEN
    RAISE EXCEPTION 'there is already an open session'
          USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION check_modify_closed_trans_line() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
    AND (OLD.translineid != NEW.translineid
      OR OLD.transid != NEW.transid
      OR OLD.items != NEW.items
      OR OLD.amount != NEW.amount
      OR OLD.dept != NEW.dept
      OR OLD.user != NEW.user
      OR OLD.transcode != NEW.transcode
      OR OLD.time != NEW.time
      OR OLD.discount != NEW.discount
      OR OLD.discount_name != NEW.discount_name
      OR OLD.source != NEW.source
      OR OLD.text != NEW.text)
    THEN RAISE EXCEPTION 'attempt to modify closed transaction % line', NEW.transid
               USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION check_modify_closed_trans_payment() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF (SELECT closed FROM transactions WHERE transid=NEW.transid)=true
  THEN RAISE EXCEPTION 'attempt to modify closed transaction % payment', NEW.transid
             USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$;

CREATE OR REPLACE FUNCTION check_transaction_balances() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF NEW.closed=true
    AND (SELECT COALESCE(sum(amount*items), 0.00) FROM translines
      WHERE transid=NEW.transid)!=
      (SELECT COALESCE(sum(amount), 0.00) FROM payments WHERE transid=NEW.transid)
  THEN RAISE EXCEPTION 'transaction % does not balance', NEW.transid
       USING ERRCODE = 'integrity_constraint_violation';
  END IF;
  RETURN NULL;
END;
$$;

COMMIT;
```

Upgrade v20.x to v21
--------------------

What's new:

 * Ability to specify minimum and/or maximum ABV for a department

 * `pricechanged` column of `stocktypes` is removed (it was unused)

 * Add a `description` column to VAT bands, shown on the web interface

 * Add a metadata table to sessions, for use by payment plugins

 * Add database constraints for ABV: can't be negative

 * Add a `source` column for transaction lines and payments; this
   records which terminal they were created at. For transaction lines
   and payments created after this change, this defaults to the
   configuration name but can be set per till using the `-t` or
   `--terminal-name` command line option.

 * Add extra columns to units to describe how stock is counted during
   a stock-take (eg. soft drink cartons are sold in multiples of 568ml
   but counted in multiples of 1000ml). Rename existing columns to be
   more descriptive of what they do!

 * The flag that determines whether stock take is done per-item or
   per-stocktype has moved from being per stock type to being a
   property of the stock type's Unit. It can no longer be edited
   explicitly during a stock take — that feature turned out to be
   confusing for users and led to some very inefficient working
   practices! After the database update, it defaults to stock take
   per-item for all Units and will need updating manually.

 * The `departments.accinfo` column has been split into
   `departments.sales_account` and `departments.purchases_account`.

To upgrade the database:

 - run "runtill syncdb" to create the new sessions metadata table

 - run psql and give the following commands to the database:

```
BEGIN;

ALTER TABLE departments
        ADD COLUMN minabv numeric(3,1),
        ADD COLUMN maxabv numeric(3,1);

ALTER TABLE vat
        ADD COLUMN description character varying DEFAULT 'None'::character varying NOT NULL;

ALTER TABLE stocktypes
        ADD CONSTRAINT stocktypes_abv_check CHECK ((abv >= 0.0));

ALTER TABLE departments
        ADD CONSTRAINT departments_maxabv_check CHECK ((maxabv >= 0.0));

ALTER TABLE departments
        ADD CONSTRAINT departments_minabv_check CHECK ((minabv >= 0.0));

ALTER TABLE payments
        ADD COLUMN source character varying DEFAULT 'default'::character varying NOT NULL;

ALTER TABLE translines
        ADD COLUMN source character varying DEFAULT 'default'::character varying NOT NULL;

ALTER TABLE unittypes
        ADD COLUMN sale_unit_name character varying,
        ADD COLUMN sale_unit_name_plural character varying,
        ADD COLUMN base_units_per_sale_unit numeric(8,1),
        ADD COLUMN stock_unit_name character varying,
        ADD COLUMN stock_unit_name_plural character varying,
        ADD COLUMN base_units_per_stock_unit numeric(8,1);
UPDATE unittypes
        SET sale_unit_name=item_name,
            sale_unit_name_plural=item_name_plural,
            base_units_per_sale_unit=units_per_item,
            stock_unit_name=item_name,
            stock_unit_name_plural=item_name_plural,
            base_units_per_stock_unit=units_per_item;
ALTER TABLE unittypes
        ALTER COLUMN sale_unit_name SET NOT NULL,
        ALTER COLUMN sale_unit_name_plural SET NOT NULL,
        ALTER COLUMN base_units_per_sale_unit SET NOT NULL,
        ALTER COLUMN stock_unit_name SET NOT NULL,
        ALTER COLUMN stock_unit_name_plural SET NOT NULL,
        ALTER COLUMN base_units_per_stock_unit SET NOT NULL;

ALTER TABLE unittypes
        ADD COLUMN stocktake_by_items boolean DEFAULT true NOT NULL;

ALTER TABLE departments
        ADD COLUMN sales_account character varying DEFAULT ''::character varying NOT NULL,
        ADD COLUMN purchases_account character varying DEFAULT ''::character varying NOT NULL;

UPDATE departments
        SET sales_account = concat_ws(
                '/',
                nullif(split_part(accinfo, '/', 1), ''),
                nullif(split_part(accinfo, '/', 3), ''));

UPDATE departments
        SET purchases_account = concat_ws(
                '/',
                nullif(split_part(accinfo, '/', 2), ''),
                nullif(split_part(accinfo, '/', 3), ''));

COMMIT;

/* If you are updating multiple systems that share a web service, you
 * can defer executing the following until all systems and the web service
 * have been updated.
 */

BEGIN;

ALTER TABLE stocktypes
        DROP COLUMN pricechanged;

ALTER TABLE unittypes
        DROP COLUMN item_name,
        DROP COLUMN item_name_plural,
        DROP COLUMN units_per_item;

ALTER TABLE stocktypes
        DROP COLUMN stocktake_by_items;

ALTER TABLE departments
        DROP COLUMN accinfo;

COMMIT;
```


Upgrade v19.x to v20
--------------------

What's new:

 * Barcode support

 * Reorganised side menu in web interface

To upgrade the database:

 - run "runtill syncdb" to create the new barcodes table


Upgrade v19.{0,1} to v19.2
--------------------------

What's new:

 * metadata tables for transaction lines and payments

These tables are only used by plugins; they are not used by the core
register code. To upgrade the database:

 - run "runtill syncdb" to create the new tables


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
