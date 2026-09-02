from unittest.mock import patch

from django.test import SimpleTestCase
from django.template.loader import render_to_string

from angelman.dashboard import (
    _clinical_field_edit_url,
    _illness_system_edit_url,
    _patient_action_required,
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


class PatientActionRequiredTest(SimpleTestCase):
    def test_identifies_missing_postcode_genetic_result_and_date_of_birth(self):
        patient = type(
            "Patient",
            (),
            {
                "home_address": type("Address", (), {"postcode": None})(),
                "date_of_birth": None,
            },
        )()

        actions = _patient_action_required(patient, angelman_type=None)

        self.assertEqual(
            actions,
            ["Patient Address", "Genetic Result", "Date of Birth"],
        )

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


class ClinicalSnapshotEditUrlTest(SimpleTestCase):
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