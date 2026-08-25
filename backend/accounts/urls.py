from django.urls import path

from .views import (
    model_credential_test_view,
    model_credential_view,
    model_profile_activate_view,
    model_profile_detail_view,
    model_profile_list_view,
    model_profile_test_view,
)


urlpatterns = [
    path("model-credential/", model_credential_view),
    path("model-credential/test/", model_credential_test_view),
    path("model-profiles/", model_profile_list_view),
    path("model-profiles/<int:profile_id>/", model_profile_detail_view),
    path("model-profiles/<int:profile_id>/activate/", model_profile_activate_view),
    path("model-profiles/<int:profile_id>/test/", model_profile_test_view),
]
