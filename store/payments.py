import requests
from django.conf import settings

BASE    = getattr(settings, "PAYSTACK_BASE_URL")
TIMEOUT = getattr(settings, "PAYSTACK_TIMEOUT", 30)


class PaystackClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type":  "application/json",
        })

    def get(self, path, **kwargs):
        return self.session.get(f"{BASE}{path}", timeout=TIMEOUT, **kwargs)

    def post(self, path, **kwargs):
        return self.session.post(f"{BASE}{path}", timeout=TIMEOUT, **kwargs)

    def put(self, path, **kwargs):
        return self.session.put(f"{BASE}{path}", timeout=TIMEOUT, **kwargs)

    def delete(self, path, **kwargs):
        return self.session.delete(f"{BASE}{path}", timeout=TIMEOUT, **kwargs)


# Singleton — import this throughout your app
paystack = PaystackClient()