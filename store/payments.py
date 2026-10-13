import requests
from django.conf import settings

BASE = getattr(settings, "PSEUDOPAY_BASE_URL", "http://127.0.0.1:8001/api")
TIMEOUT = getattr(settings, "PSEUDOPAY_TIMEOUT", 30)


class PseudoPayClient:
    """HTTP client for the PseudoPay mock provider.

    Auth: X-Api-Key header (sk_pseudo_...). Fallback Authorization: Api-Key <token>
    is also accepted server-side, but we always send X-Api-Key.
    Idempotency: PseudoPay requires Idempotency-Key: <uuid4> on initialize.
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "X-Api-Key": getattr(settings, "PSEUDOPAY_API_KEY", ""),
            "Content-Type": "application/json",
        })

    def _url(self, path):
        return f"{BASE.rstrip('/')}{path}"

    def _with_idempotency(self, kwargs, idempotency_key):
        if idempotency_key:
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault("Idempotency-Key", str(idempotency_key))
            kwargs["headers"] = headers
        return kwargs

    def get(self, path, idempotency_key=None, **kwargs):
        kwargs = self._with_idempotency(kwargs, idempotency_key)
        return self.session.get(self._url(path), timeout=TIMEOUT, **kwargs)

    def post(self, path, idempotency_key=None, **kwargs):
        kwargs = self._with_idempotency(kwargs, idempotency_key)
        return self.session.post(self._url(path), timeout=TIMEOUT, **kwargs)

    def put(self, path, idempotency_key=None, **kwargs):
        kwargs = self._with_idempotency(kwargs, idempotency_key)
        return self.session.put(self._url(path), timeout=TIMEOUT, **kwargs)

    def delete(self, path, idempotency_key=None, **kwargs):
        kwargs = self._with_idempotency(kwargs, idempotency_key)
        return self.session.delete(self._url(path), timeout=TIMEOUT, **kwargs)


# Singleton — import this throughout your app
pseudopay = PseudoPayClient()
