import pytest
from django.urls import NoReverseMatch, reverse
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from python_podcast.users.tests.factories import UserFactory


def test_token_endpoint_has_no_named_url():
    with pytest.raises(NoReverseMatch):
        reverse("api-token-auth")


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "post"])
def test_token_endpoint_returns_404(client, method):
    response = getattr(client, method)("/api/api-token-auth/", {"username": "unused", "password": "unused"})

    assert response.status_code == 404


@pytest.mark.django_db
def test_existing_token_header_still_authenticates_cast_api():
    staff = UserFactory(is_staff=True)
    credential = Token.objects.create(user=staff)
    url = reverse("cast:api:comment-training-data")

    anonymous = APIClient().get(url)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {credential.key}")
    authenticated = client.get(url)

    assert anonymous.status_code in (401, 403)
    assert authenticated.status_code == 200
