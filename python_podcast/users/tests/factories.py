from collections import OrderedDict
from collections.abc import Sequence
from typing import Any

from django.contrib.auth import get_user_model
from factory import post_generation
from factory.django import DjangoModelFactory
from faker import Faker

locales = OrderedDict(
    [
        ("en-US", 1),
        ("de_DE", 2),
    ]
)
fake = Faker(locales)


class UserFactory(DjangoModelFactory):

    username = fake.user_name()
    email = fake.email()
    name = fake.name()

    @post_generation
    def password(self, create: bool, extracted: Sequence[Any], **kwargs):
        password = fake.password()
        self.set_password(password)

    class Meta:
        model = get_user_model()
        django_get_or_create = ["username"]
