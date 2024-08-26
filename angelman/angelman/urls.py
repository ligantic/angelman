from django.conf.urls import include
from django.urls import re_path
from django.views.generic import RedirectView

from rdrf.views.handler_views import (
    handler404,
    handler500,
    handler_application_error,
    handler_exceptions,
)

urlpatterns = [
    re_path(r"^$", RedirectView.as_view(url="router/", permanent=False)),
    re_path(r"", include("rdrf.urls")),
]

handler404 = handler404
handler500 = handler500
handler_application_error = handler_application_error
handler_exceptions = handler_exceptions
