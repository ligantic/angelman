from operator import attrgetter

import pycountry
from django.forms import BooleanField, CharField, ChoiceField, DateField
from django.forms.widgets import HiddenInput, RadioSelect, Select
from django.utils.translation import gettext_lazy as _
from rdrf.forms.registration_forms import RegistrationFormCaseInsensitiveCheck
from rdrf.helpers.utils import get_all_language_codes
from rdrf.models.definition.models import CommonDataElement
from registry.patients.models import Patient

from angelman.registry.groups.registration.angelman_registration import (
    DIAGNOSIS_CDE,
)


def _tuple(code, name):
    return code, _(name)


def _countries():
    countries = sorted(pycountry.countries, key=attrgetter("name"))
    result = [_tuple("", "Country")]
    return result + [_tuple(c.alpha_2, c.name) for c in countries]


def _get_diagnosis():
    cde_code = DIAGNOSIS_CDE["cde_code"]
    cde = CommonDataElement.objects.filter(code=cde_code).first()
    options = cde.pv_group.options if cde else []
    initial = {"code": "", "text": "Diagnosis"}
    options = [initial] + options
    return [(o["code"], _(o["text"])) for o in options]


def _preferred_languages():
    languages = get_all_language_codes()
    return (
        [_tuple(lang.code, lang.name) for lang in languages]
        if languages
        else [_tuple("en", "English")]
    )


def _field_widget_class(field):
    if isinstance(field, BooleanField) or isinstance(field.widget, RadioSelect):
        return None
    elif isinstance(field.widget, Select):
        return "form-select"
    else:
        return "form-control"


class ANGPatientRegistrationForm(RegistrationFormCaseInsensitiveCheck):
    labels = {
        "username": _("Email"),
        "password1": _("Password"),
        "password2": _("Repeat Password"),
        "first_name": _("Given Names"),
        "surname": _("Surname"),
        "date_of_birth": _("Date of Birth"),
        "gender": _("Gender"),
        "diagnosis": _("Diagnosis"),
        "country": _("Country"),
        "address": _("Street"),
        "suburb": _("Suburb / Town"),
        "state": _("State / County / Province / Region"),
        "postcode": _("Zip / Postal Code"),
        "phone_number": _("Phone Number"),
        "preferred_languages": _("Preferred Language"),
    }

    placeholders = {"date_of_birth": _("YYYY-MM-DD")}

    country_choices = _countries()

    language_choices = _preferred_languages()

    password_fields = ["password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields:
            field_widget_class = _field_widget_class(self.fields[field])
            if field_widget_class is not None:
                self.fields[field].widget.attrs["class"] = field_widget_class

            if field in self.labels.keys():
                self.fields[field].label = self.labels.get(field, "")

            if field in self.placeholders.keys():
                self.fields[field].widget.attrs["placeholder"] = (
                    self.placeholders.get(field, "")
                )
            if field in self.password_fields:
                self.fields[field].widget.render_value = True

    preferred_languages = ChoiceField(
        required=False, choices=language_choices, widget=HiddenInput
    )
    first_name = CharField(required=True, max_length=30)
    surname = CharField(required=True, max_length=30)
    date_of_birth = DateField(required=True)
    gender = ChoiceField(
        choices=Patient.SEX_CHOICES, widget=RadioSelect, required=True
    )
    diagnosis = ChoiceField(
        required=True, widget=Select, choices=_get_diagnosis, initial=""
    )
    address = CharField(required=True, max_length=100)
    suburb = CharField(required=True, max_length=30)
    country = ChoiceField(
        required=True, widget=Select, choices=country_choices, initial=""
    )
    state = CharField(required=False, widget=Select)
    postcode = CharField(required=True, max_length=30)
    phone_number = CharField(required=True, max_length=30)
    registry_code = CharField(required=True)


class ANGRegistrationForm(ANGPatientRegistrationForm):
    ANGPatientRegistrationForm.labels.update(
        {
            "parent_guardian_first_name": _("Given Names"),
            "parent_guardian_last_name": _("Surname"),
            "parent_guardian_date_of_birth": _("Date of Birth"),
            "parent_guardian_gender": _("Gender"),
            "parent_guardian_address": _("Street"),
            "parent_guardian_suburb": _("Suburb / Town"),
            "parent_guardian_state": _("State / County / Province / Region"),
            "parent_guardian_country": _("Country"),
            "parent_guardian_postcode": _("Zip / Postal Code"),
            "parent_guardian_phone": _("Phone Number"),
        }
    )

    ANGPatientRegistrationForm.placeholders.update(
        {"parent_guardian_date_of_birth": _("YYYY-MM-DD")}
    )

    tooltip_info = {
        "parent_guardian_address": _(
            "Please enter an address through which we can contact you"
        ),
        "parent_guardian_phone": _("""Please enter a phone number through which we can contact you,
                                      including the country code (e.g. +61 for Australia)"""),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    parent_guardian_first_name = CharField(required=True)
    parent_guardian_last_name = CharField(required=True)
    parent_guardian_date_of_birth = DateField(required=True)
    parent_guardian_gender = ChoiceField(
        choices=Patient.SEX_CHOICES, widget=RadioSelect, required=True
    )
    parent_guardian_address = CharField(required=True, max_length=100)
    parent_guardian_suburb = CharField(required=True, max_length=30)
    parent_guardian_country = ChoiceField(
        required=True,
        widget=Select,
        choices=ANGPatientRegistrationForm.country_choices,
        initial="-1",
    )
    parent_guardian_state = CharField(
        required=False, widget=Select, max_length=30
    )
    parent_guardian_postcode = CharField(required=True, max_length=30)
    parent_guardian_phone = CharField(required=True, max_length=30)
    same_address = BooleanField(required=False)

    def _clean_fields(self):
        base_required_fields = [
            "address",
            "suburb",
            "country",
            "state",
            "postcode",
            "phone_number",
        ]
        if self.data.get("same_address", False):
            for f in base_required_fields:
                self.fields[f].required = False
        super()._clean_fields()
