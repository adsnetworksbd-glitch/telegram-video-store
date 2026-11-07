"""
Payment method registry (Phase 10).

Every payment method is a document in the EXISTING `payment_methods` collection
and is fully admin-controlled. This module is the single place that knows what
each method *type* means, so adding a new built-in type (or an admin-defined
"other" method) never touches the order code.

Pure functions only — no Firestore / network — so it is easy to unit-test.

Document fields (old names kept; new ones are additive and optional):
    name, type, is_enabled, display_order,
    network_name, wallet_address, pay_id, merchant_name, qr_code_url,
    min_amount_usdt, max_amount_usdt, payment_timeout_minutes,
    instructions_text,
    auto_verification_supported, manual_review_supported, currency

The method ID is the Firestore document ID (unique by construction).
"""
from __future__ import annotations

import re
from typing import Any

# ─── Kinds ────────────────────────────────────────────────────────────────────
# gateway : paid on Binance's own checkout; verified by Binance webhook
# pay_id  : user sends to a Binance ID / Pay ID; manual review
# wallet  : user sends USDT to an on-chain address; manual review
# custom  : any other admin-configured method; shows whatever the admin set
KIND_GATEWAY = "gateway"
KIND_PAY_ID = "pay_id"
KIND_WALLET = "wallet"
KIND_CUSTOM = "custom"

_EVM_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_TRON_ADDR = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")
_PAY_ID = re.compile(r"^[0-9]{6,20}$")

# type → built-in behaviour. `network` is only a DEFAULT label; the admin value wins.
METHOD_TYPES: dict[str, dict[str, Any]] = {
    "binance_pay": {
        "kind": KIND_GATEWAY, "label": "Binance Pay", "network": None,
        "auto": True, "manual": True, "address_re": None,
    },
    "binance_id": {
        "kind": KIND_PAY_ID, "label": "Binance ID / Pay ID", "network": "Binance Internal",
        "auto": False, "manual": True, "address_re": _PAY_ID,
    },
    "usdt_trc20": {
        "kind": KIND_WALLET, "label": "USDT TRC20", "network": "TRON (TRC20)",
        "auto": False, "manual": True, "address_re": _TRON_ADDR,
    },
    "usdt_bep20": {
        "kind": KIND_WALLET, "label": "USDT BEP20", "network": "BSC (BEP20)",
        "auto": False, "manual": True, "address_re": _EVM_ADDR,
    },
    "usdt_erc20": {
        "kind": KIND_WALLET, "label": "USDT ERC20", "network": "Ethereum (ERC20)",
        "auto": False, "manual": True, "address_re": _EVM_ADDR,
    },
}

# Admin-defined types ("Other Admin-configured Methods") use this slug shape.
TYPE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,31}$")

DEFAULT_MIN_USDT = 0.5
DEFAULT_TIMEOUT_MIN = 30
MAX_TIMEOUT_MIN = 24 * 60
MIN_TIMEOUT_MIN = 5


def kind_of(method_type: str) -> str:
    return METHOD_TYPES.get(method_type, {}).get("kind", KIND_CUSTOM)


def is_gateway(method_type: str) -> bool:
    return kind_of(method_type) == KIND_GATEWAY


# ─── Normalisation (Firestore doc → one stable shape) ─────────────────────────
def _f(v: Any, default: float | None) -> float | None:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _s(v: Any) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def normalize_method(doc_id: str, data: dict) -> dict:
    """
    Stable, public-safe view of a payment method document.

    `wallet_address` is what the existing frontend/Payment documents already
    use as "the place to send money": for a Binance ID method it carries the
    Pay ID (so Phase 6–9 screens keep working); `pay_id` is the explicit field.
    Never includes anything secret — Binance API keys live in the environment.
    """
    mtype = _s(data.get("type")) or ""
    spec = METHOD_TYPES.get(mtype, {})
    kind = spec.get("kind", KIND_CUSTOM)

    pay_id = _s(data.get("pay_id"))
    address = _s(data.get("wallet_address"))
    if kind == KIND_PAY_ID:
        pay_id = pay_id or address
        address = pay_id
    elif kind == KIND_GATEWAY:
        address = None   # nothing to copy; user pays on Binance's checkout

    # Only a gateway has an official API verifier (Binance Pay order query).
    # Wallet / Pay ID / custom methods are ALWAYS reviewed by an admin, whatever
    # a stale document flag says.
    auto = kind == KIND_GATEWAY and bool(data.get("auto_verification_supported", spec.get("auto", False)))
    manual = bool(data.get("manual_review_supported", spec.get("manual", True)))

    return {
        "id": doc_id,
        "name": _s(data.get("name")) or spec.get("label") or doc_id,
        "type": mtype,
        "kind": kind,
        "is_enabled": bool(data.get("is_enabled", False)),
        "display_order": int(_f(data.get("display_order"), 0) or 0),
        "wallet_address": address,
        "pay_id": pay_id,
        "merchant_name": _s(data.get("merchant_name")),
        "network_name": _s(data.get("network_name")) or spec.get("network"),
        "qr_code_url": _s(data.get("qr_code_url")),
        "currency": (_s(data.get("currency")) or "USDT").upper(),
        "min_amount_usdt": _f(data.get("min_amount_usdt"), DEFAULT_MIN_USDT),
        "max_amount_usdt": _f(data.get("max_amount_usdt"), None),
        "payment_timeout_minutes": timeout_minutes(data),
        "instructions_text": _s(data.get("instructions_text")) or "",
        "auto_verification_supported": auto,
        "manual_review_supported": manual,
    }


def timeout_minutes(data: dict) -> int:
    try:
        n = int(data.get("payment_timeout_minutes", DEFAULT_TIMEOUT_MIN))
    except (TypeError, ValueError):
        n = DEFAULT_TIMEOUT_MIN
    return max(MIN_TIMEOUT_MIN, min(n, MAX_TIMEOUT_MIN))


def is_payable(m: dict) -> bool:
    """
    A method may be offered to users only if the user could actually pay with
    it: manual methods need a destination, gateway methods need nothing here
    (their credentials are checked when the prepay order is created).
    """
    if not m.get("is_enabled"):
        return False
    kind = m.get("kind")
    if kind in (KIND_WALLET, KIND_PAY_ID):
        # Built-in networks have a well-defined address format; a placeholder or
        # mistyped address must never be shown to a paying user.
        dest = m.get("wallet_address")
        rx = METHOD_TYPES.get(m.get("type", ""), {}).get("address_re")
        return bool(dest) and bool(rx.match(dest) if rx else True)
    if kind == KIND_CUSTOM:
        # custom methods show whatever the admin configured
        return bool(m.get("wallet_address") or m.get("pay_id") or m.get("instructions_text"))
    return True


# ─── Amount limits ────────────────────────────────────────────────────────────
def amount_problem(m: dict, usdt: float) -> str | None:
    """Bengali user-facing message when `usdt` is outside the method's limits."""
    lo, hi = m.get("min_amount_usdt"), m.get("max_amount_usdt")
    if lo is not None and usdt < lo:
        return f"এই পদ্ধতিতে ন্যূনতম {lo:g} USDT প্রয়োজন।"
    if hi is not None and usdt > hi:
        return f"এই পদ্ধতিতে সর্বোচ্চ {hi:g} USDT পর্যন্ত গ্রহণযোগ্য।"
    return None


# ─── Admin input validation ───────────────────────────────────────────────────
def config_problems(data: dict) -> list[str]:
    """
    Validate an admin-supplied method config (create / full update).
    Returns human-readable problems; empty list = OK. Wallet format is only
    enforced for the built-in network types — "other" methods are free-form.
    """
    problems: list[str] = []
    mtype = _s(data.get("type")) or ""
    if mtype not in METHOD_TYPES and not TYPE_SLUG_RE.match(mtype):
        problems.append("type must be a built-in type or a slug like 'bkash_usd' (a-z, 0-9, _)")
    if not _s(data.get("name")):
        problems.append("name is required")

    spec = METHOD_TYPES.get(mtype)
    kind = kind_of(mtype)
    address = _s(data.get("wallet_address"))
    pay_id = _s(data.get("pay_id"))
    if kind == KIND_PAY_ID:
        dest = pay_id or address
        if not dest:
            problems.append("pay_id is required for a Binance ID method")
        elif spec and not spec["address_re"].match(dest):
            problems.append("pay_id must be numeric (6–20 digits)")
    elif kind == KIND_WALLET and data.get("is_enabled"):
        if not address:
            problems.append("wallet_address is required for an enabled wallet method")
        elif spec and not spec["address_re"].match(address):
            problems.append(f"wallet_address is not a valid {spec['label']} address")

    lo, hi = _f(data.get("min_amount_usdt"), DEFAULT_MIN_USDT), _f(data.get("max_amount_usdt"), None)
    if lo is None or lo < 0:
        problems.append("min_amount_usdt must be >= 0")
    if hi is not None and (hi <= 0 or (lo is not None and hi < lo)):
        problems.append("max_amount_usdt must be greater than min_amount_usdt")

    qr = _s(data.get("qr_code_url"))
    if qr and not qr.startswith("https://"):
        problems.append("qr_code_url must be an https:// URL")
    if not (MIN_TIMEOUT_MIN <= int(_f(data.get("payment_timeout_minutes"), DEFAULT_TIMEOUT_MIN) or 0) <= MAX_TIMEOUT_MIN):
        problems.append(f"payment_timeout_minutes must be {MIN_TIMEOUT_MIN}–{MAX_TIMEOUT_MIN}")
    # Auto/Manual is an admin choice, but only where a real verifier exists.
    if kind != KIND_GATEWAY and data.get("auto_verification_supported") is True:
        problems.append("automatic verification is only available for Binance Pay; this method is manual review")
    auto_flag = data.get("auto_verification_supported", spec.get("auto", False) if spec else False)
    if kind != KIND_GATEWAY:
        auto_flag = False
    if not (auto_flag or data.get("manual_review_supported", True)):
        problems.append("a method needs auto verification or manual review enabled")
    return problems


# ─── Transaction hash / reference helpers (manual-review proof) ───────────────
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def normalize_txhash(method_type: str, raw: str | None) -> str | None:
    """
    One canonical spelling per transaction, so the same hash cannot be submitted
    twice by changing its case or a missing 0x. EVM networks: 0x + 64 hex.
    TRON: 64 hex. Binance ID / custom: free-form reference, trimmed + lower-cased.
    """
    h = _s(raw)
    if h is None:
        return None
    h = h.lower()
    if method_type in ("usdt_bep20", "usdt_erc20") and _HEX64.match(h):
        h = "0x" + h
    return h


def txhash_problem(method_type: str, raw: str | None) -> str | None:
    """Bengali message when a hash is impossible for the chosen network; None = OK."""
    h = normalize_txhash(method_type, raw)
    if h is None:
        return None
    if method_type == "usdt_trc20" and not _HEX64.match(h):
        return "TRC20 Transaction Hash ৬৪ অক্ষরের হেক্স (0-9, a-f) হতে হবে।"
    if method_type in ("usdt_bep20", "usdt_erc20") and not re.match(r"^0x[0-9a-f]{64}$", h):
        return "Transaction Hash 0x দিয়ে শুরু হওয়া ৬৪ অক্ষরের হেক্স হতে হবে।"
    return None
