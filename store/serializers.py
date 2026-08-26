from rest_framework import serializers
from .models import User, Category, Product, Cart, CartItem, Order

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'date_of_birth', 'gender', 'email', 'password']
        extra_kwargs = {'password': {'write_only': True}}

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        return user

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']

class ProductSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    class Meta:
        model = Product
        fields = ['id', 'name', 'price', 'category', 'tags', 'stock', 'status', 'is_available', 'image_url']
        extra_kwargs = {'id': {'read_only': True}}

    def get_category(self, obj):
        return obj.category.name if obj.category else None

    def get_image_url(self, obj):
        return obj.image.url if obj.image else None

class CartItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CartItem
        fields = ['id', 'product', 'quantity', 'subtotal']



class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    total = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ['id', 'user', 'items', 'total', 'created_at']
        extra_kwargs = {'id': {'read_only': True}, 'created_at': {'read_only': True}, 'total': {'read_only': True}, 'user': {'read_only': True}, 'items': {'read_only': True} }

    def get_total(self, obj):
        return obj.total


class OrderSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    class Meta:
        model = Order
        fields = ['id', 'user', 'items', 'amount', 'email', 'reference', 'metadata', 'status', 'created_at']
        extra_kwargs = {'id': {'read_only': True}, 'user': {'read_only': True}, 'reference': {'read_only': True}, 'status': {'read_only': True}, 'created_at': {'read_only': True}, 'amount': {'read_only': True}, 'email': {'read_only': True}, 'items': {'read_only': True} }

    def get_items(self, obj):
        return obj.items.all()
