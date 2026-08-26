from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
import hashlib
from cloudinary.models import CloudinaryField


# Create your models here.

class UserModelManager(BaseUserManager):
    """Manager for email-based authentication."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')

        email = self.normalize_email(email)
        extra_fields.setdefault('is_active', False)

        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_active') is not True:
            raise ValueError('Superuser must have is_active=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        if not password:
            raise ValueError('Superuser must have a password.')

        return self.create_user(email, password, **extra_fields)



class User(AbstractUser):
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
    ]
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES)
    email = models.EmailField(unique=True)
    USERNAME_FIELD = 'email'
    username = None
    REQUIRED_FIELDS = []
    objects = UserModelManager()

    def __str__(self):
        return f"User - {self.email}"




class Category(models.Model):
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name



class Product(models.Model):
    PRODUCT_STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Out of Stock', 'Out of Stock'),
    ]

    id = models.CharField(primary_key=True)
    name = models.CharField(max_length=100)
    # description = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    tags = models.JSONField(default=list)
    stock = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=20, choices=PRODUCT_STATUS_CHOICES, default='Available')
    image = CloudinaryField('digital_lair/images', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


    @property
    def is_available(self):
        return self.status == 'Available'

    def save(self, *args, **kwargs):
        if not self.id:
            unique_string = f"{self.name}{self.price}{self.category}{self.stock}{self.status}{self.created_at}"
            self.id = f"PROD-{hashlib.sha256(unique_string.encode()).hexdigest()[:16]}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class Cart(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def total(self):
        return sum(
            (item.product.price * item.quantity for item in self.items.all()),
            Decimal('0.00')
        )

    def __str__(self):
        return f"Cart - {self.user.email}"



class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.SET_NULL, null=True, blank=True, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True)
    quantity = models.IntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # unique_together = ('cart', 'product')
        ordering = ['-created_at']

    @property
    def subtotal(self):
        return self.product.price * self.quantity

    def __str__(self):
        return f"Cart Item - {self.product.name}"




class Order(models.Model):
    ORDER_STATUS_CHOICES = [
        ('Initiated', 'Initiated'),
        ('Paid', 'Paid'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    items = models.ManyToManyField(CartItem)
    email = models.EmailField(default='')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reference = models.CharField(max_length=100, default='')
    metadata = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='Initiated')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Order - {self.user.email}"