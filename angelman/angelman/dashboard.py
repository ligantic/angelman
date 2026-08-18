from itertools import zip_longest

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


def _value(dashboard, section_code, cde_code, multisection=False):
    try:
        context_group = ContextFormGroup.objects.get(
            registry=dashboard.registry, code=CONTEXT_GROUP_CODE
        )
        context = dashboard._get_patient_context(context_group)
        if not context:
            return [] if multisection else None
        form = RegistryForm.objects.get(
            registry=dashboard.registry, name=FORM_NAME
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
        "summary": summary or "No issues reported",
        "status": "Monitoring required" if summary else "No issues",
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
        "label": "Brain/nervous system",
        "summary": summary or "No issues reported",
        "status": "Monitoring required" if summary else "No issues",
        "status_css": "monitoring" if summary else "no-issues",
    }


def clinical_snapshot(dashboard, widget):
    medications = _medications(dashboard)
    brain_conditions = _value(dashboard, "NewIllness", "ANGBrainList") or []
    if not isinstance(brain_conditions, list):
        brain_conditions = [brain_conditions]
    has_seizures = "Seizures" in brain_conditions
    seizure_status = None
    seizure_management = None
    if has_seizures:
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
            "label": "Current medications",
            "summary": (
                "; ".join(medications)
                if medications
                else "No current medications reported"
            ),
            "status": "Monitoring required" if medications else "No issues",
            "status_css": "monitoring" if medications else "no-issues",
        },
        {
            "label": "Seizure status",
            "summary": seizure_summary or "No seizure status reported",
            "status": "Monitoring required" if seizure_monitoring else "Stable",
            "status_css": "monitoring" if seizure_monitoring else "stable",
        },
        _condition_row(dashboard, "Growth/feeding", *SYSTEM_CONDITIONS["Growth/feeding"]),
        _brain_row(dashboard),
        _condition_row(
            dashboard,
            "Behaviour/psychiatric",
            *SYSTEM_CONDITIONS["Behaviour/psychiatric"],
        ),
        _condition_row(
            dashboard,
            "Muscles/skeletal",
            *SYSTEM_CONDITIONS["Muscles/skeletal"],
        ),
        _condition_row(
            dashboard,
            "Lungs/breathing",
            *SYSTEM_CONDITIONS["Lungs/breathing"],
        ),
        _condition_row(
            dashboard,
            "Digestive system",
            *SYSTEM_CONDITIONS["Digestive system"],
        ),
    ]
    return {
        "placement": "secondary",
        "template": "angelman/dashboard/widgets/clinical_snapshot.html",
        "snapshot": snapshot,
    }


def patient_information(dashboard, widget):
    patient = dashboard.patient
    return {
        "placement": "primary",
        "template": "angelman/dashboard/widgets/patient_information.html",
        "patient": {
            "name": patient.display_name,
            "sex": patient.get_sex_display(),
            "age": patient.age,
            "date_of_birth": patient.date_of_birth,
            "last_updated": patient.last_updated_overall_at,
        },
    }
