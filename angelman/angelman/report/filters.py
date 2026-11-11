from dataclasses import dataclass
from datetime import datetime, timezone

from django import forms
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from rdrf.models.definition.models import ClinicalData, RDRFContext
from registry.patients.models import Patient
from report.filter_providers import ReportFilterProvider

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
