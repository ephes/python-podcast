"""Rate-limit the Wagtail admin password reset like allauth's.

allauth limits ``/accounts/password/reset/`` with its ``reset_password`` rate
(default ``20/m/ip,5/m/key``, the key being the email address). Wagtail's own
``<WAGTAILADMIN_BASE_URL>password_reset/`` had no limit, and every accepted
request sends an email. This view charges the same ``reset_password`` budget,
so both forms together stay within allauth's limit for an address and a client.
"""

from allauth.core import ratelimit
from wagtail.admin.views import account as wagtailadmin_account


class ThrottledWagtailPasswordResetView(wagtailadmin_account.PasswordResetView):
    def form_valid(self, form):
        # Same action and key as allauth's PasswordResetView.form_valid.
        too_many = ratelimit.consume_or_429(
            self.request,
            action="reset_password",
            key=form.cleaned_data["email"].lower(),
        )
        if too_many:
            return too_many
        return super().form_valid(form)
