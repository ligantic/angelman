from itertools import zip_longest

from django.urls import reverse
from django.utils.translation import gettext as _
from rdrf.models.definition.models import (
    CommonDataElement,
    ContextFormGroup,
    RegistryForm,
)


FORM_NAME = "Clinical"
CONTEXT_GROUP_CODE = "Clinical"
ACTIVE_STATUSES = {"Current", "Episodic"}

SYSTEM_CONDITIONS = {
    "Growth/feeding": (
        "ANGGrowthList",
        (
            ("OverweightObese", "ANGOverweightStatus"),
            ("FTT", "ANGFTTStatus"),
            ("Hyperphagia", "ANGHyperphagiaStatus"),
            ("TubeFeeding", "ANGTubeFeedStatus"),
            ("FoodRefusal", "ANGFoodRefusalStatus"),
            ("DifficultSwallow", "ANGSwallowingStatus"),
        ),
    ),
    "Behaviour/psychiatric": (
        "ANGBehPsyList",
        (
            ("Anxiety", "ANGAnxietyStatus"),
            ("Aggression", "ANGAgressionStatus"),
            ("SelfInjury", "ANGSelfInjuryStatus"),
            ("Hyperactivity", "ANGHyperactivityStatus"),
        ),
    ),
    "Muscles/skeletal": (
        "ANGMusclesList",
        (
            ("Hypotonia", "ANGHypotoniaStatus"),
            ("Hypertonia", "ANGHypertoniaStatus"),
            ("TightHeel", "ANGTightHeelCordsStatus"),
            ("Scoliosis", "ANGScoliosisStatus"),
            ("ToeWalking", "ANGToeWalkingStatusV2"),
        ),
    ),
    "Lungs/breathing": (
        "ANGLungsList",
        (
            ("Apnea", "ANGApneaStatus"),
            ("Pneumonia", "ANGPneumoniaStatus"),
            ("Aspiration", "ANGAspirationsStatus"),
        ),
    ),
    "Digestive system": (
        "ANGDigestiveList",
        (
            ("Gastroesophageal", "ANGGastroStatus"),
            ("Constipation", "ANGConstipationStatus"),
            ("VomitingFeeds", "ANGVomitFeedsStatus"),
            ("Gagging", "ANGGaggingStatusV2"),
            ("CyclicVomiting", "ANGCyclicVomitStatus"),
        ),
    ),
}


def _display(cde_code, value):
    if value in (None, "", []):
        return None
    cde = CommonDataElement.objects.get(code=cde_code)
    display_value = cde.display_value(value)
    if isinstance(display_value, list):
        return ", ".join(str(item) for item in display_value)
    return display_value


def _form_value(
    dashboard,
    context_group_code,
    form_name,
    section_code,
    cde_code,
    multisection=False,
):
    try:
        context_group = ContextFormGroup.objects.get(
            registry=dashboard.registry, code=context_group_code
        )
        context = dashboard._get_patient_context(context_group)
        if not context:
            return [] if multisection else None
        form = RegistryForm.objects.get(
            registry=dashboard.registry, name=form_name
        )
        return dashboard.patient.get_form_value(
            dashboard.registry.code,
            form.name,
            section_code,
            cde_code,
            multisection=multisection,
            context_id=context.id,
        )
    except (
        CommonDataElement.DoesNotExist,
        ContextFormGroup.DoesNotExist,
        KeyError,
        RegistryForm.DoesNotExist,
    ):
        return [] if multisection else None


def _value(dashboard, section_code, cde_code, multisection=False):
    return _form_value(
        dashboard,
        CONTEXT_GROUP_CODE,
        FORM_NAME,
        section_code,
        cde_code,
        multisection,
    )


def _medications(dashboard):
    medication_codes = (
        "curmedscreen2",
        "ANGMedIntWhatV2",
        "ANGMedIntNameOTH",
        "ANGMedIntReason2",
        "ANGMedOftenSimple",
    )
    values = []
    for cde_code in medication_codes:
        field_values = _value(
            dashboard, "NewMedication", cde_code, multisection=True
        )
        values.append(
            field_values if isinstance(field_values, list) else [field_values]
        )
    entries = []
    for current, medication, other_name, reason, frequency in zip_longest(
        *values, fillvalue=None
    ):
        if _display("curmedscreen2", current) != "Yes":
            continue
        medication = _display("ANGMedIntWhatV2", medication)
        if not medication:
            continue
        if medication == "Other" and other_name:
            medication = str(other_name)
        details = []
        for cde_code, value in (
            ("ANGMedIntReason2", reason),
            ("ANGMedOftenSimple", frequency),
        ):
            detail = _display(cde_code, value)
            if detail:
                details.append(
                    {
                        "Clinical trial administration": "Clinical trial",
                        "Complimentary (e.g. vitamins and probiotics)": "Complimentary",
                    }.get(detail, detail)
                )
        entries.append(" - ".join([medication, *details]))
    return entries


def _condition_row(dashboard, label, list_cde_code, conditions):
    values = _value(dashboard, "NewIllness", list_cde_code) or []
    if not isinstance(values, list):
        values = [values]
    active_conditions = []
    for condition_code, status_cde_code in conditions:
        if condition_code not in values:
            continue
        status = _display(
            status_cde_code,
            _value(dashboard, "NewIllness", status_cde_code),
        )
        if status in ACTIVE_STATUSES:
            condition = _display(list_cde_code, condition_code)
            active_conditions.append(f"{condition} ({status})")
    summary = ", ".join(active_conditions)
    return {
        "label": label,
        "summary": summary or _("No issues reported"),
        "status": _("Monitoring required") if summary else _("No issues"),
        "status_css": "monitoring" if summary else "no-issues",
    }


def _brain_row(dashboard):
    values = _value(dashboard, "NewIllness", "ANGBrainList") or []
    if not isinstance(values, list):
        values = [values]
    brain_conditions = [
        value
        for value in values
        if value.casefold() not in {"seizures", "seizures/ epilepsy"}
    ]
    nem_status = _display(
        "ANGNEMStatus", _value(dashboard, "NewIllness", "ANGNEMStatus")
    )
    if nem_status not in ACTIVE_STATUSES:
        brain_conditions = [
            value
            for value in brain_conditions
            if "myoclonus" not in value.casefold()
        ]
    elif nem_status:
        brain_conditions = [
            f"{value} ({nem_status})" if "myoclonus" in value.casefold() else value
            for value in brain_conditions
        ]

    summary = _display("ANGBrainList", brain_conditions) if brain_conditions else None
    return {
        "label": _("Brain/nervous system"),
        "summary": summary or _("No issues reported"),
        "status": _("Monitoring required") if summary else _("No issues"),
        "status_css": "monitoring" if summary else "no-issues",
    }


def clinical_snapshot(dashboard, widget):
    medications = _medications(dashboard)
    seizure_status = _display(
        "SeizureStatus2", _value(dashboard, "NewEpilepsy", "SeizureStatus2")
    )
    seizure_management = _display(
        "ANGSEIZUREManaged",
        _value(dashboard, "NewEpilepsy", "ANGSEIZUREManaged"),
    )
    seizure_summary = "; ".join(
        value for value in (seizure_status, seizure_management) if value
    )
    seizure_monitoring = seizure_status not in (None, "Controlled")
    snapshot = [
        {
            "label": _("Current medications"),
            "summary": (
                "; ".join(medications)
                if medications
                else _("No current medications reported")
            ),
            "status": _("Monitoring required") if medications else _("No issues"),
            "status_css": "monitoring" if medications else "no-issues",
        },
        {
            "label": _("Seizure status"),
            "summary": seizure_summary or _("No seizure status reported"),
            "status": _("Monitoring required") if seizure_monitoring else _("Stable"),
            "status_css": "monitoring" if seizure_monitoring else "stable",
        },
        _condition_row(dashboard, _("Growth/feeding"), *SYSTEM_CONDITIONS["Growth/feeding"]),
        _brain_row(dashboard),
        _condition_row(
            dashboard,
            _("Behaviour/psychiatric"),
            *SYSTEM_CONDITIONS["Behaviour/psychiatric"],
        ),
        _condition_row(
            dashboard,
            _("Muscles/skeletal"),
            *SYSTEM_CONDITIONS["Muscles/skeletal"],
        ),
        _condition_row(
            dashboard,
            _("Lungs/breathing"),
            *SYSTEM_CONDITIONS["Lungs/breathing"],
        ),
        _condition_row(
            dashboard,
            _("Digestive system"),
            *SYSTEM_CONDITIONS["Digestive system"],
        ),
    ]
    return {
        "placement": "secondary",
        "template": "angelman/dashboard/widgets/clinical_snapshot.html",
        "snapshot": snapshot,
    }


def _patient_flags(dashboard):
    flags = []
    seizure_status = _display(
        "SeizureStatus2", _value(dashboard, "NewEpilepsy", "SeizureStatus2")
    )
    if seizure_status == "Uncontrolled":
        flags.append(_("Uncontrolled seizures"))

    medication_current = _value(
        dashboard, "NewMedication", "curmedscreen2", multisection=True
    )
    medication_frequency = _value(
        dashboard, "NewMedication", "ANGMedOftenSimple", multisection=True
    )
    if not isinstance(medication_current, list):
        medication_current = [medication_current]
    if not isinstance(medication_frequency, list):
        medication_frequency = [medication_frequency]
    for current, frequency in zip_longest(
        medication_current, medication_frequency, fillvalue=None
    ):
        if (
            _display("curmedscreen2", current) == "Yes"
            and _display("ANGMedOftenSimple", frequency)
            == "Taken on a regular basis"
        ):
            flags.append(_("Daily medication"))
            break

    mobility_support = _form_value(
        dashboard,
        "BehDev",
        "Development",
        "ANGBEHDEVMOTORFUNCTIONV2",
        "ANGBEHDEVMOBILITYSUPPORT",
        multisection=True,
    )
    if not isinstance(mobility_support, list):
        mobility_support = [mobility_support]
    if "WheelchairAll" in mobility_support:
        flags.append(_("Wheelchair required"))

    return flags


def patient_information(dashboard, widget):
    patient = dashboard.patient
    home_address = patient.home_address
    working_group = patient.working_groups.first()
    address = ", ".join(
        str(value)
        for value in (
            getattr(home_address, "address", None),
            getattr(home_address, "suburb", None),
            getattr(home_address, "state", None),
            getattr(home_address, "postcode", None),
            getattr(home_address, "country", None),
        )
        if value
    )
    diagnostic_information_url = None
    try:
        context_form_group = ContextFormGroup.objects.get(
            registry=dashboard.registry, code="PatientHistoryCFG"
        )
        registry_form = RegistryForm.objects.get(
            registry=dashboard.registry, name="HistoryOfDiagnosis"
        )
        diagnostic_information_url = dashboard._get_form_link(
            context_form_group, registry_form
        )
    except (ContextFormGroup.DoesNotExist, RegistryForm.DoesNotExist):
        pass

    return {
        "placement": "primary",
        "template": "angelman/dashboard/widgets/patient_information.html",
        "patient": {
            "name": patient.display_name,
            "sex": patient.get_sex_display(),
            "age": patient.age,
            "working_group": (
                working_group.display_name if working_group else None
            ),
            "flags": _patient_flags(dashboard),
            "last_updated": patient.last_updated_overall_at,
            "address": address,
            "phone": patient.home_phone or patient.mobile_phone,
            "demographics_url": reverse(
                "patient_edit",
                kwargs={
                    "registry_code": dashboard.registry.code,
                    "patient_id": patient.id,
                },
            ),
            "diagnostic_information_url": diagnostic_information_url,
        },
    }
