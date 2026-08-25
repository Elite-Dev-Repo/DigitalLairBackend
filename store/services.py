import hashlib
from django.conf import settings
from rest_framework.response import Response
from rest_framework import status
from .payments import paystack
import requests

def generate_ref(unique_strings):
    return 'TRX-' + hashlib.sha256(unique_strings.encode()).hexdigest()





def InitiatePaymentView(payload):

    res = paystack.post("/transaction/initialize", json={
        "email":        payload["email"],
        "amount":       payload["amount"],
        "reference":    str(payload["reference"]),
        "callback_url": settings.PAYSTACK_CALLBACK_URL,
        "metadata":     payload["metadata"],
        "channels":     ["card", "bank", "ussd", "bank_transfer"],
        })

    body = res.json()
    if not body["status"]:
        return {"error": body["message"]}

    return {
        "authorization_url": body["data"]["authorization_url"],
        "reference":         str(payload["reference"]),
    }