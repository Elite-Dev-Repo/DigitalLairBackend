import hashlib
from decimal import Decimal
from django.conf import settings
from .payments import pseudopay
import json


def generate_ref(unique_strings):
    return 'TRX-' + hashlib.sha256(unique_strings.encode()).hexdigest()


def hash_request(payload):
    canon = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def initiate_pseudopay_payment(payload, idempotency_key=None):
    """Initialize a DEBIT transaction on PseudoPay (mock provider).

    payload keys: email, customer_name, amount (Decimal/float, NGN),
                  reference (our Order.reference), metadata (dict, must be JSON-serializable,
                  should include payment_id/order linkage), wallet_id (optional override).
    Returns {"checkout_url", "pseudopay_reference", "raw"} on success,
    or {"error": msg} on provider rejection / transport failure.
    """
    wallet_id = payload.get("wallet_id") or getattr(settings, "PSEUDOPAY_WALLET_ID", "")
    try:
        amount = Decimal(str(payload["amount"]))
    except Exception:
        return {"error": "Invalid amount"}

    body = {
        "wallet": int(wallet_id) if str(wallet_id).isdigit() else wallet_id,
        "amount": str(amount),
        "transaction_type": "DEBIT",
        "customer_email": payload.get("email", ""),
        "customer_name": payload.get("customer_name") or payload.get("email", ""),
        "transaction_metadata": {
            "order_id": (payload.get("metadata") or {}).get("payment_id"),
            "reference": str(payload.get("reference", "")),
            "metadata": payload.get("metadata") or {},
        },
    }

    try:
        res = pseudopay.post(
            "/transaction/initialize/",
            json=body,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        return {"error": f"PseudoPay unreachable: {exc}"}

    try:
        data = res.json()
    except Exception:
        return {"error": f"PseudoPay returned non-JSON (HTTP {res.status_code})"}

    if res.status_code not in (200, 201):
        # PseudoPay error shapes: {"error": ...} or serializer errors dict
        if isinstance(data, dict) and "error" in data:
            return {"error": data["error"]}
        return {"error": f"PseudoPay rejected request: {data}"}

    checkout_url = data.get("checkout_url")
    pseudo_ref = data.get("transaction_reference")
    if not checkout_url or not pseudo_ref:
        return {"error": f"PseudoPay response missing checkout_url/reference: {data}"}

    return {
        "checkout_url": checkout_url,
        "pseudopay_reference": pseudo_ref,
        "raw": data,
    }
