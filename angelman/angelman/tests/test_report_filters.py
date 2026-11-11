import csv
import io
import json
from datetime import date

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from rdrf.models.definition.models import (
    ClinicalData,
    ContextFormGroup,
    RDRFContext,
    Registry,
)
from registry.groups.models import CustomUser
from registry.patients.models import Patient
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
            form_class(initial={"quality": "best_available"})["quality"].value(),
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
        self.record(matching, ADMIN, "RegistrationDiagnosisUPD")
        self.record(excluded, SIGNUP, "RegistrationDiagnosisUPD")
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
