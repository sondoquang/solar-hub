from django.urls import path

from .views import MailSettingsTestView, MailSettingsView

urlpatterns = [
    path("mail-settings/", MailSettingsView.as_view(), name="mail-settings"),
    path("mail-settings/test/", MailSettingsTestView.as_view(), name="mail-settings-test"),
]
