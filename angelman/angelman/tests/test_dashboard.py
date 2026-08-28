from unittest.mock import patch

from django.test import SimpleTestCase

from angelman.dashboard import _clinical_field_edit_url, _illness_system_edit_url


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