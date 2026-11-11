import logging
from calendar import isleap
from dataclasses import dataclass
from datetime import date, datetime, timezone
from fractions import Fraction

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.timezone import get_current_timezone
from django.utils.translation import gettext_lazy as _
from rdrf.models.definition.models import ClinicalData, RDRFContext
from registry.patients.models import (
    ParentGuardian,
    Patient,
    PatientAddress,
    get_countries,
)
from report.filter_providers import ReportFilterProvider

logger = logging.getLogger(__name__)

DIAGNOSIS_CHOICES = (
    ("deletion", _("Deletion")),
    ("icd", _("Imprinting centre defect (ICD)")),
    ("mutation", _("Mutation")),
    ("upd", _("Uniparental disomy (UPD)")),
    ("mosaic", _("Mosaic")),
    ("clinical", _("Clinical")),
    ("unknown", _("Unknown")),
)

REGISTRATION_CODES = {
    "RegistrationDiagnosisDeletion": "deletion",
    "RegistrationDiagnosisICD": "icd",
    "RegistrationDiagnosisMutation": "mutation",
    "RegistrationDiagnosisUPD": "upd",
    "RegistrationDiagnosisMosaic": "mosaic",
    "RegistrationDiagnosisClinical": "clinical",
    "RegistrationDiagnosisUnknown": "unknown",
}

HISTORY_CODES = {
    "Deletion": "deletion",
    "ICD": "icd",
    "Mutation": "mutation",
    "UPD": "upd",
    "Mosaic": "mosaic",
    "Unsure": "unknown",
}


@dataclass(frozen=True)
class DiagnosisSource:
    context_group: str
    form: str
    section: str
    cde: str


ADMIN = DiagnosisSource(
    "AdministrationV2",
    "AdminOnlyExtraInfoV2",
    "RegistrationExtraInfo",
    "RegistrationDiagnosis",
)
HISTORY = DiagnosisSource(
    "PatientHistoryCFG",
    "HistoryOfDiagnosis",
    "ANGPatientResultsNEW",
    "ANGDNAMethylAbnormalResult2",
)
SIGNUP = DiagnosisSource(
    "Archive",
    "AdminOnlyExtraInfo",
    "RegistrationExtraInfo",
    "RegistrationDiagnosis",
)


class AngelmanDiagnosisParametersForm(forms.Form):
    diagnoses = forms.MultipleChoiceField(
        label=_("Diagnosis types"),
        choices=DIAGNOSIS_CHOICES,
        widget=forms.CheckboxSelectMultiple,
    )
    quality = forms.ChoiceField(
        label=_("Diagnosis quality"),
        choices=(
            ("verified", _("Verified (Admin)")),
            ("best_available", _("Best available")),
        ),
        initial="verified",
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class AngelmanDiagnosisFilter(ReportFilterProvider):
    configuration_version = 1
    label = _("Filter by Angelman Diagnosis")
    parameter_form_class = AngelmanDiagnosisParametersForm

    def get_matching_patient_ids(self, registry, patient_ids, parameters):
        if not patient_ids:
            return set()
        sources = (
            (ADMIN,)
            if parameters["quality"] == "verified"
            else (ADMIN, HISTORY, SIGNUP)
        )
        contexts = {
            context_id: (patient_id, group)
            for context_id, patient_id, group in RDRFContext.objects.filter(
                registry=registry,
                content_type=ContentType.objects.get_for_model(Patient),
                object_id__in=patient_ids,
                active=True,
                context_form_group__code__in=[
                    source.context_group for source in sources
                ],
            ).values_list("id", "object_id", "context_form_group__code")
        }
        records = ClinicalData.objects.collection(registry.code, "cdes").filter(
            django_model="Patient",
            django_id__in=patient_ids,
            context_id__in=list(contexts),
        )
        latest = {}
        for record in records:
            patient_id, group = contexts[record.context_id]
            if record.django_id != patient_id:
                raise ValidationError(
                    _("Diagnosis record does not match its patient context.")
                )
            for source in sources:
                if group != source.context_group or not any(
                    form.get("name") == source.form
                    for form in record.data.get("forms", [])
                ):
                    continue
                key = (patient_id, source)
                rank = (self._saved_at(record, source), record.pk)
                if key not in latest or rank > latest[key][0]:
                    latest[key] = (rank, record)

        selected = set(parameters["diagnoses"])
        matching = set()
        for patient_id in patient_ids:
            diagnosis = None
            for source in sources:
                candidate = latest.get((patient_id, source))
                if candidate is not None:
                    diagnosis = self._diagnosis(candidate[1], source)
                if diagnosis is not None:
                    break
            if diagnosis is None and parameters["quality"] == "best_available":
                diagnosis = "unknown"
            if diagnosis in selected:
                matching.add(patient_id)
        return matching

    @staticmethod
    def _saved_at(record, source):
        timestamp = record.data.get(f"{source.form}_timestamp")
        if timestamp:
            try:
                saved_at = datetime.fromisoformat(timestamp)
            except (TypeError, ValueError) as error:
                raise ValidationError(
                    _("Invalid saved timestamp for diagnosis form %(form)s."),
                    params={"form": source.form},
                ) from error
        else:
            # Legacy signup saves may not have a per-form timestamp.
            saved_at = record.last_updated_at or record.created_at
        if saved_at is None:
            raise ValidationError(
                _("Missing saved timestamp for diagnosis form %(form)s."),
                params={"form": source.form},
            )
        if saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        return saved_at

    @staticmethod
    def _diagnosis(record, source):
        if source == HISTORY:
            genetic_test = record.cde_val(
                source.form, source.section, "ANGGeneticTestV2"
            )
            if genetic_test not in (
                None,
                "",
                "YesNoUnsureYes",
                "YesNoUnsureNo",
                "YesNoUnsureUnsure",
            ):
                raise ValidationError(_("Invalid diagnosis genetic-test code."))
            if genetic_test != "YesNoUnsureYes":
                return None
        value = record.cde_val(source.form, source.section, source.cde)
        if value is None or value == "":
            return None
        codes = HISTORY_CODES if source == HISTORY else REGISTRATION_CODES
        if not isinstance(value, str) or value not in codes:
            raise ValidationError(
                _("Invalid diagnosis code in form %(form)s."),
                params={"form": source.form},
            )
        return codes[value]


class PatientAgeParametersForm(forms.Form):
    minimum_age = forms.DecimalField(
        label=_("Minimum age (years)"),
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "any"}
        ),
        help_text=_("Inclusive. Leave empty for no minimum age."),
    )
    maximum_age = forms.DecimalField(
        label=_("Maximum age (years)"),
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "step": "any"}
        ),
        help_text=_("Inclusive. Leave empty for no maximum age."),
    )

    def clean(self):
        cleaned = super().clean()
        minimum = cleaned.get("minimum_age")
        maximum = cleaned.get("maximum_age")
        if minimum is not None and maximum is not None and minimum > maximum:
            self.add_error(
                "maximum_age",
                _("Maximum age must be greater than or equal to minimum age."),
            )
        # Preserve decimal precision in the JSON provider configuration.
        return {
            key: str(value) if value is not None else None
            for key, value in cleaned.items()
        }


class PatientAgeFilter(ReportFilterProvider):
    configuration_version = 1
    label = _("Filter by Patient Age")
    parameter_form_class = PatientAgeParametersForm

    def get_matching_patient_ids(self, registry, patient_ids, parameters):
        minimum = parameters["minimum_age"]
        maximum = parameters["maximum_age"]
        if not patient_ids or (minimum is None and maximum is None):
            return set(patient_ids)
        minimum = Fraction(minimum) if minimum is not None else None
        maximum = Fraction(maximum) if maximum is not None else None
        today = datetime.now(tz=get_current_timezone()).date()
        matching = set()
        patients = Patient.objects.filter(
            pk__in=patient_ids, rdrf_registry=registry
        ).values_list("pk", "date_of_birth", "date_of_death")
        for patient_id, born, died in patients:
            if born is None:
                continue
            age = self._age_in_years(born, died or today)
            if (minimum is None or age >= minimum) and (
                maximum is None or age <= maximum
            ):
                matching.add(patient_id)
        return matching

    @staticmethod
    def _birthday(born: date, year: int) -> date:
        # Match Patient.age: leap-day birthdays fall on March 1 otherwise.
        if born.month == 2 and born.day == 29 and not isleap(year):
            return date(year, 3, 1)
        return born.replace(year=year)

    @classmethod
    def _age_in_years(cls, born: date, on: date) -> Fraction:
        if born > on:
            raise ValidationError(
                _("Date of birth is after the age comparison date.")
            )
        birthday_year = on.year
        birthday = cls._birthday(born, birthday_year)
        if birthday > on:
            birthday_year -= 1
            birthday = cls._birthday(born, birthday_year)
        next_birthday = cls._birthday(born, birthday_year + 1)
        return Fraction(birthday_year - born.year) + Fraction(
            (on - birthday).days, (next_birthday - birthday).days
        )


class PatientCountryParametersForm(forms.Form):
    countries = forms.MultipleChoiceField(
        label=_("Countries"),
        choices=get_countries,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 10}),
        help_text=_(
            "Select one or more countries. Uses patient Home country, then "
            "Postal country, then linked parent/guardian countries."
        ),
    )


class PatientCountryFilter(ReportFilterProvider):
    configuration_version = 1
    label = _("Filter by Country")
    parameter_form_class = PatientCountryParametersForm

    def get_matching_patient_ids(self, registry, patient_ids, parameters):
        if not patient_ids:
            return set()
        selected = set(parameters["countries"])
        valid_codes = {code for code, _name in get_countries()}
        addresses = {}
        for patient_id, address_type, country in (
            PatientAddress.objects.filter(
                patient_id__in=patient_ids,
                address_type__type__in=("Home", "Postal"),
            )
            .order_by("pk")
            .values_list("patient_id", "address_type__type", "country")
        ):
            if country and country.strip():
                addresses.setdefault((patient_id, address_type), country)

        matching = set()
        fallback_ids = set()
        invalid_count = 0
        for patient_id in patient_ids:
            country = addresses.get((patient_id, "Home")) or addresses.get(
                (patient_id, "Postal")
            )
            if country is None:
                fallback_ids.add(patient_id)
            else:
                code = self._country_code(country, valid_codes)
                if code is None:
                    invalid_count += 1
                elif code in selected:
                    matching.add(patient_id)

        if fallback_ids:
            for patient_id, country in ParentGuardian.objects.filter(
                patient__pk__in=fallback_ids
            ).values_list("patient__pk", "country"):
                if not country or not country.strip():
                    continue
                code = self._country_code(country, valid_codes)
                if code is None:
                    invalid_count += 1
                elif code in selected:
                    matching.add(patient_id)
        if invalid_count:
            logger.warning(
                "Country report filter skipped %d invalid country record(s).",
                invalid_count,
            )
        return matching

    @staticmethod
    def _country_code(country, valid_codes):
        code = country.strip().upper()
        if code not in valid_codes:
            return None
        return code
