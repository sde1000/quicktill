from . import models
import unittest
import datetime
from decimal import Decimal
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError

TEST_DATABASE_NAME = "quicktill-test"


class ModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Create the test database
        engine = create_engine("postgresql+psycopg2:///postgres")
        conn = engine.connect()
        conn.execute('commit')
        conn.execute(f'create database "{TEST_DATABASE_NAME}"')
        conn.close()
        cls._engine = create_engine(
            f"postgresql+psycopg2:///{TEST_DATABASE_NAME}")
        models.metadata.bind = cls._engine
        models.metadata.create_all()
        cls._sm = sessionmaker()

    @classmethod
    def tearDownClass(cls):
        # Dispose of the connection pool, closing all checked-in connections
        cls._engine.dispose()
        del cls._engine
        engine = create_engine("postgresql+psycopg2:///postgres")
        conn = engine.connect()
        conn.execute('commit')
        conn.execute(f'drop database "{TEST_DATABASE_NAME}"')
        conn.close()

    def setUp(self):
        self.connection = self._engine.connect()
        self.trans = self.connection.begin()
        self.s = self._sm(bind=self.connection)

    def tearDown(self):
        self.s.close()
        # self.trans.rollback()
        self.connection.close()

    def test_add_business(self):
        self.s.add(models.Business(
            id=1, name='Test', abbrev='TEST', address='An address'))
        self.s.commit()

    def test_no_current_session(self):
        current = models.Session.current(self.s)
        self.assertIsNone(current)

    def test_no_session_totals_reports_none(self):
        """Session.actual_total should be None for sessions with no totals
        recorded.
        """
        session = models.Session(datetime.date.today())
        self.s.add(session)
        self.s.commit()
        self.assertIsNone(session.actual_total)
        session.endtime = datetime.datetime.now()
        self.s.commit()
        self.assertIsNone(session.actual_total)

    def test_actual_session_totals(self):
        session = models.Session(datetime.date.today())
        session.endtime = datetime.datetime.now()
        cash = models.PayType(paytype='CASH', description='Cash')
        card = models.PayType(paytype='CARD', description='Card')
        self.s.add_all([session, cash, card])
        self.s.commit()
        self.s.add_all([
            models.SessionTotal(session=session, paytype=cash,
                                amount=Decimal(2)),
            models.SessionTotal(session=session, paytype=card,
                                amount=Decimal(1)),
        ])
        self.s.commit()
        self.assertEqual(session.actual_total, Decimal(3))

    def template_setup(self):
        """Add template data to the database to make other tests shorter.
        """
        business = models.Business(
            id=1, name='Test', abbrev='TEST', address='An address')
        vatband = models.VatBand(band='A', business=business, rate=0.2)
        dept = models.Department(id=1, description="Test", vat=vatband)
        sale = models.TransCode(code='S', description='Sale')
        void = models.TransCode(code='V', description='Void')
        self.s.add_all([business, vatband, dept, sale, void])
        self.s.commit()

    def template_removecode_setup(self):
        """Add a removecode to the database to make other tests shorter."""
        self.s.add(models.RemoveCode(id='test', reason='Test'))
        self.s.commit()

    def template_stocktype_setup(self):
        """Add a stocktype to the database to make other tests shorter."""
        pint = models.Unit(
            name='pint', description='Pint',
            sale_unit_name='pint', sale_unit_name_plural='pints',
            stock_unit_name='pint', stock_unit_name_plural='pints')
        beer = models.StockType(
            manufacturer="A Brewery", name="A Beer",
            abv=5, unit=pint, dept_id=1)
        self.s.add(beer)
        self.s.commit()
        return beer

    def template_stockline_and_plu_setup(self):
        self.template_setup()
        stockline = models.StockLine(name="Test SL", location="Test",
                                     linetype="regular", dept_id=1)
        plu = models.PriceLookup(description="Test PLU", note="", dept_id=1,
                                 price=1.00)
        self.s.add_all([stockline, plu])
        self.s.commit()
        return stockline, plu

    def test_stockline_linetype_constraint(self):
        self.template_setup()
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="unknown"))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_regular_stockline_capacity_constraint(self):
        self.template_setup()
        # Try it with a capacity
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="regular", dept_id=1,
            capacity=10, pullthru=1))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_regular_stockline_stocktype_constraint(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        # Try it with a stocktype
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="regular", dept_id=1,
            stocktype=beer, pullthru=1))
        self.s.commit()

    def test_display_stockline_pullthru_constraint(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        # Try it with a pullthru
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="display",
            capacity=10, pullthru=1, stocktype=beer))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_display_stockline_capacity_constraint(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        # Try it without a capacity
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="display",
            stocktype=beer))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_display_stockline_stocktype_constraint(self):
        self.template_setup()
        # Try it without a stocktype
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="display",
            capacity=10))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_continuous_stockline_constraint(self):
        self.template_setup()
        self.s.add(models.StockLine(
            name="Test", location="Test", linetype="continuous"))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_keyboard_binding_unambigous_constraint(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        self.s.add(models.KeyboardBinding(
            keycode='FOO', menukey='BAR',
            stockline=stockline, plu=plu))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_keyboard_binding_useful_constraint(self):
        self.s.add(models.KeyboardBinding(
            keycode='FOO', menukey='BAR'))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_barcode_useful_constraint(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        self.s.add(models.Barcode(id='123456'))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_barcode_unambiguous_constraint(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        self.s.add(models.Barcode(id='12121', stockline=stockline,
                                  plu=plu))
        with self.assertRaises(IntegrityError):
            self.s.commit()

    def test_barcode_stockline_cascade(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        barcode = models.Barcode(id='123456', stockline=stockline)
        self.s.add(barcode)
        self.s.commit()
        self.assertEqual(stockline.barcodes, [barcode])
        self.s.delete(stockline)
        self.s.commit()

    def test_barcode_plu_cascade(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        barcode = models.Barcode(id='123456', plu=plu)
        self.s.add(barcode)
        self.s.commit()
        self.assertEqual(plu.barcodes, [barcode])
        self.s.delete(plu)
        self.s.commit()

    def test_barcode_delete(self):
        stockline, plu = self.template_stockline_and_plu_setup()
        barcode = models.Barcode(id='123456', plu=plu)
        self.s.add(barcode)
        self.s.commit()
        self.s.delete(barcode)
        self.s.commit()
        self.s.refresh(plu)
        self.assertEqual(plu.barcodes, [])

    def test_transline_void(self):
        self.template_setup()
        session = models.Session(datetime.date.today())
        self.s.add(session)
        self.s.commit()
        trans = models.Transaction(session=session)
        transline = models.Transline(
            transaction=trans, items=1,
            amount=Decimal("10.00"), dept_id=1,
            transcode='S', text="Test sale")
        self.s.add(transline)
        self.s.commit()
        self.assertEqual(trans.balance, Decimal("10.00"))
        void = transline.void(trans, None)
        self.s.add(void)
        self.s.commit()
        self.assertEqual(transline.voided_by_id, void.id)
        self.assertEqual(trans.balance, Decimal("0.00"))
        self.s.delete(void)
        self.s.commit()
        self.assertIsNone(transline.voided_by_id)
        self.assertEqual(trans.balance, Decimal("10.00"))

    def test_delivery_costprice(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        delivery = models.Delivery(
            date=datetime.date.today(),
            supplier=models.Supplier(name="Test supplier"),
            docnumber="test")
        self.s.add(delivery)
        self.s.commit()
        self.assertIsNone(delivery.costprice)
        self.s.add(models.StockItem(
            delivery=delivery,
            stocktype=beer,
            description="Firkin",
            size=72,
            costprice=72))
        self.s.commit()
        self.assertEqual(delivery.costprice, Decimal("72.00"))
        self.s.add(models.StockItem(
            delivery=delivery,
            stocktype=beer,
            description="Firkin",
            size=72))
        self.s.commit()
        self.assertIsNone(delivery.costprice)

    def test_delivery_add_items(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        pint = beer.unit
        firkin = models.StockUnit(name="Firkin", unit=pint, size=72.0,
                                  merge=False)
        self.s.add(firkin)
        delivery = models.Delivery(
            date=datetime.date.today(),
            supplier=models.Supplier(name="Test supplier"),
            docnumber="test")
        self.s.add(delivery)
        self.s.commit()
        # Add three firkins to the delivery.  If this fails, has
        # autoflush somehow been turned on?
        delivery.add_items(beer, firkin, 3, Decimal("157.00"))
        self.s.flush()
        # Test adding a merged item
        merge_stockunit = models.StockUnit(name="Test", unit=pint, size=10,
                                           merge=True)
        self.s.add(merge_stockunit)
        delivery.add_items(beer, merge_stockunit, 2, Decimal("201.00"))
        self.s.commit()

    def test_stockitem_remaining(self):
        self.template_setup()
        self.template_removecode_setup()
        beer = self.template_stocktype_setup()
        delivery = models.Delivery(
            date=datetime.date.today(),
            supplier=models.Supplier(name="Test supplier"),
            docnumber="test")
        item = models.StockItem(
            delivery=delivery,
            stocktype=beer,
            description="Firkin",
            size=72)
        self.s.add(item)
        self.s.commit()
        self.assertEqual(item.remaining, Decimal("72.0"))
        self.s.add(models.StockOut(stockitem=item, removecode_id='test', qty=1))
        self.s.commit()
        self.assertEqual(item.remaining, Decimal("71.0"))

    def test_stocktype_remaining(self):
        self.template_setup()
        self.template_removecode_setup()
        beer = self.template_stocktype_setup()
        delivery = models.Delivery(
            date=datetime.date.today(),
            supplier=models.Supplier(name="Test supplier"),
            docnumber="test")
        for i in range(2):
            item = models.StockItem(
                delivery=delivery,
                stocktype=beer,
                description="Firkin",
                size=72)
            self.s.add(item)
        self.s.commit()
        self.assertEqual(beer.remaining, Decimal("0.0"))
        delivery.checked = True
        self.s.commit()
        self.assertEqual(beer.remaining, Decimal("144.0"))
        self.s.add(models.StockOut(stockitem=item, removecode_id='test', qty=1))
        self.s.commit()
        self.assertEqual(beer.remaining, Decimal("143.0"))

    def test_annotation_delete_cascade(self):
        self.template_setup()
        beer = self.template_stocktype_setup()
        user = self.template_user_setup()
        atype = models.AnnotationType(id='test', description='test')
        delivery = models.Delivery(
            date=datetime.date.today(),
            supplier=models.Supplier(name="Test supplier"),
            docnumber="test")
        item = models.StockItem(
            delivery=delivery,
            stocktype=beer,
            description="Firkin",
            size=72)
        annotation = models.StockAnnotation(
            stockitem=item, type=atype, user=user, text='test')
        self.s.add(annotation)
        self.s.commit()
        self.s.delete(item)
        self.s.commit()

    def template_user_setup(self):
        user = models.User(fullname="A User", shortname="A", enabled=True)
        permission_a = models.Permission(id="frob", description="Do Something")
        permission_b = models.Permission(id="wibble",
                                         description="Do something else")
        group = models.Group(id="basic-users", description="General users")
        group.permissions.append(permission_a)
        user.groups.append(group)
        self.s.add(user)
        self.s.add(permission_b)
        self.s.commit()
        return user

    def test_user_permissions(self):
        user = self.template_user_setup()
        pa = self.s.query(models.Permission).get('frob')
        self.assertIsNotNone(pa)
        pb = self.s.query(models.Permission).get('wibble')
        self.assertIsNotNone(pb)
        permissions = user.permissions
        self.assertEqual(len(permissions), 1)
        self.assertIn(pa, permissions)
        self.assertNotIn(pb, permissions)

    def test_group_rename(self):
        user = self.template_user_setup()
        group = self.s.query(models.Group).get('basic-users')
        self.assertIsNotNone(group)
        group.id = 'all-users'
        self.s.flush()
        groups = user.groups
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].id, 'all-users')
        self.s.flush()
        pa = self.s.query(models.Permission).get('frob')
        self.assertIsNotNone(pa)
        self.assertEqual(pa.groups[0].id, 'all-users')

    def test_session_meta(self):
        session = models.Session(datetime.date.today())
        self.s.add(session)
        session.set_meta('test', 'testval')
        self.s.flush()
        # SessionMeta row should exist
        sm = self.s.query(models.SessionMeta).get((session.id, 'test'))
        self.assertIsNotNone(sm)
        self.assertEqual(sm.value, 'testval')
        # SessionMeta should be accessible through the collection
        self.assertIn('test', session.meta)
        self.assertEqual(session.meta['test'].value, 'testval')
        sid = session.id
        self.s.delete(session)
        self.s.flush()
        # SessionMeta row should not exist
        sm = self.s.query(models.SessionMeta).get((sid, 'test'))
        self.assertIsNone(sm)

    def test_transaction_meta(self):
        self.template_setup()
        session = models.Session(datetime.date.today())
        self.s.add(session)
        self.s.flush()
        trans = models.Transaction(session=session)
        trans.set_meta('test', 'testval')
        self.s.add(trans)
        self.s.flush()
        # TransactionMeta row should exist
        tm = self.s.query(models.TransactionMeta).get((trans.id, 'test'))
        self.assertIsNotNone(tm)
        self.assertEqual(tm.value, 'testval')
        # TransactionMeta should be accessible through the collection
        self.assertIn('test', trans.meta)
        self.assertEqual(trans.meta['test'].value, 'testval')
        self.s.delete(trans)
        self.s.flush()
        # TransactionMeta row should not exist
        tm = self.s.query(models.TransactionMeta).get((trans.id, 'test'))
        self.assertIsNone(tm)

    def test_transline_meta(self):
        self.template_setup()
        session = models.Session(datetime.date.today())
        trans = models.Transaction(session=session)
        transline = models.Transline(
            transaction=trans, items=1,
            amount=Decimal("10.00"), dept_id=1,
            transcode='S', text="Test sale")
        self.s.add_all([session, trans, transline])
        transline.set_meta('test', 'testval')
        self.s.flush()
        tlid = transline.id
        # TranslineMeta row should exist
        tm = self.s.query(models.TranslineMeta).get((tlid, 'test'))
        self.assertIsNotNone(tm)
        self.assertEqual(tm.value, 'testval')
        # TranslineMeta should be accessible through the collection
        self.assertIn('test', transline.meta)
        self.assertEqual(transline.meta['test'].value, 'testval')
        self.s.delete(trans)
        self.s.commit()
        # Transline row should not exist
        tl = self.s.query(models.Transline).get(tlid)
        self.assertIsNone(tl)
        # TranslineMeta row should not exist
        tm = self.s.query(models.TranslineMeta).get((tlid, 'test'))
        self.assertIsNone(tm)

    def test_payment_meta(self):
        self.template_setup()
        cash = models.PayType(paytype='CASH', description='Cash')
        session = models.Session(datetime.date.today())
        trans = models.Transaction(session=session)
        payment = models.Payment(
            transaction=trans, amount=Decimal("10.00"),
            paytype=cash, ref="Test")
        self.s.add_all([cash, session, trans, payment])
        self.s.flush()
        payment.set_meta('test', 'testval')
        pid = payment.id
        # PaymentMeta row should exist
        pm = self.s.query(models.PaymentMeta).get((pid, 'test'))
        self.assertIsNotNone(pm)
        self.assertEqual(pm.value, 'testval')
        # PaymentMeta should be accessible through the collection
        self.assertIn('test', payment.meta)
        self.assertEqual(payment.meta['test'].value, 'testval')
        self.s.delete(trans)
        self.s.commit()
        # PaymentMeta row should not exist
        pm = self.s.query(models.PaymentMeta).get((pid, 'test'))
        self.assertIsNone(pm)


if __name__ == '__main__':
    unittest.main()
