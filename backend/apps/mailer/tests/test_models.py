import pytest

from apps.mailer.models import MailSettings


@pytest.mark.django_db
def test_password_round_trips_and_is_encrypted_at_rest():
    s = MailSettings.load()
    s.set_password("super-secret")
    s.save()

    reloaded = MailSettings.load()
    # Stored ciphertext is not the plaintext…
    assert bytes(reloaded.password_enc) != b"super-secret"
    # …but decrypts back to it.
    assert reloaded.get_password() == "super-secret"
    assert reloaded.has_password is True


@pytest.mark.django_db
def test_blank_password_clears_secret():
    s = MailSettings.load()
    s.set_password("x")
    s.save()
    s.set_password("")
    s.save()
    assert MailSettings.load().get_password() == ""
    assert MailSettings.load().has_password is False


@pytest.mark.django_db
def test_singleton_pins_pk():
    a = MailSettings.load()
    a.username = "a@x.com"
    a.save()
    # A second "create" still writes the same row.
    b = MailSettings(username="b@y.com")
    b.save()
    assert MailSettings.objects.count() == 1
    assert MailSettings.load().username == "b@y.com"


@pytest.mark.django_db
def test_is_configured_requires_login_password_and_sender():
    s = MailSettings.load()
    assert s.is_configured is False
    s.username = "shop@gmail.com"
    s.set_password("p")
    assert s.is_configured is True  # from_email falls back to username
    assert s.effective_from_email == "shop@gmail.com"
