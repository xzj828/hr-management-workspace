from django.urls import path

from .views import model_credential_test_view, model_credential_view


urlpatterns = [
    path("model-credential/", model_credential_view),
    path("model-credential/test/", model_credential_test_view),
]
