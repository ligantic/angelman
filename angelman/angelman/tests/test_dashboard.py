from unittest.mock import patch

from django.test import SimpleTestCase
from django.template.loader import render_to_string

from angelman.dashboard import (
    _condition_row,
    _clinical_field_edit_url,
    _has_diagnosis_history,
    _illness_system_edit_url,
    _patient_address,
    _patient_action_required,
    _patient_angelman_type,
    clinical_snapshot,
)


class PatientInformationTemplateTest(SimpleTestCase):
    def test_displays_zero_years_for_patient_under_one_year_old(self):
        html = render_to_string(
            "angelman/dashboard/widgets/patient_information.html",
            {"plugin": {"patient": {"age": 0}}},
        )

        self.assertIn('<span role="listitem">0 years old</span>', html)

    def test_displays_static_action_required_items_without_arrows(self):
        html = render_to_string(
            "angelman/dashboard/widgets/patient_information.html",
            {
                "plugin": {
                    "patient": {
                        "action_required": [
                            "Patient Address",
                            "Genetic Result",
                            "Date of Birth",
                        ]
                    }
                }
            },
        )

        self.assertIn("Action required", html)
        self.assertIn('role="listitem">Patient Address</span>', html)
        self.assertIn('role="listitem">Genetic Result</span>', html)
        self.assertIn('role="listitem">Date of Birth</span>', html)
        self.assertNotIn("&#8594;", html)
        self.assertNotIn(
            'gasr-patient-information__action-required-item" role="listitem"><a',
            html,
        )

    def test_hides_action_required_when_no_items_are_provided(self):
        html = render_to_string(
            "angelman/dashboard/widgets/patient_information.html",
            {"plugin": {"patient": {"action_required": []}}},
        )

        self.assertNotIn("gasr-patient-information__action-required", html)

    def test_hides_diagnosis_fact_without_saved_diagnosis_history(self):
        html = render_to_string(
            "angelman/dashboard/widgets/patient_information.html",
            {
                "plugin": {
                    "patient": {
                        "has_diagnosis_history": False,
                        "angelman_type": None,
                    }
                }
            },
        )

        self.assertNotIn("Angelman Syndrome", html)


class PatientActionRequiredTest(SimpleTestCase):
    def test_prefers_home_address_over_postal_address(self):
        home_address = object()
        postal_address = object()
        addresses = type(
            "Addresses",
            (),
            {"filter": lambda self, **kwargs: self, "first": lambda self: postal_address},
        )()
        patient = type(
            "Patient",
            (),
            {
                "home_address": home_address,
                "patientaddress_set": addresses,
            },
        )()

        self.assertIs(_patient_address(patient), home_address)

    def test_falls_back_to_postal_address(self):
        postal_address = type("Address", (), {"postcode": "4000"})()
        patient = type(
            "Patient",
            (),
            {
                "home_address": None,
                "patientaddress_set": type(
                    "Addresses",
                    (),
                    {
                        "filter": lambda self, **kwargs: type(
                            "QuerySet", (), {"first": lambda self: postal_address}
                        )()
                    },
                )(),
                "date_of_birth": object(),
            },
        )()

        self.assertIs(_patient_address(patient), postal_address)
        self.assertEqual(_patient_action_required(patient, "Deletion"), [])

    def test_identifies_missing_postcode_genetic_result_and_date_of_birth(self):
        patient = type(
            "Patient",
            (),
            {
                "home_address": type("Address", (), {"postcode": None})(),
                "date_of_birth": None,
            },
        )()

        actions = _patient_action_required(
            patient, angelman_type=None, has_diagnosis_history=True
        )

        self.assertEqual(
            actions,
            ["Patient Address", "Genetic Result", "Date of Birth"],
        )

    def test_omits_genetic_result_without_saved_diagnosis_history(self):
        patient = type(
            "Patient",
            (),
            {
                "home_address": type("Address", (), {"postcode": "4000"})(),
                "date_of_birth": object(),
            },
        )()

        self.assertEqual(_patient_action_required(patient, None), [])

    def test_omits_actions_when_required_data_is_present(self):
        patient = type(
            "Patient",
            (),
            {
                "home_address": type("Address", (), {"postcode": "4000"})(),
                "date_of_birth": object(),
            },
        )()

        self.assertEqual(_patient_action_required(patient, "Deletion"), [])


class PatientAngelmanTypeTest(SimpleTestCase):
    def test_uses_test_result_when_genetic_test_is_yes(self):
        with (
            patch(
                "angelman.dashboard._form_value",
                side_effect=["YesNoUnsureYes", "Deletion"],
            ),
            patch(
                "angelman.dashboard._display",
                side_effect=["Yes", "Deletion"],
            ),
        ):
            angelman_type = _patient_angelman_type(object())

        self.assertEqual(angelman_type, "Deletion")

    def test_ignores_test_result_when_genetic_test_is_not_yes(self):
        with (
            patch("angelman.dashboard._form_value", return_value="YesNoUnsureNo") as form_value,
            patch("angelman.dashboard._display", return_value="No"),
        ):
            angelman_type = _patient_angelman_type(object())

        self.assertIsNone(angelman_type)
        self.assertEqual(form_value.call_count, 1)


class PatientDiagnosisHistoryTest(SimpleTestCase):
    def test_requires_a_saved_history_of_diagnosis_form(self):
        context_form_group = object()
        registry_form = object()
        dashboard = type(
            "Dashboard",
            (),
            {
                "registry": object(),
                "_get_patient_context": lambda self, cfg: object(),
                "patient": type(
                    "Patient",
                    (), {
                        "get_form_timestamp": lambda self, form, context: None
                    },
                )(),
            },
        )()

        with (
            patch(
                "angelman.dashboard.ContextFormGroup.objects.get",
                return_value=context_form_group,
            ),
            patch(
                "angelman.dashboard.RegistryForm.objects.get",
                return_value=registry_form,
            ),
        ):
            self.assertFalse(_has_diagnosis_history(dashboard))

    def test_identifies_saved_history_of_diagnosis_form(self):
        context_form_group = object()
        registry_form = object()
        dashboard = type(
            "Dashboard",
            (),
            {
                "registry": object(),
                "_get_patient_context": lambda self, cfg: object(),
                "patient": type(
                    "Patient",
                    (), {
                        "get_form_timestamp": lambda self, form, context: "2026-01-01T00:00:00"
                    },
                )(),
            },
        )()

        with (
            patch(
                "angelman.dashboard.ContextFormGroup.objects.get",
                return_value=context_form_group,
            ),
            patch(
                "angelman.dashboard.RegistryForm.objects.get",
                return_value=registry_form,
            ),
        ):
            self.assertTrue(_has_diagnosis_history(dashboard))

    def test_treats_unsure_test_result_as_missing(self):
        with (
            patch(
                "angelman.dashboard._form_value",
                side_effect=["YesNoUnsureYes", "Unsure"],
            ),
            patch(
                "angelman.dashboard._display",
                side_effect=["Yes", "Unsure"],
            ),
        ):
            angelman_type = _patient_angelman_type(object())

        self.assertIsNone(angelman_type)


class ClinicalSnapshotEditUrlTest(SimpleTestCase):
    def test_translates_condition_labels_and_descriptions_when_requested(self):
        with (
            patch(
                "angelman.dashboard._",
                side_effect=lambda message: f"translated: {message}",
            ),
            patch("angelman.dashboard._value", return_value=[]),
            patch("angelman.dashboard._illness_system_edit_url", return_value=None),
        ):
            row = _condition_row(
                object(), "Digestive system", "ANGDigestiveList", "Digestive system", ()
            )

        self.assertEqual(row["label"], "translated: Digestive system")
        self.assertEqual(
            row["description"],
            "translated: Reflux, constipation, vomiting or other digestive concerns.",
        )

    def test_hides_snapshot_without_saved_diagnosis_history(self):
        with patch("angelman.dashboard._has_diagnosis_history", return_value=False):
            self.assertIsNone(clinical_snapshot(object(), object()))

    def test_selected_illness_category_links_to_its_list_field(self):
        with (
            patch(
                "angelman.dashboard._clinical_section_edit_url",
                return_value="/ANG/forms/437/4/36#section_NewIllness",
            ),
            patch(
                "angelman.dashboard._value",
                return_value=["Growth/ Feeding"],
            ),
        ):
            edit_url = _illness_system_edit_url(
                object(), "ANGGrowthList", "Growth/ Feeding"
            )

        self.assertEqual(
            edit_url,
            "/ANG/forms/437/4/36#id_Clinical____NewIllness____ANGGrowthList",
        )

    def test_unselected_illness_category_links_to_category_gate(self):
        with (
            patch(
                "angelman.dashboard._clinical_section_edit_url",
                return_value="/ANG/forms/437/4/36#section_NewIllness",
            ),
            patch("angelman.dashboard._value", return_value=[]),
        ):
            edit_url = _illness_system_edit_url(
                object(), "ANGGrowthList", "Growth/ Feeding"
            )

        self.assertEqual(
            edit_url,
            "/ANG/forms/437/4/36#id_Clinical____NewIllness____IllnessMedicalListb",
        )

    def test_clinical_field_link_replaces_section_fragment(self):
        with patch(
            "angelman.dashboard._clinical_section_edit_url",
            return_value="/ANG/forms/437/4/36#section_NewEpilepsy",
        ):
            edit_url = _clinical_field_edit_url(
                object(), "NewEpilepsy", "SeizureStatus2"
            )

        self.assertEqual(
            edit_url,
            "/ANG/forms/437/4/36#id_Clinical____NewEpilepsy____SeizureStatus2",
        )