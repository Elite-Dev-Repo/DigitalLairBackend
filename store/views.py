from .services import generate_ref, InitiatePaymentView
from django.shortcuts import render
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsAdminorReadOnly
from .models import User, Category, Product, Cart, CartItem, Order
from .serializers import UserSerializer, CategorySerializer, ProductSerializer, CartSerializer, CartItemSerializer, OrderSerializer
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from .pagination import CustomPagination
from django.conf import settings
import json
import hmac
import hashlib


# Create your views here.


class UserRegistrationView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = UserSerializer


class CategoryListCreateView(generics.ListCreateAPIView):
    queryset = Category.objects.all()
    permission_classes = [IsAdminorReadOnly]
    serializer_class = CategorySerializer

class ProductListCreateView(generics.ListCreateAPIView):
    queryset = Product.objects.all()
    permission_classes = [IsAdminorReadOnly]
    serializer_class = ProductSerializer

class RecentProductListView(generics.ListAPIView):
    queryset = Product.objects.all()
    permission_classes = [AllowAny]
    serializer_class = ProductSerializer
    pagination_class = CustomPagination

class ProductDetailView(generics.RetrieveAPIView):
    queryset = Product.objects.all()
    permission_classes = [AllowAny]
    serializer_class = ProductSerializer

class CartListView(generics.RetrieveUpdateAPIView):
    queryset = Cart.objects.prefetch_related('items').all()
    permission_classes = [IsAuthenticated]
    serializer_class = CartSerializer

    def get_object(self):
        return Cart.objects.get(user=self.request.user)






class CartItemListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = CartItemSerializer
    queryset = CartItem.objects.all()


    def perform_create(self, serializer):
            user_cart = Cart.objects.get(user=self.request.user)
            product = serializer.validated_data['product']
            quantity = serializer.validated_data['quantity']
            if product.stock < int(quantity):
                raise ValidationError({'error': 'Insufficient product available'})
            with transaction.atomic():
                cart_item = CartItem.objects.filter(cart=user_cart, product=product).first()
                print(cart_item)
                if cart_item:
                    print('PRODUCT AVAILABLE')
                    cart_item.quantity += int(quantity)
                    cart_item.save()
                else:
                    serializer.save(cart=user_cart)


class CartItemDeleteView(generics.DestroyAPIView):
    permission_classes = [IsAuthenticated]
    lookup_field = 'pk'

    def get_queryset(self):
        return CartItem.objects.filter(cart__user=self.request.user)

    def delete(self, request, pk):
        user = self.request.user
        item = self.get_object()
        if not item.cart.user == user:
            return Response({'error': 'you cannot perform this action'}, status= status.HTTP_403_FORBIDDEN)
        item.delete()
        return Response({'message': 'Item deleted successfully'})



class OrderListCreateView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer
    queryset = Order.objects.select_related('user').prefetch_related('items').all()

    def get(self, request):
        user_orders = self.queryset.filter(user=self.request.user)
        serializer = self.serializer_class(user_orders, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        if serializer.is_valid():
            with transaction.atomic():
                user_cart = Cart.objects.get(user=self.request.user)
                cart_items = list(user_cart.items.all())
                if not cart_items:
                    raise ValidationError({'error': 'Your cart is empty'})
                unique_strings = f"{self.request.user.id}{self.request.user.email}{serializer.validated_data.get('metadata', {})}{user_cart.total}{timezone.now().timestamp()}"
                reference = generate_ref(unique_strings)
                order = serializer.save(user=self.request.user, amount=user_cart.total, email=self.request.user.email, reference=reference)
                
                # Save the items inside the order
                order.items.set(cart_items)
                
                # Decrement product stock levels
                for item in cart_items:
                    item.product.stock -= item.quantity
                    item.product.save()
                
                # Clear items from cart without deleting them so they persist in the order
                user_cart.items.all().update(cart=None)
                
                # Initiate payment with Paystack
                res = InitiatePaymentView({
                    "email":        self.request.user.email,
                    "amount":       float(order.amount) * 100,
                    "reference":    reference,
                    "metadata":     {"payment_id": order.id},
                })

            return Response(res)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class OrderRetrieveUpdateView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = OrderSerializer
    queryset = Order.objects.select_related('user').prefetch_related('items').all()

    def get_object(self):
        return Order.objects.get(user=self.request.user, id=self.kwargs['pk'])

    def perform_update(self, serializer):
        order = self.get_object()
        order.status = serializer.validated_data['status']
        order.save()
        if order.status == 'Cancelled':
            for item in order.items.all():
                item.product.stock += item.quantity
                item.product.save()
            order.delete()



class VerifyPayStackWebhookView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        secret_key = settings.PAYSTACK_SECRET_KEY
        hash = hmac.new(secret_key.encode('utf-8'), request.body, hashlib.sha512).hexdigest()

        if request.method == 'POST':
            with transaction.atomic():
                if hash == request.headers.get('X-Paystack-Signature'):
                    event = request.data.get('event')
                    if event == 'charge.success':
                        order = Order.objects.get(id=request.data.get('metadata')['payment_id'])
                        order.status = 'Paid'
                        order.save()
                        return Response({'message': 'Webhook received successfully'})
                    return Response({'error': 'Invalid event'}, status=status.HTTP_400_BAD_REQUEST)
                return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
            return Response({'error': 'Invalid request method'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)