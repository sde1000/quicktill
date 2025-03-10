from . import passwords
import unittest

# This password hash was generated by Django to test interoperability
pass_12345 = "pbkdf2_sha256$720000$kir3IBKRCByvPaRZv3pKLH$Q6TOts5S6gFwtbZ" \
    "Ykd0vSix4tWuLWd2aQJab7DXX2aI="
pass_invalid_algorithm = "foo$1$abc$def"
pass_invalid_format = "foo"


class PasswordTest(unittest.TestCase):
    def test_pass_12345(self):
        self.assertTrue(
            passwords.check_password("12345", pass_12345))

    def test_invalid_algorithm(self):
        with self.assertRaises(ValueError):
            passwords.get_hasher("foo")

        with self.assertRaises(ValueError):
            passwords.check_password("12345", pass_invalid_algorithm)

    def test_invalid_format(self):
        with self.assertRaises(ValueError):
            passwords.check_password("12345", pass_invalid_format)

    def test_hash_password(self):
        hash_foo = passwords.encode_password("foo")
        parts = hash_foo.split("$")
        self.assertEqual(len(parts), 4)
        self.assertEqual(parts[0], "pbkdf2_sha256")

    def test_wrong_password(self):
        hash_foo = passwords.encode_password("foo")
        self.assertFalse(passwords.check_password("bar", hash_foo))

    def test_correct_password(self):
        hash_foo = passwords.encode_password("foo")
        self.assertTrue(passwords.check_password("foo", hash_foo))


if __name__ == '__main__':
    unittest.main()
