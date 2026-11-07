"""Redact secret query parameters from log text (stdlib only).

Monetag authenticates its GET postback with a secret in the URL query, and
uvicorn's access log prints the full request line — so it must be scrubbed.
"""
import logging
import re

_PATTERN = re.compile(r"([?&](?:secret|key|token)=)[^&\s\"']*", re.IGNORECASE)


def redact_secrets(text: str) -> str:
    return _PATTERN.sub(r"\1[REDACTED]", text)


class RedactSecretsFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.msg, str):
                record.msg = redact_secrets(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(redact_secrets(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: redact_secrets(v) if isinstance(v, str) else v for k, v in record.args.items()}
        except Exception:  # logging must never break the request
            pass
        return True
