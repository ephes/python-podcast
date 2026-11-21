from django.contrib.auth import forms, get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()
DUPLICATE_USERNAME = _("This username has already been taken.")


class UserChangeForm(forms.UserChangeForm):

    class Meta(forms.UserChangeForm.Meta):
        model = User


class UserCreationForm(forms.UserCreationForm):

    error_messages = {**forms.UserCreationForm.error_messages, "duplicate_username": DUPLICATE_USERNAME}

    class Meta(forms.UserCreationForm.Meta):
        model = User
        error_messages = {"username": {"unique": DUPLICATE_USERNAME}}
