import pytest
from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm
from django.utils.translation import override

from python_podcast.users.forms import UserCreationForm
from python_podcast.users.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestUserCreationForm:

    def test_duplicate_message_is_local_to_the_app_form(self):
        assert "duplicate_username" not in DjangoUserCreationForm.error_messages
        assert UserCreationForm.error_messages is not DjangoUserCreationForm.error_messages

    @pytest.mark.parametrize("username", ["existing-member", "EXISTING-MEMBER"])
    def test_duplicate_username_uses_the_localized_message(self, username):
        UserFactory(username="existing-member")
        form = UserCreationForm(
            {"username": username, "password1": "Synth3tic-test-password!", "password2": "Synth3tic-test-password!"}
        )

        with override("en"):
            assert not form.is_valid()
            assert form.errors["username"] == ["This username has already been taken."]
            assert form.has_error("username", "unique")

    def test_clean_username(self):
        # A user with proto_user params does not exist yet.
        proto_user = UserFactory.build()

        form = UserCreationForm(
            {
                "username": proto_user.username,
                "password1": proto_user._password,
                "password2": proto_user._password,
            }
        )

        assert form.is_valid()
        assert form.clean_username() == proto_user.username

        # Creating a user.
        form.save()

        # The user with proto_user params already exists,
        # hence cannot be created.
        form = UserCreationForm(
            {
                "username": proto_user.username,
                "password1": proto_user._password,
                "password2": proto_user._password,
            }
        )

        assert not form.is_valid()
        assert len(form.errors) == 1
        assert "username" in form.errors
