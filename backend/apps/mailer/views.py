"""Mail settings API.

- ``GET/PUT/PATCH /api/mail-settings/`` — read/update the singleton SMTP config.
- ``POST /api/mail-settings/test/``    — send a test email to verify the account.

The manual "send selected orders to an address" action lives on the orders
viewset (``POST /api/orders/send_email/``) since it operates on orders.
"""

import logging
import smtplib

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import MailSettings
from .serializers import MailSettingsSerializer

logger = logging.getLogger(__name__)


class MailSettingsView(generics.RetrieveUpdateAPIView):
    """The single system-wide SMTP config row (auto-created on first read)."""

    serializer_class = MailSettingsSerializer

    def get_object(self):
        return MailSettings.load()


class MailSettingsTestView(APIView):
    """Send a test email to the given ``recipient`` (or the saved recipients)."""

    def post(self, request):
        recipient = request.data.get("recipient") or request.data.get("recipients")
        try:
            services.send_test_email(recipient or [])
        except services.MailNotConfigured as exc:
            return Response(
                {"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST
            )
        except (smtplib.SMTPException, OSError):
            # No PII / no credentials in the log — just the failure.
            logger.error("mailer: test email failed (SMTP error)")
            return Response(
                {"detail": "Không gửi được email. Kiểm tra lại cấu hình SMTP."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"ok": True})
