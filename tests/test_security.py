from __future__ import annotations

import hashlib
import unittest

from app.services.security import (
    create_session_token,
    hash_password,
    read_session_token,
    verify_password,
)


class SecurityTests(unittest.TestCase):
    def test_passwords_are_salted_and_verified(self) -> None:
        first = hash_password("mot-de-passe")
        second = hash_password("mot-de-passe")

        self.assertNotEqual(first, second)
        self.assertNotIn("mot-de-passe", first)
        self.assertEqual(verify_password("mot-de-passe", first), (True, False))
        self.assertEqual(verify_password("incorrect", first), (False, False))

    def test_legacy_password_formats_are_accepted_for_upgrade(self) -> None:
        legacy_sha = hashlib.sha256(b"ancien").hexdigest()

        self.assertEqual(verify_password("ancien", "ancien"), (True, True))
        self.assertEqual(verify_password("ancien", legacy_sha), (True, True))

    def test_signed_session_rejects_tampering_and_expiration(self) -> None:
        token = create_session_token("FIKRI HAMMADI", "secret-test", 3600, now=1000)

        self.assertEqual(
            read_session_token(token, "secret-test", now=2000), "FIKRI HAMMADI"
        )
        self.assertIsNone(read_session_token(token + "x", "secret-test", now=2000))
        self.assertIsNone(read_session_token(token, "secret-test", now=5000))


if __name__ == "__main__":
    unittest.main()
