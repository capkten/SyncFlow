import unittest

from backend.utils.crypto import encrypt_secret, decrypt_secret


class TestCrypto(unittest.TestCase):
    def test_encrypt_decrypt(self):
        raw = "my_password"
        encrypted = encrypt_secret(raw)
        self.assertTrue(encrypted.startswith("enc:"))
        decrypted = decrypt_secret(encrypted)
        self.assertEqual(decrypted, raw)

    def test_encrypt_idempotent(self):
        raw = "secret"
        encrypted = encrypt_secret(raw)
        encrypted_again = encrypt_secret(encrypted)
        self.assertEqual(encrypted, encrypted_again)

    def test_decrypt_plaintext(self):
        raw = "plain"
        self.assertEqual(decrypt_secret(raw), raw)


if __name__ == '__main__':
    unittest.main()
