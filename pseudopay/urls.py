from django.urls import path

# PseudoPay-related routes live in store.urls (pseudopay/webhook/, order verify).
# This module exists so DigitalLairBackend/urls.py `include('pseudopay.urls')` imports cleanly.
urlpatterns = []
