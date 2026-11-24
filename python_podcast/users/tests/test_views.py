import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.template import Engine
from django.test import RequestFactory
from django.urls import reverse

from python_podcast.users.tests.factories import UserFactory
from python_podcast.users.views import UserRedirectView, user_detail_view, user_list_view, user_update_view

pytestmark = pytest.mark.django_db


class TestUserUpdateView:
    def test_updates_account_after_username_changes(self, user, request_factory):
        request = request_factory.post(reverse("users:update"), {"name": "Updated Name"})
        request.user = user
        get_user_model().objects.filter(pk=user.pk).update(username="renamed-member")

        response = user_update_view(request)

        user.refresh_from_db()
        assert user.name == "Updated Name"
        assert response.status_code == 302
        assert response.url == reverse("users:detail", kwargs={"username": "renamed-member"})

    def test_account_removed_before_lookup_is_404(self, user, request_factory):
        request = request_factory.get(reverse("users:update"))
        request.user = user
        get_user_model().objects.filter(pk=user.pk).delete()

        with pytest.raises(Http404):
            user_update_view(request)


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

    def test_staff_directory_paginates_in_username_order(self, request_factory, staff):
        user_model = get_user_model()
        usernames = [f"member-{index:02d}" for index in range(51)]
        user_model.objects.bulk_create(user_model(username=username) for username in reversed(usernames))

        first = user_list_view(self._get(request_factory, "/users/", staff))
        second = user_list_view(self._get(request_factory, "/users/?page=2", staff))

        assert [user.username for user in first.context_data["user_list"]] == usernames[:50]
        assert [user.username for user in second.context_data["user_list"]] == [usernames[50], staff.username]

        base_template = Engine.get_default().from_string("{% block content %}{% endblock %}")
        first.context_data["cast_base_template"] = base_template
        second.context_data["cast_base_template"] = base_template
        assert 'href="?page=2"' in first.rendered_content
        assert 'href="?page=1"' in second.rendered_content

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
