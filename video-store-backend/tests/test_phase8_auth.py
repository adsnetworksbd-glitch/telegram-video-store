"""
Phase 8 / Part 1 — Telegram authentication tests.

Honest scope of each section (also printed in docs/PHASE8_PART1_REPORT.md):

  A. TelegramVerification  — REAL. Runs app.core.telegram_auth (the production
     code, stdlib only). initData is signed in the test with a THROWAWAY bot
     token using the official algorithm. It is therefore "validly signed for a
     test token", NOT data issued by Telegram's servers.
  B. UserService (MOCK DB) — the real app.services.user_auth logic running
     against an in-memory fake of the Firestore calls it uses. This is a MOCK
     test of persistence; it proves our logic, not Firestore behaviour.
  C. StaticChecks          — real source inspection (AST / text) of backend and
     frontend files. No code is executed.
  D. JwtTokens             — REAL python-jose + RSA keys, but only when
     python-jose / passlib / pydantic-settings are installed; otherwise skipped.
     (Skipped, not passed, when dependencies are missing.)
"""
import ast
import base64
import hashlib
import hmac
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "video-store-backend"
APP = BACKEND_ROOT / "app"
EP = APP / "api" / "v1" / "endpoints"
FRONTEND = ROOT / "video-store-frontend" / "src"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.telegram_auth import (  # noqa: E402
    MAX_FUTURE_SKEW_SECONDS,
    TelegramAuthConfigError,
    TelegramAuthError,
    verify_init_data,
)

TEST_TOKEN = "123456:TEST-token-not-a-real-bot-xxxxxxxxxxxx"
USER = {"id": 424242, "first_name": "Rahim", "last_name": "Uddin",
        "username": "rahim_u", "language_code": "bn", "photo_url": "https://t.me/i/userpic/x.jpg"}


def sign(fields: dict, token: str = TEST_TOKEN) -> str:
    """Official algorithm, implemented independently of the production module."""
    dcs = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode({**fields, "hash": digest})


def fields(now: float, **over) -> dict:
    base = {"query_id": "AAH-test", "user": json.dumps(USER, separators=(",", ":")),
            "auth_date": str(int(now)), "signature": "c2lnbmF0dXJl"}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


# ═══ A. Telegram initData verification (REAL code) ═══════════════════════════
class TelegramVerification(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0

    def verify(self, init_data, **kw):
        kw.setdefault("now", self.now)
        return verify_init_data(init_data, TEST_TOKEN, **kw)

    def reason(self, init_data, **kw):
        with self.assertRaises(TelegramAuthError) as cm:
            self.verify(init_data, **kw)
        return cm.exception.reason

    # 1 ─ valid
    def test_valid_init_data(self):
        u = self.verify(sign(fields(self.now, start_param="VS-ABC1234")))
        self.assertEqual(u["id"], 424242)
        self.assertEqual(u["username"], "rahim_u")
        self.assertEqual(u["start_param"], "VS-ABC1234")

    def test_signature_field_is_part_of_signed_data(self):
        good = sign(fields(self.now))
        self.verify(good)  # includes `signature=` in the data-check-string
        stripped = re.sub(r"&?signature=[^&]*", "", good)
        self.assertEqual(self.reason(stripped), "hash_mismatch")

    @unittest.skipUnless(shutil.which("openssl"), "openssl CLI not available")
    def test_known_answer_against_openssl(self):
        """Independent check: compute the hash with the OpenSSL CLI, not Python's hmac."""
        f = fields(self.now)
        dcs = "\n".join(f"{k}={v}" for k, v in sorted(f.items()))
        k1 = subprocess.run(["openssl", "dgst", "-sha256", "-mac", "HMAC", "-macopt", "key:WebAppData", "-hex"],
                            input=TEST_TOKEN.encode(), capture_output=True, check=True).stdout.decode().split()[-1]
        h = subprocess.run(["openssl", "dgst", "-sha256", "-mac", "HMAC", "-macopt", f"hexkey:{k1}", "-hex"],
                           input=dcs.encode(), capture_output=True, check=True).stdout.decode().split()[-1]
        self.assertEqual(self.verify(urllib.parse.urlencode({**f, "hash": h}))["id"], 424242)

    # 2 ─ invalid hash
    def test_invalid_hash(self):
        good = sign(fields(self.now))
        bad = good[:-1] + ("0" if good[-1] != "0" else "1")
        self.assertEqual(self.reason(bad), "hash_mismatch")

    def test_wrong_bot_token(self):
        self.assertEqual(self.reason(sign(fields(self.now), token="999:other-token")), "hash_mismatch")

    def test_non_ascii_hash_is_rejected_not_500(self):
        s = urllib.parse.urlencode({**fields(self.now), "hash": "é" * 64})
        self.assertEqual(self.reason(s), "hash_mismatch")  # must be TelegramAuthError, never TypeError

    # 10 ─ spoofing: changing the id after signing breaks the hash
    def test_user_id_spoofing_after_signing(self):
        signed = sign(fields(self.now))
        parsed = dict(urllib.parse.parse_qsl(signed))          # includes the genuine hash
        parsed["user"] = json.dumps({**USER, "id": 1}, separators=(",", ":"))
        forged = urllib.parse.urlencode(parsed)                # same hash, different user id
        self.assertNotEqual(forged, signed)
        self.assertEqual(self.reason(forged), "hash_mismatch")

    def test_forged_user_with_attacker_controlled_hash(self):
        forged = urllib.parse.urlencode({**fields(self.now, user=json.dumps({**USER, "id": 1})), "hash": "0" * 64})
        self.assertEqual(self.reason(forged), "hash_mismatch")

    # 3 ─ expired
    def test_expired_init_data(self):
        old = fields(self.now - 86400 - 1)
        self.assertEqual(self.reason(sign(old)), "expired")

    def test_age_boundary_and_custom_max_age(self):
        self.verify(sign(fields(self.now - 86400)))  # exactly max age is still accepted
        self.assertEqual(self.reason(sign(fields(self.now - 3601)), max_age_seconds=3600), "expired")

    def test_future_auth_date(self):
        self.verify(sign(fields(self.now + MAX_FUTURE_SKEW_SECONDS - 1)))  # small clock drift ok
        self.assertEqual(self.reason(sign(fields(self.now + 3600))), "auth_date_in_future")

    def test_auth_date_missing_or_garbage(self):
        self.assertEqual(self.reason(sign(fields(self.now, auth_date=None))), "missing_auth_date")
        self.assertEqual(self.reason(sign(fields(self.now, auth_date="abc"))), "invalid_auth_date")
        self.assertEqual(self.reason(sign(fields(self.now, auth_date="-5"))), "invalid_auth_date")
        self.assertEqual(self.reason(sign(fields(self.now, auth_date="²"))), "invalid_auth_date")

    # 4 ─ missing initData
    def test_missing_init_data(self):
        self.assertEqual(self.reason(""), "missing_init_data")
        self.assertEqual(self.reason(None), "missing_init_data")  # type: ignore[arg-type]

    def test_missing_hash(self):
        self.assertEqual(self.reason(urllib.parse.urlencode(fields(self.now))), "missing_hash")

    def test_oversized_init_data(self):
        self.assertEqual(self.reason("a=" + "b" * 9000), "init_data_too_long")

    def test_duplicate_fields_rejected(self):
        good = sign(fields(self.now))
        self.assertEqual(self.reason(good + "&auth_date=1"), "duplicate_field")

    def test_user_payload_validation(self):
        self.assertEqual(self.reason(sign(fields(self.now, user=None))), "missing_user")
        self.assertEqual(self.reason(sign(fields(self.now, user="{not json"))), "invalid_user_json")
        self.assertEqual(self.reason(sign(fields(self.now, user="[1,2]"))), "invalid_user")
        for bad in ('{"id":"424242"}', '{"id":true}', '{"id":-3}', '{"id":0}', '{"first_name":"x"}'):
            self.assertEqual(self.reason(sign(fields(self.now, user=bad))), "invalid_user_id", bad)

    def test_missing_bot_token_is_server_error_not_client_error(self):
        with self.assertRaises(TelegramAuthConfigError):
            verify_init_data(sign(fields(self.now)), "", now=self.now)
        self.assertFalse(issubclass(TelegramAuthConfigError, ValueError))

    def test_real_clock_is_used_when_now_not_given(self):
        s = sign(fields(time.time()))
        self.assertEqual(verify_init_data(s, TEST_TOKEN)["id"], 424242)


# ═══ B. User service against an in-memory FAKE Firestore (MOCK) ══════════════
from app.services import user_auth  # noqa: E402


class FakeSnap:
    def __init__(self, data):
        self.exists = data is not None
        self._d = data

    def to_dict(self):
        return None if self._d is None else dict(self._d)


class FakeRef:
    def __init__(self, db, doc_id):
        self.db, self.id = db, doc_id

    async def get(self):
        if self.db.hide_first_get and self.id not in self.db.docs_hidden_done:
            self.db.docs_hidden_done.add(self.id)
            return FakeSnap(None)
        return FakeSnap(self.db.docs.get(self.id))

    async def create(self, data):
        self.db.writes.append(("create", self.id, dict(data)))
        if self.id in self.db.docs:
            raise user_auth.AlreadyExists("exists")
        self.db.docs[self.id] = dict(data)

    async def update(self, fields):
        self.db.writes.append(("update", self.id, dict(fields)))
        self.db.docs[self.id].update(fields)


class FakeCollection:
    def __init__(self, db):
        self.db = db

    def document(self, doc_id):
        return FakeRef(self.db, doc_id)


class FakeDB:
    def __init__(self):
        self.docs, self.writes = {}, []
        self.hide_first_get, self.docs_hidden_done = False, set()

    def collection(self, name):
        assert name == "users"
        return FakeCollection(self)


async def _fixed_code(db):
    return "VS-TESTCODE"


class UserService(unittest.IsolatedAsyncioTestCase):
    """MOCK-DB tests: real service logic, fake persistence."""

    def setUp(self):
        self._orig = user_auth._unique_referral_code
        user_auth._unique_referral_code = _fixed_code  # (needs google-cloud; mocked here)
        self.db = FakeDB()
        self.now = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
        self.tg = {**USER, "start_param": None}

    def tearDown(self):
        user_auth._unique_referral_code = self._orig

    async def test_new_user_registration_fields(self):
        data, created = await user_auth.find_or_create_user(self.db, self.tg, self.now)
        self.assertTrue(created)
        doc = self.db.docs["424242"]
        for k, v in {"id": "424242", "telegram_id": "424242", "username": "rahim_u", "first_name": "Rahim",
                     "last_name": "Uddin", "photo_url": USER["photo_url"], "created_at": self.now,
                     "last_login": self.now, "account_status": "active", "is_banned": False,
                     "wallet_balance": 0.0, "total_spent_bdt": 0.0, "referral_count": 0}.items():
            self.assertEqual(doc[k], v, k)
        self.assertEqual(doc["referral_code"], "VS-TESTCODE")
        self.assertEqual(data, doc)

    async def test_optional_telegram_fields_may_be_absent(self):
        _, created = await user_auth.find_or_create_user(self.db, {"id": 7, "first_name": "A"}, self.now)
        self.assertTrue(created)
        self.assertIsNone(self.db.docs["7"]["username"])
        self.assertIsNone(self.db.docs["7"]["photo_url"])

    async def test_existing_user_is_not_recreated_and_nothing_is_written(self):
        await user_auth.find_or_create_user(self.db, self.tg, self.now)
        self.db.writes.clear()
        _, created = await user_auth.find_or_create_user(self.db, self.tg, self.now)
        self.assertFalse(created)
        self.assertEqual(self.db.writes, [], "a returning user lookup must not write")
        self.assertEqual(len(self.db.docs), 1)

    async def test_existing_user_data_preserved_on_login(self):
        legacy = {  # pre-Phase-8 document: no id / last_login / account_status
            "telegram_id": "424242", "username": "old_name", "first_name": "Rahim", "last_name": None,
            "photo_url": None, "wallet_balance": 150.5, "total_spent_bdt": 999.0,
            "referral_code": "VS-LEGACY1", "referred_by_code": "VS-FRIEND1", "referral_count": 3,
            "referral_reward_total_bdt": 45.0, "is_banned": False,
            "created_at": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "last_seen_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        self.db.docs["424242"] = dict(legacy)
        data, created = await user_auth.find_or_create_user(self.db, self.tg, self.now)
        self.assertFalse(created)
        await user_auth.record_login(self.db, "424242", self.now)
        after = self.db.docs["424242"]
        changed = {k for k in after if after.get(k) != legacy.get(k)}
        self.assertEqual(changed, {"last_login", "last_seen_at"})
        for k in ("wallet_balance", "total_spent_bdt", "referral_code", "referral_count",
                  "referral_reward_total_bdt", "created_at", "username"):
            self.assertEqual(after[k], legacy[k], k)
        self.assertEqual([w[0] for w in self.db.writes], ["update"], "only a single update, never create/set")

    async def test_first_login_race_cannot_overwrite_existing_user(self):
        self.db.docs["424242"] = {"telegram_id": "424242", "wallet_balance": 500.0, "referral_code": "VS-REAL001"}
        self.db.hide_first_get = True  # get() says "missing" although it now exists
        data, created = await user_auth.find_or_create_user(self.db, self.tg, self.now)
        self.assertFalse(created)
        self.assertEqual(self.db.docs["424242"]["wallet_balance"], 500.0)
        self.assertEqual(self.db.docs["424242"]["referral_code"], "VS-REAL001")
        self.assertEqual(data["wallet_balance"], 500.0)

    async def test_identity_comes_only_from_verified_id(self):
        evil = {**USER, "id": 42, "telegram_id": "1", "user_id": "1"}
        await user_auth.find_or_create_user(self.db, evil, self.now)
        self.assertEqual(list(self.db.docs), ["42"])
        self.assertEqual(self.db.docs["42"]["telegram_id"], "42")
        self.assertEqual(self.db.docs["42"]["id"], "42")

    async def test_referral_start_param(self):
        d, _ = await user_auth.find_or_create_user(self.db, {**USER, "start_param": "VS-FRIEND1"}, self.now)
        self.assertEqual(d["referred_by_code"], "VS-FRIEND1")
        d, _ = await user_auth.find_or_create_user(self.db, {**USER, "id": 5, "start_param": "junk"}, self.now)
        self.assertIsNone(d["referred_by_code"])

    def test_is_blocked(self):
        self.assertTrue(user_auth.is_blocked({"is_banned": True}))
        self.assertTrue(user_auth.is_blocked({"account_status": "banned"}))
        self.assertFalse(user_auth.is_blocked({"account_status": "active", "is_banned": False}))
        self.assertFalse(user_auth.is_blocked({}))  # legacy document


# ═══ C. Static source checks (no code executed) ═════════════════════════════
class StaticChecks(unittest.TestCase):
    def test_no_endpoint_takes_user_identity_from_the_client(self):
        offenders = []
        for f in EP.glob("*.py"):
            for node in ast.walk(ast.parse(f.read_text())):
                if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                    continue
                args = node.args
                params = args.args + args.kwonlyargs
                defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults) + list(args.kw_defaults)
                for a, d in zip(params, defaults):
                    if a.arg in ("user_id", "telegram_id", "tg_id"):
                        ok = d is not None and "get_current_user" in ast.unparse(d)
                        if not ok:
                            offenders.append(f"{f.name}:{node.name}({a.arg})")
        self.assertEqual(offenders, [])

    def test_request_bodies_have_no_identity_fields(self):
        tree = ast.parse((APP / "schemas" / "__init__.py").read_text())
        for cls in [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name.endswith("Request")]:
            names = {s.target.id for s in cls.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
            self.assertFalse(names & {"user_id", "telegram_id", "id"}, cls.name)
        auth_req = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TelegramAuthRequest")
        # Phase 11: `start_param` (referral code from the launch URL) is the ONLY addition. It is
        # not an identity (the user id always comes from the verified initData) and is pattern-locked.
        self.assertEqual([s.target.id for s in auth_req.body if isinstance(s, ast.AnnAssign)], ["init_data", "start_param"])
        self.assertIn('pattern="^VS-[A-Z0-9]{7}$"', ast.unparse(auth_req).replace("'", '"'))

    def test_auth_errors_are_generic_and_never_echo_exception_text(self):
        src = (EP / "auth.py").read_text()
        self.assertNotIn("detail=str(e)", src)
        self.assertEqual(src.count("_verified_telegram_user(body.init_data)"), 2)  # login + refresh
        self.assertIn('_AUTH_FAILED = "Authentication failed"', src)

    def test_login_rejects_blocked_accounts_and_refresh_too(self):
        src = (EP / "auth.py").read_text()
        self.assertEqual(src.count("is_blocked("), 2)
        self.assertIn("get_current_user", (APP / "core" / "deps.py").read_text())
        self.assertIn("is_blocked(data)", (APP / "core" / "deps.py").read_text())

    def test_bot_token_only_in_backend_settings(self):
        for f in FRONTEND.rglob("*"):
            if f.is_file() and f.suffix in (".ts", ".tsx"):
                self.assertNotRegex(f.read_text(), r"BOT_TOKEN|bot_token|botToken", f.name)
        self.assertIn("settings.TELEGRAM_BOT_TOKEN", (APP / "core" / "security.py").read_text())

    def test_frontend_sends_only_init_data_and_keeps_jwt_in_memory(self):
        api = (FRONTEND / "api" / "index.ts").read_text()
        self.assertRegex(api, r"'/auth/telegram',\s*\{\s*init_data:\s*initData\b")
        login_call = api[api.index("'/auth/telegram'"):api.index("AUTH_TIMEOUT_MS }")]
        self.assertNotRegex(login_call, r"user_id|telegram_id")   # no identity in the login body
        for f in FRONTEND.rglob("*"):
            if f.is_file() and f.suffix in (".ts", ".tsx"):
                t = f.read_text()
                self.assertNotRegex(t, r"(localStorage|sessionStorage)\.setItem\([^)]*(token|jwt)", f.name)

    def test_frontend_gate_blocks_unauthenticated_and_session_reset_clears_everything(self):
        gate = (FRONTEND / "pages" / "Auth" / "index.tsx").read_text()
        self.assertIn("if (!isAuthenticated) {", gate)
        store = (FRONTEND / "store" / "index.ts").read_text()
        body = store[store.index("export function resetSession"):]
        self.assertIn("token: null", body)
        self.assertIn("isAuthenticated: false", body)
        self.assertIn("profile: null", body)
        self.assertLess(body.index("useAuthStore.setState"), body.index("useUserStore.setState"))
        self.assertIn("resetSession(", (FRONTEND / "api" / "client.ts").read_text())

class JwtTokens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        cls.tmp = tempfile.mkdtemp()

        def make_key(name):
            k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                   serialization.NoEncryption()).decode()
            pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            (Path(cls.tmp) / f"{name}.pem").write_text(priv)
            (Path(cls.tmp) / f"{name}.pub").write_text(pub)
            return priv, pub

        cls.priv, cls.pub = make_key("main")
        cls.other_priv, _ = make_key("other")

        from app.core import security
        from app.core.config import settings
        cls.security, cls.settings = security, settings
        cls._saved = (settings.JWT_PRIVATE_KEY_PATH, settings.JWT_PUBLIC_KEY_PATH,
                      settings.JWT_ALGORITHM, settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS)
        settings.JWT_PRIVATE_KEY_PATH = str(Path(cls.tmp) / "main.pem")
        settings.JWT_PUBLIC_KEY_PATH = str(Path(cls.tmp) / "main.pub")
        settings.JWT_ALGORITHM = "RS256"

    @classmethod
    def tearDownClass(cls):
        (cls.settings.JWT_PRIVATE_KEY_PATH, cls.settings.JWT_PUBLIC_KEY_PATH,
         cls.settings.JWT_ALGORITHM, cls.settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS) = cls._saved
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS = 24

    @staticmethod
    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    def test_roundtrip_and_minimal_claims(self):
        tok = self.security.create_access_token("424242")
        self.assertEqual(self.security.decode_access_token(tok), "424242")
        payload = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
        self.assertEqual(set(payload), {"sub", "iat", "exp", "type"})

    def test_expired_token_rejected(self):
        self.settings.JWT_ACCESS_TOKEN_EXPIRE_HOURS = -1
        with self.assertRaises(ValueError):
            self.security.decode_access_token(self.security.create_access_token("424242"))

    def test_garbage_and_tampered_tokens_rejected(self):
        tok = self.security.create_access_token("424242")
        h, p, s = tok.split(".")
        forged_p = self._b64(json.dumps({**json.loads(base64.urlsafe_b64decode(p + "==")), "sub": "1"}).encode())
        for bad in ("", "abc", "a.b.c", f"{h}.{forged_p}.{s}", tok[:-4] + "AAAA"):
            with self.assertRaises(ValueError, msg=bad):
                self.security.decode_access_token(bad)

    def test_token_signed_with_other_key_rejected(self):
        from jose import jwt
        now = int(time.time())
        tok = jwt.encode({"sub": "1", "type": "access", "iat": now, "exp": now + 600}, self.other_priv, algorithm="RS256")
        with self.assertRaises(ValueError):
            self.security.decode_access_token(tok)

    def test_alg_none_and_hs256_confusion_rejected(self):
        now = int(time.time())
        payload = self._b64(json.dumps({"sub": "1", "type": "access", "iat": now, "exp": now + 600}).encode())
        none_head = self._b64(b'{"alg":"none","typ":"JWT"}')
        none_tok = f"{none_head}.{payload}."
        hs_head = self._b64(b'{"alg":"HS256","typ":"JWT"}')
        sig = self._b64(hmac.new(self.pub.encode(), f"{hs_head}.{payload}".encode(), hashlib.sha256).digest())
        for bad in (none_tok, f"{hs_head}.{payload}.{sig}"):
            with self.assertRaises(ValueError):
                self.security.decode_access_token(bad)

    def test_token_without_exp_rejected(self):
        from jose import jwt
        tok = jwt.encode({"sub": "1", "type": "access", "iat": int(time.time())}, self.priv, algorithm="RS256")
        with self.assertRaises(ValueError):
            self.security.decode_access_token(tok)

    def test_admin_and_user_tokens_not_interchangeable(self):
        with self.assertRaises(ValueError):
            self.security.decode_access_token(self.security.create_admin_token("admin"))
        with self.assertRaises(ValueError):
            self.security.decode_admin_token(self.security.create_access_token("424242"))


if __name__ == "__main__":
    unittest.main()
