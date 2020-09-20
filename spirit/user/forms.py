# -*- coding: utf-8 -*-

import os

from django import forms
from django.utils.translation import ugettext_lazy as _
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.template import defaultfilters

from spirit.core.conf import settings
from spirit.core.utils.timezone import timezones
from .models import UserProfile

User = get_user_model()
TIMEZONE_CHOICES = timezones()


class CleanEmailMixin(object):

    def clean_email(self):
        email = self.cleaned_data["email"]

        if settings.ST_CASE_INSENSITIVE_EMAILS:
            email = email.lower()

        if not settings.ST_UNIQUE_EMAILS:
            return email

        is_taken = (
            User.objects
            .filter(email=email)
            .exists())

        if is_taken:
            raise forms.ValidationError(_("The email is taken."))

        return email

    def get_email(self):
        return self.cleaned_data["email"]


class EmailCheckForm(CleanEmailMixin, forms.Form):

    email = forms.CharField(label=_("Email"), widget=forms.EmailInput, max_length=254)


class EmailChangeForm(CleanEmailMixin, forms.Form):

    email = forms.CharField(label=_("Email"), widget=forms.EmailInput, max_length=254)
    password = forms.CharField(label=_("Password"), widget=forms.PasswordInput)

    def __init__(self, user=None, *args, **kwargs):
        self.user = user
        super(EmailChangeForm, self).__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]

        if not self.user.check_password(password):
            raise forms.ValidationError(_("The provided password is incorrect."))

        return password


class UserForm(forms.ModelForm):

    class Meta:
        model = User
        fields = ("first_name", "last_name")


class ImageWidget(forms.ClearableFileInput):
    template_name = 'spirit/user/_image_widget.html'


class UserProfileForm(forms.ModelForm):

    timezone = forms.ChoiceField(label=_("Time zone"), choices=TIMEZONE_CHOICES)

    class Meta:
        model = UserProfile
        fields = ("avatar", "location", "timezone")
        widgets = {'avatar': ImageWidget}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.localtime(timezone.now())
        self.fields['timezone'].help_text = _('Current time is: %(date)s %(time)s') % {
            'date': defaultfilters.date(now),
            'time': defaultfilters.time(now)}
        self.fields['avatar'].widget.clear_checkbox_label = _('Remove avatar')
        self.fields['avatar'].widget.attrs['accept'] = (
            ", ".join(
                '.%s' % ext
                for ext in sorted(settings.ST_ALLOWED_AVATAR_FORMAT)))

    def clean_avatar(self):
        file = self.cleaned_data['avatar']
        # can be bool (clear) or not an image (empty)
        if not hasattr(file, 'image'):
            return file

        ext = os.path.splitext(file.name)[1].lstrip('.').lower()
        if (ext not in settings.ST_ALLOWED_AVATAR_FORMAT or
                file.image.format.lower() not in settings.ST_ALLOWED_AVATAR_FORMAT):
            raise forms.ValidationError(
                _("Unsupported file format. Supported formats are %s.") %
                ", ".join(settings.ST_ALLOWED_AVATAR_FORMAT))

        return file

    def clean(self):
        cleaned_data = super().clean()
        if self.instance.pk is not None:
            if self.instance.avatar != cleaned_data['avatar']:
                # XXX maybe add setting.AVATAR_STORAGE
                #     to support overwrite and prevent race conditions
                self.instance.avatar.delete()
        return cleaned_data
