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
ACTIVE_STATUSES = {"Current", "Episodic", "Intermittently experiencing/ episodic"}
RESOLVED_STATUS = "Resolved"

CLINICAL_SNAPSHOT_DESCRIPTIONS = {
    "Growth/feeding": _("Growth, weight, appetite or feeding concerns."),
    "Brain/nervous system": _(
        "Seizures, myoclonus or other neurological concerns."
    ),
    "Behaviour/psychiatric": _(
        "Behaviour, anxiety or other emotional and mental health concerns."
    ),
    "Muscles/skeletal": _(
        "Muscle, joint, bone, posture or mobility concerns."
    ),
    "Lungs/breathing": _(
        "Breathing, aspiration or recurrent respiratory concerns."
    ),
    "Digestive system": _(
        "Reflux, constipation, vomiting or other digestive concerns."
    ),
}

CRITICAL_GROWTH_CONDITIONS = {
    "FTT",
    "TubeFeeding",
    "FoodRefusal",
    "DifficultSwallow",
}

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


def _clinical_section_edit_url(dashboard, section_code):
    try:
        context_group = ContextFormGroup.objects.get(
            registry=dashboard.registry, code=CONTEXT_GROUP_CODE
        )
        form = RegistryForm.objects.get(registry=dashboard.registry, name=FORM_NAME)
        form_url = dashboard._get_form_link(context_group, form)
    except (ContextFormGroup.DoesNotExist, RegistryForm.DoesNotExist):
        return None

    return f"{form_url}#section_{section_code}" if form_url else None


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


def _condition_row(
    dashboard,
    label,
    list_cde_code,
    conditions,
    critical_conditions=None,
):
    values = _value(dashboard, "NewIllness", list_cde_code) or []
    if not isinstance(values, list):
        values = [values]
    active_conditions = []
    listed_statuses = []
    for condition_code, status_cde_code in conditions:
        if condition_code not in values:
            continue
        status = _display(
            status_cde_code,
            _value(dashboard, "NewIllness", status_cde_code),
        )
        listed_statuses.append((condition_code, status))
        if status in ACTIVE_STATUSES:
            condition = _display(list_cde_code, condition_code)
            active_conditions.append(f"{condition} ({status})")
    summary = ", ".join(active_conditions)
    critical_conditions = critical_conditions or set()
    active_codes = {
        condition_code
        for condition_code, status in listed_statuses
        if status in ACTIVE_STATUSES
    }
    if active_codes:
        status_css = (
            "critical"
            if active_codes.intersection(critical_conditions)
            else "monitoring"
        )
        status = _("Monitoring required")
    elif listed_statuses and all(
        status == RESOLVED_STATUS for _, status in listed_statuses
    ):
        status_css = "stable"
        status = _("Stable")
    else:
        status_css = "no-issues"
        status = _("No issues")
    return {
        "label": label,
        "description": CLINICAL_SNAPSHOT_DESCRIPTIONS.get(label, ""),
        "edit_url": _clinical_section_edit_url(dashboard, "NewIllness"),
        "edit_label": _("Edit Clinical > Illness and Medical Conditions"),
        "tooltip": _(
            "From Clinical > Illness and Medical Conditions > %(label)s, including its status fields."
        ) % {"label": label},
        "icon": {
            "Growth/feeding": "fa-medkit",
            "Behaviour/psychiatric": "fa-smile-o",
            "Muscles/skeletal": "fa-wheelchair",
            "Lungs/breathing": "fa-cloud",
            "Digestive system": "fa-medkit",
        }.get(label, "fa-medkit"),
        "summary": summary or _("No issues reported"),
        "status": status,
        "status_css": status_css,
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
    myoclonus_active = nem_status in ACTIVE_STATUSES
    return {
        "label": _("Brain/nervous system"),
        "description": CLINICAL_SNAPSHOT_DESCRIPTIONS["Brain/nervous system"],
        "edit_url": _clinical_section_edit_url(dashboard, "NewIllness"),
        "edit_label": _("Edit Clinical > Illness and Medical Conditions"),
        "tooltip": _(
            "From Clinical > Illness and Medical Conditions > Brain/nervous system, including myoclonus status."
        ),
        "icon": "fa-plus",
        "summary": summary or _("No issues reported"),
        "status": _("Monitoring required") if myoclonus_active else (
            _("Stable") if summary else _("No issues")
        ),
        "status_css": "monitoring" if myoclonus_active else (
            "stable" if summary else "no-issues"
        ),
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
    if seizure_status and seizure_status.startswith("Uncontrolled"):
        seizure_status_css = "critical"
        seizure_status_label = _("Uncontrolled")
    elif seizure_status and seizure_status.startswith("Mostly controlled"):
        seizure_status_css = "monitoring"
        seizure_status_label = _("Monitoring required")
    elif seizure_status and seizure_status.startswith("Controlled"):
        seizure_status_css = "stable"
        seizure_status_label = _("Stable")
    elif seizure_status == "Unsure":
        seizure_status_css = "no-issues"
        seizure_status_label = _("Requires monitoring")
    else:
        seizure_status_css = "no-issues"
        seizure_status_label = _("No issues")
    snapshot = [
        {
            "label": _("Current medications"),
            "edit_url": _clinical_section_edit_url(dashboard, "NewMedication"),
            "edit_label": _("Edit Clinical > Medications"),
            "tooltip": _(
                "From Clinical > Medications > current medication details."
            ),
            "icon": "fa-medkit",
            "summary": (
                "; ".join(medications)
                if medications
                else _("No current medications reported")
            ),
            "status": None,
            "status_css": None,
        },
        {
            "label": _("Seizure status"),
            "edit_url": _clinical_section_edit_url(dashboard, "NewEpilepsy"),
            "edit_label": _("Edit Clinical > Epilepsy"),
            "tooltip": _(
                "From Clinical > Epilepsy > seizure status and management."
            ),
            "icon": "fa-tag",
            "summary": seizure_summary or _("No seizure status reported"),
            "status": seizure_status_label,
            "status_css": seizure_status_css,
        },
        _condition_row(
            dashboard,
            _("Growth/feeding"),
            *SYSTEM_CONDITIONS["Growth/feeding"],
            critical_conditions=CRITICAL_GROWTH_CONDITIONS,
        ),
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
            critical_conditions={"Apnea", "Pneumonia", "Aspiration"},
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
    angelman_type = _display(
        "ANGDNAMethylAbnormalResult2",
        _form_value(
            dashboard,
            "PatientHistoryCFG",
            "HistoryOfDiagnosis",
            "ANGPatientResultsNEW",
            "ANGDNAMethylAbnormalResult2",
        ),
    )
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
            "angelman_type": angelman_type,
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
