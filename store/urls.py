from django.urls import path
from .views import UserRegistrationView, CartItemListCreateView, CartItemDeleteView, CartListView, ProductListCreateView, RecentProductListView, OrderListCreateView, OrderRetrieveUpdateView, CategoryListCreateView,VerifyPayStackWebhookView

urlpatterns = [
    path('regsiter/', UserRegistrationView.as_view()),
    path('cart/', CartListView.as_view()),
    path('products/', ProductListCreateView.as_view()),
    path('cart_item/', CartItemListCreateView.as_view()),
    path('cart_item/<str:pk>/', CartItemDeleteView.as_view()),
    path('order/', OrderListCreateView.as_view()),
    path('order/<str:pk>/', OrderRetrieveUpdateView.as_view()),
    path('recent_products/', RecentProductListView.as_view()),
    path('category/', CategoryListCreateView.as_view()),
    path('paystack/webhook/', VerifyPayStackWebhookView.as_view()),

]