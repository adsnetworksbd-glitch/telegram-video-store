"""Pure helpers for webhook verification (no framework imports → unit-testable)."""
import hashlib
import hmac


def verify_hmac_sha256_hex(secret: str, body: bytes, signature: str) -> bool:
    """
    Fail-CLOSED: returns False when the secret is not configured or the
    signature is missing/wrong. Never skips verification.
    """
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip().lower())


def amount_covers(expected: float, paid: float, tolerance: float = 1e-6) -> bool:
    """Paid amount must be at least the expected amount (minus float noise)."""
    return paid + tolerance >= expected
