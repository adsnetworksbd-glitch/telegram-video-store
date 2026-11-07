"""Transaction ledger — records every financial event."""
from datetime import datetime, timezone
from typing import Literal
import uuid
import logging

from google.cloud.firestore_v1 import AsyncClient
from app.db.firebase import Col

logger = logging.getLogger(__name__)


async def record_transaction(
    db: AsyncClient,
    user_id: str,
    type_: str,
    amount_bdt: float,
    direction: Literal["credit", "debit"],
    reference_type: str,
    reference_id: str,
    description: str,
    tx_id: str | None = None,   # deterministic id → idempotent re-recording
) -> str:
    doc = {
        "user_id": user_id,
        "type": type_,
        "amount_bdt": amount_bdt,
        "direction": direction,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "description": description,
        "created_at": datetime.now(timezone.utc),
    }
    if tx_id:
        # Deterministic id → create-once. A repeated call (crash recovery, two
        # racing fulfilments) must neither duplicate the ledger row nor add the
        # amount to total_spent_bdt a second time.
        from google.api_core.exceptions import AlreadyExists
        try:
            await db.collection(Col.TRANSACTIONS).document(tx_id).create(doc)
        except AlreadyExists:
            logger.info(f"Transaction {tx_id} already recorded — skipped")
            return tx_id
    else:
        tx_id = str(uuid.uuid4())
        await db.collection(Col.TRANSACTIONS).document(tx_id).set(doc)

    # Update user total_spent_bdt
    if direction == "debit" and type_ == "purchase":
        user_ref = db.collection(Col.USERS).document(user_id)
        doc = await user_ref.get()
        if doc.exists:
            current = (doc.to_dict() or {}).get("total_spent_bdt", 0.0)
            await user_ref.update({"total_spent_bdt": current + amount_bdt})

    logger.info(f"Transaction {tx_id}: {direction} {amount_bdt} BDT for user {user_id}")
    return tx_id
