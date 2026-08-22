from django.urls import path

from .views import model_credential_view


urlpatterns = [
    path("model-credential/", model_credential_view),
]
