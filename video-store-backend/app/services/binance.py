"""
Binance Pay API integration.
Only called from backend — API keys never exposed to frontend.
"""
import base64
import hashlib
import hmac
import json
import time
import uuid
import logging
from datetime import datetime, timezone

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.core.config import settings

logger = logging.getLogger(__name__)

BINANCE_PAY_BASE = settings.BINANCE_PAY_BASE_URL


def _build_signature(timestamp: str, nonce: str, body: str) -> str:
    """HMAC-SHA512 signature for Binance Pay API."""
    payload = f"{timestamp}\n{nonce}\n{body}\n"
    return hmac.new(
        settings.BINANCE_PAY_API_SECRET.encode(),
        payload.encode(),
        hashlib.sha512,
    ).hexdigest().upper()


def _build_headers(body: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    nonce = uuid.uuid4().hex
    signature = _build_signature(timestamp, nonce, body)
    return {
        "Content-Type": "application/json",
        "BinancePay-Timestamp": timestamp,
        "BinancePay-Nonce": nonce,
        "BinancePay-Certificate-SN": settings.BINANCE_PAY_API_KEY,
        "BinancePay-Signature": signature,
    }


async def create_prepay_order(
    order_id: str,
    amount_usdt: float,
    description: str,
    return_url: str,
    cancel_url: str,
    webhook_url: str,
    expire_at: datetime | None = None,
) -> dict:
    """
    Create a Binance Pay prepay order.
    Returns { prepay_id, checkout_url } on success.
    Raises RuntimeError on failure.
    """
    if not settings.BINANCE_PAY_API_KEY:
        raise RuntimeError("Binance Pay not configured")

    body_dict = {
        "env": {"terminalType": "APP"},
        "merchantTradeNo": order_id,
        "orderAmount": round(amount_usdt, 8),
        "currency": "USDT",
        "goods": {
            "goodsType": "02",
            "goodsCategory": "Z000",
            "referenceGoodsId": order_id,
            "goodsName": description[:256],
        },
        "returnUrl": return_url,
        "cancelUrl": cancel_url,
        "webhookUrl": webhook_url,
    }
    if expire_at is not None:
        # Keep Binance's checkout window equal to OUR order window (admin-set timeout).
        body_dict["orderExpireTime"] = int(expire_at.timestamp() * 1000)
    body = json.dumps(body_dict)
    headers = _build_headers(body)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BINANCE_PAY_BASE}/binancepay/openapi/v2/order",
            content=body,
            headers=headers,
        )

    data = resp.json()
    if data.get("status") != "SUCCESS":
        logger.error(f"Binance Pay order failed: {data}")
        raise RuntimeError(f"Binance Pay error: {data.get('errorMessage', 'Unknown')}")

    result = data["data"]
    return {
        "prepay_id": result["prepayId"],
        "checkout_url": result["checkoutUrl"],
    }


def verify_binance_webhook(
    body: str,
    timestamp: str,
    nonce: str,
    signature: str,
) -> bool:
    """
    Verify Binance Pay webhook HMAC-SHA512.
    Must be called before processing any webhook event.
    """
    expected = _build_signature(timestamp, nonce, body)
    # bytes compare: str compare_digest raises TypeError for non-ASCII input.
    return hmac.compare_digest(expected.encode(), signature.upper().encode("utf-8"))


async def query_order_status(prepay_id: str) -> str:
    """
    Query Binance Pay for order status (fallback if webhook missed).
    Returns status string: 'INITIAL'|'PENDING'|'PAID'|'CANCELED'|'ERROR'
    """
    body_dict = {"prepayId": prepay_id}
    body = json.dumps(body_dict)
    headers = _build_headers(body)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{BINANCE_PAY_BASE}/binancepay/openapi/v2/order/query",
            content=body,
            headers=headers,
        )

    data = resp.json()
    if data.get("status") != "SUCCESS":
        return "ERROR"
    return data.get("data", {}).get("status", "ERROR")


# ─── Phase 10 Part 2A: authoritative verification ─────────────────────────────
class BinanceUnavailable(RuntimeError):
    """Binance could not be asked (not configured / network / non-SUCCESS reply).
    NEVER means "not paid" — callers must leave the order untouched and retry later."""


async def _signed_post(path: str, body_dict: dict) -> dict:
    if not settings.BINANCE_PAY_API_KEY or not settings.BINANCE_PAY_API_SECRET:
        raise BinanceUnavailable("Binance Pay not configured")
    body = json.dumps(body_dict)
    headers = _build_headers(body)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{BINANCE_PAY_BASE}{path}", content=body, headers=headers)
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 - network / JSON errors are all "unavailable"
        raise BinanceUnavailable(f"Binance request failed: {type(exc).__name__}") from exc
    if data.get("status") != "SUCCESS":
        raise BinanceUnavailable(f"Binance error: {data.get('code')} {data.get('errorMessage')}")
    return data.get("data") or {}


async def query_order(merchant_trade_no: str) -> dict:
    """
    Official Binance Pay order query by OUR order id (merchantTradeNo). This is the
    source of truth for "was it paid": the request is signed with our API secret,
    so its answer cannot be forged by a user or by someone posting to our webhook.
    Returns the raw `data` object (status, currency, orderAmount, ...).
    """
    return await _signed_post("/binancepay/openapi/v2/order/query", {"merchantTradeNo": merchant_trade_no})


# Webhook authenticity. Binance signs webhooks with its OWN private key
# (SHA256withRSA over "timestamp\nnonce\nbody\n"); the matching public key is
# served by the certificates endpoint, selected by BinancePay-Certificate-SN.
_CERT_CACHE: dict[str, tuple[str, float]] = {}
_CERT_TTL_SECONDS = 3600


async def _certificate_pem(serial: str) -> str | None:
    now = time.monotonic()
    hit = _CERT_CACHE.get(serial)
    if hit and now - hit[1] < _CERT_TTL_SECONDS:
        return hit[0]
    data = await _signed_post("/binancepay/openapi/certificates", {})
    certs = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
    for c in certs:
        if isinstance(c, dict) and c.get("certSerial") and c.get("certPublic"):
            _CERT_CACHE[str(c["certSerial"])] = (c["certPublic"], now)
    hit = _CERT_CACHE.get(serial)
    return hit[0] if hit else None


def verify_rsa_signature(public_pem: str, body: str, timestamp: str, nonce: str, signature_b64: str) -> bool:
    """Pure check (no network): SHA256withRSA over timestamp\nnonce\nbody\n."""
    try:
        pem = public_pem.encode()
        if b"BEGIN CERTIFICATE" in pem:
            key = load_pem_x509_certificate(pem).public_key()
        else:
            key = load_pem_public_key(pem)
        key.verify(
            base64.b64decode(signature_b64),
            f"{timestamp}\n{nonce}\n{body}\n".encode(),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


async def verify_webhook_signature(body: str, timestamp: str, nonce: str, signature: str, cert_serial: str) -> bool:
    """
    True only for a genuine Binance webhook. Fail CLOSED: a missing key/certificate
    or a bad signature is False. Raises BinanceUnavailable when the certificate
    cannot be fetched (the caller answers 503 so Binance retries).
    The legacy HMAC form is still accepted (it needs our secret, so it is not forgeable).
    """
    if verify_binance_webhook(body, timestamp, nonce, signature):
        return True
    if not cert_serial:
        return False
    pem = await _certificate_pem(cert_serial)
    return bool(pem) and verify_rsa_signature(pem, body, timestamp, nonce, signature)
