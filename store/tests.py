from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import User, Category, Product, Cart, CartItem, Order, IdempotencyRecord
from decimal import Decimal
from unittest.mock import patch
import uuid


def _mock_init(ref="TRX-mockref123", url="http://127.0.0.1:8001/api/checkout/TRX-mockref123"):
    mock_response = type("R", (), {})()
    mock_response.status_code = 201
    mock_response.json = lambda: {
        "transaction_reference": ref,
        "checkout_url": url,
        "transaction_status": "INITIATED",
    }
    return mock_response


class OrderCreationTestCase(APITestCase):
    def setUp(self):
        # Create user
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
            gender="Male"
        )
        self.user.is_active = True
        self.user.save()
        self.client.force_authenticate(user=self.user)

        # Create category and product
        self.category = Category.objects.create(name="Electronics")
        self.product = Product.objects.create(
            name="Laptop",
            price=Decimal("1500.00"),
            category=self.category,
            stock=10,
            status="Available"
        )

        # Create cart and cart item (a cart is auto-created by signal; reuse it)
        self.cart = Cart.objects.filter(user=self.user).order_by('-created_at').first()
        if self.cart is None:
            self.cart = Cart.objects.create(user=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            quantity=2
        )
        self.idem_key = str(uuid.uuid4())

    def _post_order(self, key=None, body=None):
        return self.client.post(
            "/api/order/",
            data={} if body is None else body,
            format='json',
            HTTP_IDEMPOTENCY_KEY=key or self.idem_key,
        )

    @patch('store.services.pseudopay.post')
    def test_order_creation_saves_items_and_returns_payment_response(self, mock_post):
        mock_post.return_value = _mock_init()

        response = self._post_order()

        print("RESPONSE STATUS:", response.status_code)
        print("RESPONSE DATA:", response.data)

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("checkout_url", response.data)
        self.assertIn("authorization_url", response.data)  # frontend compat alias
        self.assertIn("pseudopay_reference", response.data)

        order = Order.objects.first()
        self.assertIsNotNone(order)
        print("ORDER ITEMS IN TEST:", list(order.items.all()))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.pseudopay_reference, "TRX-mockref123")

    @patch('store.services.pseudopay.post')
    def test_order_requires_idempotency_key(self, mock_post):
        mock_post.return_value = _mock_init()
        response = self.client.post("/api/order/", data={}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch('store.services.pseudopay.post')
    def test_order_idempotent_replay(self, mock_post):
        mock_post.return_value = _mock_init()
        key = str(uuid.uuid4())
        r1 = self._post_order(key=key)
        # Re-stock cart for second call simulation is NOT needed: replay happens
        # before any order logic, so provider must be hit exactly once.
        r2 = self._post_order(key=key)
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r1.data, r2.data)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(mock_post.call_count, 1)

    @patch('store.services.pseudopay.post')
    def test_order_idempotency_conflict(self, mock_post):
        mock_post.return_value = _mock_init()
        key = str(uuid.uuid4())
        r1 = self._post_order(key=key, body={})
        r2 = self._post_order(key=key, body={"metadata": {"note": "different"}})
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED)
        self.assertEqual(r2.status_code, status.HTTP_409_CONFLICT)


class PseudoPayWebhookTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="hook@example.com", password="pw12345678",
            first_name="H", last_name="K", gender="Male",
        )
        self.order = Order.objects.create(
            user=self.user, email=self.user.email, amount=Decimal("1500.00"),
            reference="TRX-abc", pseudopay_reference="TRX-pseudo123",
            checkout_url="http://x/checkout/TRX-pseudo123",
            metadata={"payment_id": 1}, status="Initiated",
        )

    def test_webhook_marks_paid_and_replays(self):
        body = {"transaction_reference": "TRX-pseudo123", "amount": "1500.00",
                "status": "SUCCESSFUL"}
        r1 = self.client.post("/api/pseudopay/webhook/", data=body, format='json')
        self.assertEqual(r1.status_code, status.HTTP_200_OK)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "Paid")
        r2 = self.client.post("/api/pseudopay/webhook/", data=body, format='json')
        self.assertEqual(r2.status_code, status.HTTP_200_OK)
        self.assertIn("already processed", r2.data["message"])

    def test_webhook_unknown_reference_404(self):
        r = self.client.post("/api/pseudopay/webhook/",
                             data={"transaction_reference": "TRX-nope", "status": "SUCCESSFUL"},
                             format='json')
        self.assertEqual(r.status_code, status.HTTP_404_NOT_FOUND)

    def test_webhook_amount_mismatch_400(self):
        r = self.client.post("/api/pseudopay/webhook/",
                             data={"transaction_reference": "TRX-pseudo123",
                                   "amount": "1.00", "status": "SUCCESSFUL"},
                             format='json')
        self.assertEqual(r.status_code, status.HTTP_400_BAD_REQUEST)

    def test_paystack_webhook_deprecated(self):
        r = self.client.post("/api/paystack/webhook/", data={}, format='json')
        self.assertEqual(r.status_code, status.HTTP_410_GONE)
