import csv
import io
import json
from datetime import date, datetime, timezone
from fractions import Fraction
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase, TestCase
from rdrf.models.definition.models import (
    ClinicalData,
    ContextFormGroup,
    RDRFContext,
    Registry,
)
from registry.groups.models import CustomUser
from registry.patients.models import (
    AddressType,
    ParentGuardian,
    Patient,
    PatientAddress,
    get_countries,
)
from report.filter_providers import (
    get_report_filter_providers,
    validate_report_filter_parameters,
)
from report.forms import ReportDesignerForm, get_demographic_field_value
from report.models import ReportCdeHeadingFormat, ReportDesign
from report.report_builder import ReportBuilder

from angelman.report.filters import (
    ADMIN,
    HISTORY,
    SIGNUP,
    DIAGNOSIS_CHOICES,
    HISTORY_CODES,
    REGISTRATION_CODES,
    AngelmanDiagnosisFilter,
    PatientAgeFilter,
    PatientCountryFilter,
)


class AngelmanDiagnosisFilterTests(TestCase):
    databases = ("default", "clinical")

    def setUp(self):
        self.registry = Registry.objects.create(code="ang", name="Angelman")
        self.content_type = ContentType.objects.get_for_model(Patient)
        self.groups = {
            source: ContextFormGroup.objects.create(
                registry=self.registry,
                code=source.context_group,
                name=source.context_group,
            )
            for source in (ADMIN, HISTORY, SIGNUP)
        }
        self.provider = AngelmanDiagnosisFilter()

    def patient(self):
        patient = Patient.objects.create(
            consent=True, date_of_birth=date(2000, 1, 1)
        )
        patient.rdrf_registry.add(self.registry)
        return patient

    def record(
        self,
        patient,
        source,
        value,
        *,
        test="YesNoUnsureYes",
        timestamp="2026-01-01T10:00:00",
        active=True,
    ):
        context = RDRFContext.objects.create(
            registry=self.registry,
            content_type=self.content_type,
            object_id=patient.pk,
            context_form_group=self.groups[source],
            active=active,
        )
        cdes = [{"code": source.cde, "value": value}]
        if source == HISTORY:
            cdes.append({"code": "ANGGeneticTestV2", "value": test})
        data = {
            "forms": [
                {
                    "name": source.form,
                    "sections": [{"code": source.section, "cdes": cdes}],
                }
            ],
        }
        if timestamp is not None:
            data[f"{source.form}_timestamp"] = timestamp
        return ClinicalData.objects.create(
            registry_code=self.registry.code,
            collection="cdes",
            django_id=patient.pk,
            context_id=context.pk,
            data=data,
        )

    def matching(self, patients, diagnoses, quality="best_available"):
        parameters = validate_report_filter_parameters(
            self.provider, {"diagnoses": diagnoses, "quality": quality}
        )
        return self.provider.get_matching_patient_ids(
            self.registry, [patient.pk for patient in patients], parameters
        )

    def test_registration_and_required_parameters(self):
        form_class = self.provider.parameter_form_class
        self.assertEqual(form_class()["quality"].value(), "verified")
        self.assertEqual(
            form_class(initial={"quality": "best_available"})[
                "quality"
            ].value(),
            "best_available",
        )
        self.assertIsInstance(
            get_report_filter_providers(self.registry)["angelman.diagnosis"],
            AngelmanDiagnosisFilter,
        )
        self.assertEqual(len(DIAGNOSIS_CHOICES), 7)
        for parameters in (
            {"diagnoses": [], "quality": "verified"},
            {"diagnoses": ["invalid"], "quality": "verified"},
            {"diagnoses": ["unknown"], "quality": "invalid"},
            {"diagnoses": ["unknown"]},
            {"diagnoses": ["unknown"], "quality": "verified", "extra": True},
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValidationError):
                    validate_report_filter_parameters(self.provider, parameters)

    def test_all_signup_and_admin_codes(self):
        for source in (ADMIN, SIGNUP):
            for raw, canonical in REGISTRATION_CODES.items():
                with self.subTest(source=source, raw=raw):
                    patient = self.patient()
                    self.record(patient, source, raw)
                    self.assertEqual(
                        self.matching([patient], [canonical]), {patient.pk}
                    )

    def test_all_history_codes_including_unsure(self):
        for raw, canonical in HISTORY_CODES.items():
            with self.subTest(raw=raw):
                patient = self.patient()
                self.record(patient, HISTORY, raw)
                self.assertEqual(
                    self.matching([patient], [canonical]), {patient.pk}
                )

    def test_precedence_is_independent_of_selected_types(self):
        patient = self.patient()
        self.record(patient, SIGNUP, "RegistrationDiagnosisMosaic")
        self.record(patient, HISTORY, "UPD")
        self.record(patient, ADMIN, "RegistrationDiagnosisDeletion")
        self.assertEqual(self.matching([patient], ["deletion"]), {patient.pk})
        self.assertEqual(self.matching([patient], ["upd", "mosaic"]), set())

    def test_history_precedes_signup_and_blank_admin_allows_fallback(self):
        patient = self.patient()
        self.record(patient, ADMIN, "")
        self.record(patient, HISTORY, "UPD")
        self.record(patient, SIGNUP, "RegistrationDiagnosisDeletion")
        self.assertEqual(self.matching([patient], ["upd"]), {patient.pk})
        self.assertEqual(self.matching([patient], ["deletion"]), set())
        self.assertEqual(self.matching([patient], ["upd"], "verified"), set())

    def test_blank_history_falls_back_to_signup_without_form_timestamp(self):
        patient = self.patient()
        self.record(patient, HISTORY, "")
        self.record(
            patient, SIGNUP, "RegistrationDiagnosisClinical", timestamp=None
        )
        self.assertEqual(self.matching([patient], ["clinical"]), {patient.pk})

    def test_history_requires_positive_genetic_test_not_form_completion(self):
        for answer in (None, "", "YesNoUnsureNo", "YesNoUnsureUnsure"):
            with self.subTest(answer=answer):
                patient = self.patient()
                self.record(patient, HISTORY, "UPD", test=answer)
                self.record(patient, SIGNUP, "RegistrationDiagnosisDeletion")
                self.assertEqual(
                    self.matching([patient], ["deletion"]), {patient.pk}
                )
        patient = self.patient()
        self.record(patient, HISTORY, "UPD")
        self.assertEqual(self.matching([patient], ["upd"]), {patient.pk})

    def test_unknown_stops_fallback_at_admin_or_history(self):
        for source, value in (
            (ADMIN, "RegistrationDiagnosisUnknown"),
            (HISTORY, "Unsure"),
        ):
            with self.subTest(source=source):
                patient = self.patient()
                self.record(patient, source, value)
                self.record(patient, SIGNUP, "RegistrationDiagnosisDeletion")
                self.assertEqual(
                    self.matching([patient], ["unknown"]), {patient.pk}
                )
                self.assertEqual(self.matching([patient], ["deletion"]), set())

    def test_verified_excludes_missing_admin_but_includes_explicit_unknown(
        self,
    ):
        missing, signup, verified = [self.patient() for _ in range(3)]
        self.record(signup, SIGNUP, "RegistrationDiagnosisUnknown")
        self.record(verified, ADMIN, "RegistrationDiagnosisUnknown")
        patients = [missing, signup, verified]
        self.assertEqual(
            self.matching(patients, ["unknown"]), {p.pk for p in patients}
        )
        self.assertEqual(
            self.matching(patients, ["unknown"], "verified"), {verified.pk}
        )

    def test_latest_form_timestamp_not_context_or_document_order_wins(self):
        patient = self.patient()
        self.record(
            patient,
            ADMIN,
            "RegistrationDiagnosisUPD",
            timestamp="2026-03-01T00:00:00+00:00",
        )
        self.record(
            patient,
            ADMIN,
            "RegistrationDiagnosisDeletion",
            timestamp="2026-02-01T00:00:00",
        )
        self.assertEqual(self.matching([patient], ["upd"]), {patient.pk})

    def test_latest_blank_does_not_resurrect_older_admin_value(self):
        patient = self.patient()
        self.record(patient, ADMIN, "RegistrationDiagnosisDeletion")
        self.record(patient, ADMIN, "", timestamp="2026-02-01T00:00:00")
        self.record(patient, SIGNUP, "RegistrationDiagnosisMosaic")
        self.assertEqual(self.matching([patient], ["mosaic"]), {patient.pk})
        self.assertEqual(
            self.matching([patient], ["deletion"], "verified"), set()
        )

    def test_tied_timestamps_use_record_id_deterministically(self):
        patient = self.patient()
        self.record(patient, ADMIN, "RegistrationDiagnosisDeletion")
        self.record(patient, ADMIN, "RegistrationDiagnosisUPD")
        self.assertEqual(self.matching([patient], ["upd"]), {patient.pk})

    def test_inactive_wrong_group_and_legacy_history_are_not_used(self):
        patient = self.patient()
        self.record(
            patient, ADMIN, "RegistrationDiagnosisDeletion", active=False
        )
        inactive_record = self.record(
            patient, ADMIN, "RegistrationDiagnosisDeletion"
        )
        ClinicalData.objects.filter(pk=inactive_record.pk).update(active=False)
        wrong_group = self.record(
            patient, ADMIN, "RegistrationDiagnosisDeletion"
        )
        RDRFContext.objects.filter(pk=wrong_group.context_id).update(
            context_form_group=self.groups[SIGNUP]
        )
        legacy = self.record(patient, HISTORY, "UPD")
        legacy.data["forms"][0]["name"] = (
            "AngelmanRegistryHistoryOfDiagnosisAndResults"
        )
        legacy.save()
        self.assertEqual(self.matching([patient], ["unknown"]), {patient.pk})

    def test_resolved_admin_does_not_evaluate_lower_priority_invalid_codes(
        self,
    ):
        patient = self.patient()
        self.record(patient, ADMIN, "RegistrationDiagnosisUPD")
        self.record(patient, HISTORY, "invalid")
        self.record(patient, SIGNUP, "invalid")
        self.assertEqual(self.matching([patient], ["upd"]), {patient.pk})

    def test_mismatched_patient_context_fails_explicitly(self):
        owner, other = self.patient(), self.patient()
        record = self.record(owner, ADMIN, "RegistrationDiagnosisUPD")
        ClinicalData.objects.filter(pk=record.pk).update(django_id=other.pk)
        with self.assertRaisesMessage(ValidationError, "patient context"):
            self.matching([owner, other], ["upd"])

    def test_invalid_used_codes_and_timestamps_fail_explicitly(self):
        for source in (ADMIN, HISTORY, SIGNUP):
            for invalid in ("unexpected", ["Deletion"]):
                with self.subTest(source=source, invalid=invalid):
                    patient = self.patient()
                    self.record(patient, source, invalid)
                    with self.assertRaisesMessage(
                        ValidationError, "Invalid diagnosis code"
                    ):
                        self.matching([patient], ["unknown"])
        patient = self.patient()
        self.record(patient, HISTORY, "UPD", test="unexpected")
        with self.assertRaisesMessage(ValidationError, "genetic-test code"):
            self.matching([patient], ["unknown"])
        patient = self.patient()
        self.record(
            patient, ADMIN, "RegistrationDiagnosisUPD", timestamp="invalid"
        )
        with self.assertRaisesMessage(
            ValidationError, "Invalid saved timestamp"
        ):
            self.matching([patient], ["unknown"])

    def test_bulk_routed_loading_and_batch_independence(self):
        patients = [self.patient() for _ in range(6)]
        for index, patient in enumerate(patients):
            self.record(
                patient,
                ADMIN,
                "RegistrationDiagnosisUPD"
                if index % 2
                else "RegistrationDiagnosisDeletion",
            )
        with self.assertNumQueries(1, using="default"):
            with self.assertNumQueries(1, using="clinical"):
                together = self.matching(patients, ["upd"])
        separate = set()
        for patient in reversed(patients):
            separate.update(self.matching([patient], ["upd"]))
        self.assertEqual(together, separate)
        self.assertEqual(together, {p.pk for p in patients[1::2]})
        self.assertEqual(self.matching([], ["unknown"]), set())

    def test_designer_persistence_and_identical_preview_csv_json_membership(
        self,
    ):
        matching, excluded = self.patient(), self.patient()
        too_young = self.patient()
        too_young.date_of_birth = date.today()
        too_young.save()
        self.record(matching, ADMIN, "RegistrationDiagnosisUPD")
        self.record(excluded, SIGNUP, "RegistrationDiagnosisUPD")
        self.record(too_young, ADMIN, "RegistrationDiagnosisUPD")
        wrong_country = self.patient()
        self.record(wrong_country, ADMIN, "RegistrationDiagnosisUPD")
        parent = ParentGuardian.objects.create(country="AU")
        parent.patient.add(matching, excluded, too_young)
        other_parent = ParentGuardian.objects.create(country="GB")
        other_parent.patient.add(wrong_country)
        design = ReportDesign.objects.create(
            registry=self.registry,
            title="Verified diagnosis",
            cde_heading_format=ReportCdeHeadingFormat.CODE.value,
        )
        form = ReportDesignerForm(
            instance=design,
            data={
                "title": design.title,
                "registry": self.registry.code,
                "cde_heading_format": ReportCdeHeadingFormat.CODE.value,
                "demographic_fields": [
                    get_demographic_field_value("patient", "id")
                ],
                "custom_filter_enabled_0": "on",
                "custom_filter_0-diagnoses": ["upd", "mosaic"],
                "custom_filter_0-quality": "verified",
                "custom_filter_enabled_1": "on",
                "custom_filter_1-minimum_age": "20.5",
                "custom_filter_1-maximum_age": "",
                "custom_filter_enabled_2": "on",
                "custom_filter_2-countries": ["AU", "NZ"],
            },
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save_to_model()
        design.refresh_from_db()
        self.assertEqual(
            design.custom_filters["filters"]["angelman.diagnosis"][
                "parameters"
            ],
            {"diagnoses": ["upd", "mosaic"], "quality": "verified"},
        )
        restored = ReportDesignerForm(instance=design)
        html = str(
            restored.custom_filter_groups[0]["filters"][0]["parameter_form"]
        )
        for label in (
            "Verified (Admin)",
            "Best available",
            "Unknown",
            "Clinical",
        ):
            self.assertIn(label, html)
        self.assertEqual(
            restored.custom_filter_groups[0]["filters"][0]["parameter_form"][
                "diagnoses"
            ].value(),
            ["upd", "mosaic"],
        )
        self.assertIn('value="verified" selected', html)
        age_form = restored.custom_filter_groups[0]["filters"][1][
            "parameter_form"
        ]
        self.assertEqual(age_form["minimum_age"].value(), "20.5")
        self.assertIsNone(age_form["maximum_age"].value())
        self.assertEqual(
            design.custom_filters["filters"]["angelman.patient_age"][
                "parameters"
            ],
            {"minimum_age": "20.5", "maximum_age": None},
        )
        self.assertEqual(
            design.custom_filters["filters"]["angelman.patient_country"][
                "parameters"
            ],
            {"countries": ["AU", "NZ"]},
        )
        country_form = restored.custom_filter_groups[0]["filters"][2][
            "parameter_form"
        ]
        self.assertEqual(country_form["countries"].value(), ["AU", "NZ"])
        request = RequestFactory().get("/")
        request.user = CustomUser.objects.create(
            username="diagnosis-admin",
            is_active=True,
            is_superuser=True,
        )
        self.client.force_login(request.user)
        response = self.client.get(f"/report/{design.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Filter by Angelman Diagnosis")
        self.assertContains(response, "Verified (Admin)")
        self.assertContains(response, "Best available")
        self.assertContains(response, "Filter by Patient Age")
        self.assertContains(response, "Minimum age (years)")
        self.assertContains(response, "Maximum age (years)")
        self.assertContains(response, "Filter by Country")
        self.assertContains(response, "Australia")
        self.assertContains(response, "New Zealand")
        report = ReportBuilder(design)
        valid, errors = report.validate_query(request)
        self.assertTrue(valid, errors)
        _, preview = report.build_preview(request)
        self.assertEqual(preview, [[str(matching.pk)]])
        csv_export = "".join(
            chunk.decode("utf-8-sig") if isinstance(chunk, bytes) else chunk
            for chunk in report.export_to_csv(request)
        )
        self.assertEqual(list(csv.reader(io.StringIO(csv_export)))[1:], preview)
        self.assertEqual(
            [
                str(json.loads(row)["id"])
                for row in report.export_to_json(request)
            ],
            [str(matching.pk)],
        )

    def test_invalid_diagnosis_is_reported_before_export(self):
        patient = self.patient()
        self.record(patient, ADMIN, "invalid")
        design = ReportDesign.objects.create(
            registry=self.registry,
            title="Invalid diagnosis",
            custom_filters={
                "schema_version": 1,
                "filters": {
                    "angelman.diagnosis": {
                        "version": 1,
                        "parameters": {
                            "diagnoses": ["unknown"],
                            "quality": "verified",
                        },
                    },
                },
            },
        )
        design.reportdemographicfield_set.create(
            model="patient", field="id", sort_order=0
        )
        request = RequestFactory().get("/")
        request.user = CustomUser.objects.create(
            username="diagnosis-errors",
            is_active=True,
            is_superuser=True,
        )
        valid, errors = ReportBuilder(design).validate_query(request)
        self.assertFalse(valid)
        self.assertIn("Invalid diagnosis code", str(errors))


class PatientAgeParametersTests(SimpleTestCase):
    def setUp(self):
        self.provider = PatientAgeFilter()

    def test_optional_bounds_are_json_serialisable_and_revalidate(self):
        for raw, expected in (
            ({}, {"minimum_age": None, "maximum_age": None}),
            (
                {"minimum_age": "", "maximum_age": ""},
                {"minimum_age": None, "maximum_age": None},
            ),
            (
                {"minimum_age": "0", "maximum_age": "10.5"},
                {"minimum_age": "0", "maximum_age": "10.5"},
            ),
            (
                {"minimum_age": "10.5000000000000000001"},
                {"minimum_age": "10.5000000000000000001", "maximum_age": None},
            ),
            (
                {"maximum_age": "0.25"},
                {"minimum_age": None, "maximum_age": "0.25"},
            ),
        ):
            with self.subTest(raw=raw):
                parameters = validate_report_filter_parameters(
                    self.provider, raw
                )
                self.assertEqual(parameters, expected)
                self.assertEqual(
                    validate_report_filter_parameters(
                        self.provider, json.loads(json.dumps(parameters))
                    ),
                    expected,
                )

    def test_invalid_bounds_are_rejected(self):
        for parameters in (
            {"minimum_age": "-0.1"},
            {"maximum_age": "-1"},
            {"minimum_age": "10", "maximum_age": "9.99"},
            {"minimum_age": "invalid"},
            {"minimum_age": "NaN"},
            {"maximum_age": "Infinity"},
            {"maximum_age": "-Infinity"},
            {"minimum_age": "1", "unexpected": "value"},
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValidationError):
                    validate_report_filter_parameters(self.provider, parameters)

    def test_equal_bounds_and_arbitrary_decimal_input_step(self):
        parameters = validate_report_filter_parameters(
            self.provider, {"minimum_age": "10.5", "maximum_age": "10.5"}
        )
        self.assertEqual(parameters["minimum_age"], parameters["maximum_age"])
        html = str(self.provider.parameter_form_class())
        self.assertEqual(html.count('step="any"'), 2)
        self.assertNotIn("required", html)

    def test_calendar_fraction_uses_birthday_interval_without_rounding(self):
        for born, on, expected in (
            (date(2014, 1, 1), date(2024, 1, 1), Fraction(10)),
            (date(2014, 1, 1), date(2024, 7, 2), Fraction(21, 2)),
            (date(2014, 1, 1), date(2023, 7, 2), 9 + Fraction(182, 365)),
            (date(2014, 7, 2), date(2024, 7, 1), 9 + Fraction(365, 366)),
            (date(2024, 7, 2), date(2024, 7, 2), Fraction(0)),
            (date(2024, 1, 1), date(2024, 7, 2), Fraction(1, 2)),
        ):
            with self.subTest(born=born, on=on):
                self.assertEqual(
                    self.provider._age_in_years(born, on), expected
                )

    def test_leap_day_birthdays_follow_patient_age_march_first_convention(self):
        born = date(2020, 2, 29)
        for on, expected in (
            (date(2021, 2, 28), Fraction(365, 366)),
            (date(2021, 3, 1), Fraction(1)),
            (date(2024, 2, 28), 3 + Fraction(364, 365)),
            (date(2024, 2, 29), Fraction(4)),
            (date(2025, 2, 28), 4 + Fraction(365, 366)),
            (date(2025, 3, 1), Fraction(5)),
        ):
            with self.subTest(on=on):
                self.assertEqual(
                    self.provider._age_in_years(born, on), expected
                )

    def test_future_birth_dates_fail_explicitly_when_calculating_age(self):
        with self.assertRaisesMessage(
            ValidationError, "Date of birth is after"
        ):
            self.provider._age_in_years(date(2025, 1, 1), date(2024, 1, 1))


class PatientAgeFilterTests(TestCase):
    def setUp(self):
        self.registry = Registry.objects.create(code="ang", name="Angelman")
        self.provider = PatientAgeFilter()
        date_mock = patch("angelman.report.filters.datetime", wraps=datetime)
        date_mock.start().now.return_value = datetime(
            2024, 7, 2, tzinfo=timezone.utc
        )
        self.addCleanup(date_mock.stop)
        self.ten = self.patient(date(2014, 7, 2))
        self.ten_and_half = self.patient(date(2014, 1, 1))
        self.eleven = self.patient(date(2013, 7, 2))
        self.newborn = self.patient(date(2024, 7, 2))
        self.patients = [self.ten, self.ten_and_half, self.eleven, self.newborn]

    def patient(self, born, died=None):
        patient = Patient.objects.create(
            consent=True, date_of_birth=born, date_of_death=died
        )
        patient.rdrf_registry.add(self.registry)
        return patient

    def matching(self, minimum=None, maximum=None, patients=None):
        parameters = validate_report_filter_parameters(
            self.provider, {"minimum_age": minimum, "maximum_age": maximum}
        )
        return self.provider.get_matching_patient_ids(
            self.registry,
            [
                p.pk
                for p in (patients if patients is not None else self.patients)
            ],
            parameters,
        )

    def test_registered_for_actual_registry(self):
        self.assertIsInstance(
            get_report_filter_providers(self.registry)["angelman.patient_age"],
            PatientAgeFilter,
        )

    def test_new_designer_can_save_restore_and_disable_open_age_range(self):
        blank = ReportDesignerForm()
        self.assertEqual(len(blank.custom_filter_groups[0]["filters"]), 3)
        data = {
            "title": "Age range",
            "registry": self.registry.code,
            "cde_heading_format": ReportCdeHeadingFormat.CODE.value,
            "demographic_fields": [
                get_demographic_field_value("patient", "id")
            ],
            "custom_filter_enabled_1": "on",
            "custom_filter_1-minimum_age": "",
            "custom_filter_1-maximum_age": "10.5",
        }
        form = ReportDesignerForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save_to_model()
        configuration = {
            "schema_version": 1,
            "filters": {
                "angelman.patient_age": {
                    "version": 1,
                    "parameters": {
                        "minimum_age": None,
                        "maximum_age": "10.5",
                    },
                },
            },
        }
        self.assertEqual(form.instance.custom_filters, configuration)
        restored = ReportDesignerForm(instance=form.instance)
        age_form = restored.custom_filter_groups[0]["filters"][1][
            "parameter_form"
        ]
        self.assertIsNone(age_form["minimum_age"].value())
        self.assertEqual(age_form["maximum_age"].value(), "10.5")
        data.pop("custom_filter_enabled_1")
        disabled = ReportDesignerForm(data=data, instance=form.instance)
        self.assertTrue(disabled.is_valid(), disabled.errors)
        disabled.save_to_model()
        self.assertEqual(disabled.instance.custom_filters, {})

    def test_inclusive_decimal_range_and_equal_bounds(self):
        self.assertEqual(
            self.matching("10", "10.5"), {self.ten.pk, self.ten_and_half.pk}
        )
        self.assertEqual(self.matching("10.5", "10.5"), {self.ten_and_half.pk})
        self.assertEqual(self.matching("0", "0"), {self.newborn.pk})

    def test_empty_minimum_or_maximum_is_an_open_bound(self):
        self.assertEqual(
            self.matching("10.5"), {self.ten_and_half.pk, self.eleven.pk}
        )
        self.assertEqual(
            self.matching(maximum="10"), {self.ten.pk, self.newborn.pk}
        )

    def test_no_bounds_is_no_restriction_or_database_query(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.matching(), {p.pk for p in self.patients})
        with self.assertNumQueries(0):
            self.assertEqual(self.matching("10", patients=[]), set())

    def test_decimal_precision_is_not_rounded_to_the_boundary(self):
        self.assertNotIn(
            self.ten_and_half.pk, self.matching("10.5000000000000000001")
        )
        self.assertNotIn(
            self.ten_and_half.pk,
            self.matching(maximum="10.4999999999999999999"),
        )

    def test_age_stops_at_date_of_death(self):
        deceased = self.patient(date(2000, 1, 1), date(2010, 1, 1))
        self.assertEqual(self.matching("10", "10", [deceased]), {deceased.pk})
        self.assertEqual(self.matching("24", patients=[deceased]), set())

    def test_bulk_query_is_bounded_and_batch_and_order_independent(self):
        with self.assertNumQueries(1):
            together = self.matching("10", "10.5")
        separate = set()
        for patient in reversed(self.patients):
            separate.update(self.matching("10", "10.5", [patient]))
        self.assertEqual(together, separate)

    def test_does_not_add_patients_outside_registry_or_input(self):
        other = self.patient(date(2014, 7, 2))
        other.rdrf_registry.clear()
        self.assertEqual(self.matching("10", patients=[other]), set())
        self.assertEqual(
            self.matching("10", patients=[self.ten]), {self.ten.pk}
        )


class PatientCountryParametersTests(SimpleTestCase):
    def test_requires_valid_country_codes_and_serialises_selections(self):
        provider = PatientCountryFilter()
        parameters = validate_report_filter_parameters(
            provider, {"countries": ["AU", "NZ"]}
        )
        self.assertEqual(json.loads(json.dumps(parameters)), parameters)
        self.assertEqual(parameters, {"countries": ["AU", "NZ"]})
        form = provider.parameter_form_class()
        self.assertEqual(
            list(form.fields["countries"].choices), get_countries()
        )
        self.assertIn("multiple", str(form["countries"]))
        for invalid in (
            {},
            {"countries": []},
            {"countries": ["XX"]},
            {"countries": ["Australia"]},
            {"countries": ["AU"], "extra": True},
        ):
            with self.subTest(parameters=invalid):
                with self.assertRaises(ValidationError):
                    validate_report_filter_parameters(provider, invalid)


class PatientCountryFilterTests(TestCase):
    def setUp(self):
        self.registry = Registry.objects.create(code="ang", name="Angelman")
        self.home = AddressType.objects.create(type="Home")
        self.postal = AddressType.objects.create(type="Postal")
        self.provider = PatientCountryFilter()

    def patient(self):
        patient = Patient.objects.create(
            consent=True, date_of_birth=date(2000, 1, 1)
        )
        patient.rdrf_registry.add(self.registry)
        return patient

    def address(self, patient, country, address_type=None):
        return PatientAddress.objects.create(
            patient=patient,
            country=country,
            address_type=address_type or self.home,
        )

    def parent(self, patient, country, user=None):
        parent = ParentGuardian.objects.create(country=country, user=user)
        parent.patient.add(patient)
        return parent

    def matching(self, patients, countries=None):
        parameters = validate_report_filter_parameters(
            self.provider, {"countries": countries or ["AU"]}
        )
        return self.provider.get_matching_patient_ids(
            self.registry, [p.pk for p in patients], parameters
        )

    def test_registered_for_actual_registry(self):
        self.assertIsInstance(
            get_report_filter_providers(self.registry)[
                "angelman.patient_country"
            ],
            PatientCountryFilter,
        )

    def test_multiple_selected_countries_match_either_home_country(self):
        australia, nz, uk = [self.patient() for _ in range(3)]
        for patient, country in ((australia, "AU"), (nz, "NZ"), (uk, "GB")):
            self.address(patient, country)
        self.assertEqual(
            self.matching([australia, nz, uk], ["AU", "NZ"]),
            {australia.pk, nz.pk},
        )

    def test_home_precedes_postal_and_parent_even_when_it_does_not_match(self):
        patient = self.patient()
        self.address(patient, "GB")
        self.address(patient, "AU", self.postal)
        self.parent(patient, "AU")
        self.assertEqual(self.matching([patient]), set())
        self.assertEqual(self.matching([patient], ["GB"]), {patient.pk})

    def test_postal_precedes_parent_if_no_home_country(self):
        patient = self.patient()
        self.address(patient, " ")
        self.address(patient, "NZ", self.postal)
        self.parent(patient, "AU")
        self.assertEqual(self.matching([patient]), set())
        self.assertEqual(self.matching([patient], ["NZ"]), {patient.pk})

    def test_falls_back_to_parent_for_missing_or_blank_patient_countries(self):
        missing, blank = self.patient(), self.patient()
        self.address(blank, "")
        self.address(blank, "  ", self.postal)
        self.parent(missing, "AU")
        self.parent(blank, "AU")
        self.assertEqual(
            self.matching([missing, blank]), {missing.pk, blank.pk}
        )

    def test_fallback_matches_any_linked_parent_country_and_deduplicates(self):
        patient = self.patient()
        self.parent(patient, "GB")
        self.parent(patient, "")
        self.parent(patient, "AU")
        self.parent(patient, "AU")
        self.assertEqual(self.matching([patient]), {patient.pk})
        self.assertEqual(self.matching([patient], ["GB"]), {patient.pk})

    def test_uses_current_registration_parent_user_address(self):
        patient = self.patient()
        user = CustomUser.objects.create(username="country-parent")
        parent = self.parent(patient, "AU", user)
        self.assertEqual(self.matching([patient]), {patient.pk})
        parent.country = "NZ"
        parent.save()
        self.assertEqual(self.matching([patient]), set())
        self.assertEqual(self.matching([patient], ["NZ"]), {patient.pk})

    def test_shared_parent_only_returns_input_patients(self):
        first, second = self.patient(), self.patient()
        parent = self.parent(first, "AU")
        parent.patient.add(second)
        self.assertEqual(self.matching([first]), {first.pk})

    def test_missing_countries_and_unrelated_parents_do_not_match(self):
        patient, other = self.patient(), self.patient()
        self.parent(patient, "")
        self.parent(other, "AU")
        self.assertEqual(self.matching([patient]), set())

    def test_uses_first_nonblank_address_of_each_type_by_record_id(self):
        patient = self.patient()
        self.address(patient, "")
        self.address(patient, "GB")
        self.address(patient, "AU")
        self.assertEqual(self.matching([patient]), set())
        self.assertEqual(self.matching([patient], ["GB"]), {patient.pk})

    def test_normalises_case_and_whitespace_in_saved_country_codes(self):
        patient, fallback = self.patient(), self.patient()
        self.address(patient, " au ")
        self.parent(fallback, "au")
        self.assertEqual(
            self.matching([patient, fallback]), {patient.pk, fallback.pk}
        )

    def test_invalid_used_country_codes_fail_rather_than_allow_fallback(self):
        for source in ("Home", "Postal", "Parent"):
            with self.subTest(source=source):
                patient = self.patient()
                if source == "Parent":
                    self.parent(patient, "invalid")
                else:
                    self.address(
                        patient,
                        "invalid",
                        self.home if source == "Home" else self.postal,
                    )
                    self.parent(patient, "AU")
                with self.assertRaisesMessage(
                    ValidationError, "Invalid country"
                ):
                    self.matching([patient])

    def test_does_not_evaluate_lower_priority_invalid_codes(self):
        patient = self.patient()
        self.address(patient, "AU")
        self.address(patient, "invalid", self.postal)
        self.parent(patient, "invalid")
        self.assertEqual(self.matching([patient]), {patient.pk})

    def test_bounded_queries_and_batch_and_order_independence(self):
        patients = [self.patient() for _ in range(6)]
        for index, patient in enumerate(patients):
            if index % 2:
                self.parent(patient, "AU")
            else:
                self.address(patient, "GB")
        with self.assertNumQueries(2):
            together = self.matching(patients)
        separate = set()
        for patient in reversed(patients):
            separate.update(self.matching([patient]))
        self.assertEqual(together, separate)
        self.assertEqual(together, {p.pk for p in patients[1::2]})
        with self.assertNumQueries(1):
            self.matching(patients[::2])
        with self.assertNumQueries(0):
            self.assertEqual(self.matching([]), set())

    def test_new_designer_requires_selection_and_can_disable_country_filter(
        self,
    ):
        data = {
            "title": "Country filter",
            "registry": self.registry.code,
            "cde_heading_format": ReportCdeHeadingFormat.CODE.value,
            "demographic_fields": [
                get_demographic_field_value("patient", "id")
            ],
            "custom_filter_enabled_2": "on",
        }
        invalid = ReportDesignerForm(data=data)
        self.assertFalse(invalid.is_valid())
        data["custom_filter_2-countries"] = ["AU", "NZ"]
        form = ReportDesignerForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        form.save_to_model()
        self.assertEqual(
            form.instance.custom_filters["filters"]["angelman.patient_country"],
            {"version": 1, "parameters": {"countries": ["AU", "NZ"]}},
        )
        data.pop("custom_filter_enabled_2")
        disabled = ReportDesignerForm(data=data, instance=form.instance)
        self.assertTrue(disabled.is_valid(), disabled.errors)
        disabled.save_to_model()
        self.assertEqual(disabled.instance.custom_filters, {})
