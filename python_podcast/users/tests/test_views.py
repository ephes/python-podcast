import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory
from django.urls import reverse

from python_podcast.users.tests.factories import UserFactory
from python_podcast.users.views import UserRedirectView, UserUpdateView, user_detail_view, user_list_view

pytestmark = pytest.mark.django_db


class TestUserUpdateView:
    """
    TODO:
        extracting view initialization code as class-scoped fixture
        would be great if only pytest-django supported non-function-scoped
        fixture db access -- this is a work-in-progress for now:
        https://github.com/pytest-dev/pytest-django/pull/258
    """

    def test_get_success_url(self, user: settings.AUTH_USER_MODEL, request_factory: RequestFactory):
        view = UserUpdateView()
        request = request_factory.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_success_url() == f"/users/{user.username}/"

    def test_get_object(self, user: settings.AUTH_USER_MODEL, request_factory: RequestFactory):
        view = UserUpdateView()
        request = request_factory.get("/fake-url/")
        request.user = user

        view.request = request

        assert view.get_object() == user


class TestUserRedirectView:

    def test_get_redirect_url(self, user: settings.AUTH_USER_MODEL, request_factory: RequestFactory):
        view = UserRedirectView()
        request = request_factory.get("/fake-url")
        request.user = user

        view.request = request

        assert view.get_redirect_url() == f"/users/{user.username}/"


class TestUserDirectoryAccess:
    """Logged-in users must not be able to enumerate other accounts.

    The views are called directly so the templates (which need a site theme
    and Vite assets) are not rendered; the context shows what would be.
    """

    @pytest.fixture
    def other(self):
        return UserFactory(username="other-member", name="Other Member")

    @pytest.fixture
    def staff(self):
        return UserFactory(username="staff-member", is_staff=True)

    @staticmethod
    def _get(request_factory, path, user):
        request = request_factory.get(path)
        request.user = user
        return request

    def test_list_redirects_anonymous_to_login(self, request_factory):
        response = user_list_view(self._get(request_factory, "/users/", AnonymousUser()))
        assert response.status_code == 302
        assert response.url.startswith(reverse("account_login"))

    def test_list_forbidden_for_non_staff(self, request_factory, user, other):
        with pytest.raises(PermissionDenied):
            user_list_view(self._get(request_factory, "/users/", user))

    def test_list_allowed_for_staff(self, request_factory, staff, other):
        response = user_list_view(self._get(request_factory, "/users/", staff))
        assert response.status_code == 200
        assert list(response.context_data["object_list"]) == [other, staff]

    def test_detail_redirects_anonymous_to_login(self, request_factory, other):
        path = f"/users/{other.username}/"
        response = user_detail_view(self._get(request_factory, path, AnonymousUser()), username=other.username)
        assert response.status_code == 302
        assert response.url.startswith(reverse("account_login"))

    def test_detail_shows_own_profile(self, request_factory, user):
        path = f"/users/{user.username}/"
        response = user_detail_view(self._get(request_factory, path, user), username=user.username)
        assert response.status_code == 200
        assert response.context_data["object"] == user

    def test_detail_of_other_user_is_404_for_non_staff(self, request_factory, user, other):
        path = f"/users/{other.username}/"
        with pytest.raises(Http404):
            user_detail_view(self._get(request_factory, path, user), username=other.username)

    def test_detail_of_missing_user_is_404_for_non_staff(self, request_factory, user):
        with pytest.raises(Http404):
            user_detail_view(self._get(request_factory, "/users/missing/", user), username="missing")

    def test_detail_of_other_user_allowed_for_staff(self, request_factory, staff, other):
        path = f"/users/{other.username}/"
        response = user_detail_view(self._get(request_factory, path, staff), username=other.username)
        assert response.status_code == 200
        assert response.context_data["object"] == other
