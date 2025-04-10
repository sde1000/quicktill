from . import config
import unittest
import datetime
from decimal import Decimal


class ConfigTest(unittest.TestCase):
    def test_text_config(self):
        with self.assertRaises(Exception):
            config.ConfigItem("test:bad_default", None)
        with self.assertRaises(Exception):
            config.ConfigItem("test:no_none", "", allow_none=True)

        cfg = config.ConfigItem("test:text", "")
        cfg._test_set("hello")
        self.assertEqual(cfg(), "hello")

    def test_int_config(self):
        with self.assertRaises(Exception):
            config.IntConfigItem("test:bad_default", "foo")
        with self.assertRaises(Exception):
            config.IntConfigItem("test:bad_default_none", "foo",
                                 allow_none=True)
        cfg = config.IntConfigItem("test:int", 12345)
        cfg._test_set("4")
        self.assertEqual(cfg(), 4)
        cfg._test_set("foo")
        self.assertEqual(cfg(), 12345)
        cfg = config.IntConfigItem("test:int_or_none", None, allow_none=True)
        cfg._test_set("4")
        self.assertEqual(cfg(), 4)
        cfg._test_set("foo")
        self.assertIsNone(cfg())

    def test_positive_int_config(self):
        with self.assertRaises(Exception):
            config.PositiveIntConfigItem("test:bad_default", -1)
        cfg = config.PositiveIntConfigItem("test:posint", 5)
        cfg._test_set("4")
        self.assertEqual(cfg(), 4)
        cfg._test_set("-1")
        self.assertEqual(cfg(), 5)

    def test_boolean_config(self):
        with self.assertRaises(Exception):
            config.BooleanConfigItem("test:bad_default", "wibble")
        cfg = config.BooleanConfigItem("test:bool", True)
        cfg._test_set("No")
        self.assertFalse(cfg())
        cfg._test_set("Yes")
        self.assertTrue(cfg())
        cfg._test_set("")
        self.assertTrue(cfg())
        cfg = config.BooleanConfigItem(
            "test:bool_or_none", None, allow_none=True)
        cfg._test_set("No")
        self.assertFalse(cfg())
        cfg._test_set("Yes")
        self.assertTrue(cfg())
        cfg._test_set("")
        self.assertIsNone(cfg())

    def test_date_config(self):
        with self.assertRaises(Exception):
            config.DateConfigItem("test:bad_default", "wibble")
        cfg = config.DateConfigItem("test:date", datetime.date(2025, 4, 10))
        cfg._test_set("1974-03-20")
        self.assertEqual(cfg(), datetime.date(1974, 3, 20))
        cfg._test_set("foo")
        self.assertEqual(cfg(), datetime.date(2025, 4, 10))
        cfg = config.DateConfigItem("test:date_or_none", None, allow_none=True)
        cfg._test_set("1974-03-20")
        self.assertEqual(cfg(), datetime.date(1974, 3, 20))
        cfg._test_set("foo")
        self.assertIsNone(cfg())

    def test_time_config(self):
        with self.assertRaises(Exception):
            config.TimeConfigItem("test:bad_default", "wibble")
        cfg = config.TimeConfigItem("test:time", datetime.time(16, 24))
        cfg._test_set("23:30")
        self.assertEqual(cfg(), datetime.time(23, 30))
        cfg._test_set("")
        self.assertEqual(cfg(), datetime.time(16, 24))
        cfg = config.TimeConfigItem("test:time_or_none", None, allow_none=True)
        cfg._test_set("23:30")
        self.assertEqual(cfg(), datetime.time(23, 30))
        cfg._test_set("")
        self.assertIsNone(cfg())

    def test_interval_config(self):
        with self.assertRaises(Exception):
            config.IntervalConfigItem("test:bad_default", "wibble")
        cfg = config.IntervalConfigItem(
            "test:interval", datetime.timedelta(seconds=3600))
        cfg._test_set("30 minutes")
        self.assertEqual(cfg(), datetime.timedelta(seconds=1800))
        cfg._test_set("forever")
        self.assertEqual(cfg(), datetime.timedelta(hours=1))
        cfg = config.IntervalConfigItem(
            "test:interval_or_none", None, allow_none=True)
        cfg._test_set("30 minutes")
        self.assertEqual(cfg(), datetime.timedelta(seconds=1800))
        cfg._test_set("forever")
        self.assertIsNone(cfg())

    def test_money_config(self):
        with self.assertRaises(Exception):
            config.MoneyConfigItem("test:bad_default", "wibble")
        with self.assertRaises(Exception):
            config.MoneyConfigItem("test:bad_default", Decimal("10.152"))
        cfg = config.MoneyConfigItem("test:money", Decimal("2.30"))
        cfg._test_set("12")
        self.assertEqual(cfg(), Decimal("12.00"))
        cfg._test_set("fiver")
        self.assertEqual(cfg(), Decimal("2.30"))
        cfg = config.MoneyConfigItem(
            "test:money_or_none", None, allow_none=True)
        cfg._test_set("12.34")
        self.assertEqual(cfg(), Decimal("12.34"))
        cfg._test_set("fiver")
        self.assertIsNone(cfg())


if __name__ == '__main__':
    unittest.main()
