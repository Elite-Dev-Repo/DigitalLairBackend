from .services import generate_ref, initiate_pseudopay_payment, hash_request
from django.shortcuts import render
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from .permissions import IsAdminorReadOnly
from .models import User, Category, Product, Cart, CartItem, Order, IdempotencyRecord
from .serializers import UserSerializer, CategorySerializer, ProductSerializer, CartSerializer, CartItemSerializer, OrderSerializer
from django.db import transaction
from rest_framework.exceptions import ValidationError
from django.utils import timezone
from .pagination import CustomPagination, ProductPagination
from django.conf import settings
from decimal import Decimal, InvalidOperation
import json
import hmac
import hashlib
import uuid


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
    pagination_class = ProductPagination

    # def get_queryset(self):
    #     queryset = super().get_queryset()
    #     category = self.request.query_params.get('category')
    #     if category:
    #         queryset = queryset.filter(category__name=category)
    #     return queryset

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
        # --- 1. Require a UUID Idempotency-Key (same key is forwarded to PseudoPay) ---
        raw_key = request.headers.get('Idempotency-Key')
        try:
            idem_key = uuid.UUID(str(raw_key))
        except (ValueError, TypeError, AttributeError):
            return Response(
                {'error': 'A valid Idempotency-Key header (UUID) is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.serializer_class(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Hash the meaningful request body so a reused key with a different
        # payload is a 409 (not a silent replay).
        request_hash = hash_request({
            'metadata': serializer.validated_data.get('metadata', {}),
            'email': self.request.user.email,
        })

        with transaction.atomic():
            record, created = IdempotencyRecord.objects.select_for_update().get_or_create(
                user=self.request.user,
                key=idem_key,
                defaults={'request_hash': request_hash, 'response_status': 0, 'response_data': {}},
            )
            if not created:
                if record.request_hash != request_hash:
                    return Response(
                        {'error': 'Idempotency-Key already used with a different request body'},
                        status=status.HTTP_409_CONFLICT,
                    )
                if record.response_data:
                    # Replay stored response — no new order, no new PseudoPay call.
                    return Response(record.response_data, status=record.response_status or status.HTTP_200_OK)

            # --- 2. Create the order atomically (NO external HTTP in here) ---
            # NOTE: Cart.objects.get(user=...) can raise MultipleObjectsReturned
            # (signal auto-creates a cart + seeds). Pick the cart holding items.
            carts = list(Cart.objects.filter(user=self.request.user).order_by('-created_at'))
            if not carts:
                return Response({'error': 'No cart found for user'}, status=status.HTTP_400_BAD_REQUEST)
            user_cart = next((c for c in carts if c.items.exists()), carts[0])
            cart_items = list(user_cart.items.select_related('product').all())
            if not cart_items:
                raise ValidationError({'error': 'Your cart is empty'})
            unique_strings = f"{self.request.user.id}{self.request.user.email}{serializer.validated_data.get('metadata', {})}{user_cart.total}{timezone.now().timestamp()}"
            reference = generate_ref(unique_strings)
            order = serializer.save(
                user=self.request.user,
                amount=user_cart.total,
                email=self.request.user.email,
                reference=reference,
            )
            order.items.set(cart_items)
            for item in cart_items:
                if item.product is None:
                    continue
                item.product.stock -= item.quantity
                item.product.save()
            # Clear items from cart without deleting them so they persist in the order
            user_cart.items.all().update(cart=None)

        # --- 3. Initialize payment with PseudoPay OUTSIDE the atomic block ---
        metadata = serializer.validated_data.get('metadata', {}) or {}
        customer_name = (metadata.get('full_name') or '').strip() if isinstance(metadata, dict) else ''
        init = initiate_pseudopay_payment(
            {
                'email': self.request.user.email,
                'customer_name': customer_name or f"{self.request.user.first_name} {self.request.user.last_name}".strip(),
                'amount': order.amount,
                'reference': reference,
                'metadata': {'payment_id': order.id, **(metadata if isinstance(metadata, dict) else {})},
            },
            idempotency_key=str(idem_key),
        )
        if 'error' in init:
            # Roll back the reservation: restore stock, release items back to cart, drop order.
            with transaction.atomic():
                fallback_cart = Cart.objects.filter(user=self.request.user).order_by('-created_at').first()
                for item in order.items.select_related('product').all():
                    if item.product is not None:
                        item.product.stock += item.quantity
                        item.product.save()
                    if fallback_cart is not None:
                        item.cart = fallback_cart
                        item.save(update_fields=['cart'])
                order.delete()
            return Response({'error': init['error']}, status=status.HTTP_502_BAD_GATEWAY)

        order.pseudopay_reference = init['pseudopay_reference']
        order.checkout_url = init['checkout_url']
        order.save(update_fields=['pseudopay_reference', 'checkout_url'])

        response_data = {
            'order_id': order.id,
            'reference': reference,
            'pseudopay_reference': init['pseudopay_reference'],
            'checkout_url': init['checkout_url'],
            # Alias for the old Paystack-shaped frontend + docs:
            'authorization_url': init['checkout_url'],
            'amount': str(order.amount),
            'status': order.status,
        }
        record.request_hash = request_hash
        record.response_status = status.HTTP_201_CREATED
        record.response_data = response_data
        record.save(update_fields=['request_hash', 'response_status', 'response_data'])
        return Response(response_data, status=status.HTTP_201_CREATED)



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


class OrderVerifyView(APIView):
    """Return current payment state for an order (frontend polls this after
    returning from the PseudoPay hosted checkout).

    NOTE: PseudoPay exposes GET /api/transaction/ under merchant JWT auth only,
    so DigitalLair (API-Key holder) cannot server-side reconcile against the
    provider. This endpoint reports our own authoritative state, which the
    webhook (below) advances to Paid. If PseudoPay later adds an API-Key
    readable GET /api/transaction/<ref>/, reconcile here.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            order = Order.objects.get(user=request.user, id=pk)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'order_id': order.id,
            'reference': order.reference,
            'pseudopay_reference': order.pseudopay_reference,
            'checkout_url': order.checkout_url,
            'amount': str(order.amount),
            'status': order.status,
            'paid': order.status == 'Paid',
        })


class VerifyPseudoPayWebhookView(APIView):
    """Receive PseudoPay transaction webhooks and mark orders Paid (idempotent).

    Accepted payload (current mock shape + recommended extended shape):
      {"transaction_id": 12, "amount": "1000.00", "status": "SUCCESSFUL",
       "created_at": "...", "transaction_reference": "TRX-... (optional)",
       "transaction_metadata": {"order_id": 7, ...} (optional)}
    Resolution order: metadata.order_id -> transaction_reference/pseudopay_reference
                      -> transaction_id (stored? we store reference, so id is last resort
                         via metadata echo only).
    Configure PSEUDOPAY_WEBHOOK_SECRET to require
    X-PseudoPay-Signature: HMAC_SHA256(secret, raw_body). Empty secret = accept
    unsigned (mock default).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        secret = getattr(settings, 'PSEUDOPAY_WEBHOOK_SECRET', '') or ''
        if secret:
            expected = hmac.new(secret.encode('utf-8'), request.body, hashlib.sha256).hexdigest()
            got = request.headers.get('X-PseudoPay-Signature', '')
            if not got or not hmac.compare_digest(expected, got):
                return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data if isinstance(request.data, dict) else {}
        meta = data.get('transaction_metadata') or {}
        order_id = meta.get('order_id') if isinstance(meta, dict) else None
        pseudo_ref = data.get('transaction_reference') or data.get('reference') or ''
        txn_status = str(data.get('status', '')).upper()
        amount_raw = data.get('amount')

        print(f"[pseudopay webhook] ref={pseudo_ref} order_id={order_id} status={txn_status} amount={amount_raw}")

        with transaction.atomic():
            order = None
            if order_id is not None:
                try:
                    order = Order.objects.select_for_update().get(id=order_id)
                except Order.DoesNotExist:
                    return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
            elif pseudo_ref:
                try:
                    order = Order.objects.select_for_update().get(pseudopay_reference=pseudo_ref)
                except Order.DoesNotExist:
                    return Response({'error': 'Order not found for transaction_reference'},
                                    status=status.HTTP_404_NOT_FOUND)
            else:
                return Response(
                    {'error': 'Cannot link webhook to order: include transaction_metadata.order_id '
                              'or transaction_reference in the webhook payload'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if order.status == 'Paid':
                return Response({'message': 'Webhook already processed'}, status=status.HTTP_200_OK)

            if txn_status != 'SUCCESSFUL':
                return Response({'error': f'Unhandled transaction status: {txn_status or "missing"}'},
                                status=status.HTTP_400_BAD_REQUEST)

            if amount_raw is not None:
                try:
                    if Decimal(str(amount_raw)) != order.amount:
                        return Response({'error': 'Amount mismatch'}, status=status.HTTP_400_BAD_REQUEST)
                except (InvalidOperation, ValueError, TypeError):
                    return Response({'error': 'Invalid amount in webhook'}, status=status.HTTP_400_BAD_REQUEST)

            order.status = 'Paid'
            order.save(update_fields=['status'])
            return Response({'message': 'Webhook received successfully'}, status=status.HTTP_200_OK)


class VerifyPayStackWebhookView(APIView):
    """Deprecated Paystack endpoint — kept so old integrations fail loudly."""
    permission_classes = [AllowAny]

    def post(self, request):
        return Response(
            {'error': 'Paystack is no longer supported. Use POST /api/pseudopay/webhook/ instead.'},
            status=status.HTTP_410_GONE,
        )
