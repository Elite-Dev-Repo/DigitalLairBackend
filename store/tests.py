from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import User, Category, Product, Cart, CartItem, Order
from decimal import Decimal
from unittest.mock import patch

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
            description="A test laptop",
            price=Decimal("1500.00"),
            category=self.category,
            stock=10,
            status="Available"
        )

        # Create cart and cart item
        self.cart = Cart.objects.create(user=self.user)
        self.cart_item = CartItem.objects.create(
            cart=self.cart,
            product=self.product,
            quantity=2
        )

    @patch('store.services.paystack.post')
    def test_order_creation_saves_items_and_returns_payment_response(self, mock_paystack_post):
        # Mock Paystack initialize response
        mock_response = mock_paystack_post.return_value
        mock_response.json.return_value = {
            "status": True,
            "message": "Initialization successful",
            "data": {
                "authorization_url": "https://checkout.paystack.com/mock-auth-url",
                "reference": "mock-ref"
            }
        }

        # Let's make the POST request directly.
        response = self.client.post("/api/order/", data={}, format='json')
        
        # Print actual response for debugging
        print("RESPONSE STATUS:", response.status_code)
        print("RESPONSE DATA:", response.data)

        # Assertions to see if it behaves as expected
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("authorization_url", response.data)
        
        # Verify that order has items
        order = Order.objects.first()
        self.assertIsNotNone(order)
        print("ORDER ITEMS IN TEST:", list(order.items.all()))
        self.assertEqual(order.items.count(), 1)
