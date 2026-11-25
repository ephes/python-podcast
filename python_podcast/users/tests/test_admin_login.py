import pytest
from django.test import Client
from django.urls import reverse

from python_podcast.users.tests.factories import UserFactory


def make_user(**kwargs):
    # The project factory sets a random password; pin a known one.
    user = UserFactory(**kwargs)
    user.set_password("password")
    user.save()
    return user


def post_login(url, username, password, client):
    return client.post(url, {"username": username, "password": password})


@pytest.mark.django_db
def test_staff_login_to_django_admin_works():
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()

    # The admin login form posts "next" as a hidden field.
    response = post_login(
        f"{reverse('admin:login')}?next={reverse('admin:index')}", user.username, "password", client=client
    )

    assert response.status_code == 302
    assert response["Location"] == reverse("admin:index")
    # The dashboards need migrated Wagtail data, so check the session instead.
    assert client.session["_auth_user_id"] == str(user.pk)


@pytest.mark.django_db
def test_staff_login_to_wagtail_admin_works():
    user = make_user(is_staff=True, is_superuser=True)
    client = Client()

    response = post_login(reverse("wagtailadmin_login"), user.username, "password", client=client)

    assert response.status_code == 302
    assert response["Location"] == reverse("wagtailadmin_home")
    # The dashboards need migrated Wagtail data, so check the session instead.
    assert client.session["_auth_user_id"] == str(user.pk)
