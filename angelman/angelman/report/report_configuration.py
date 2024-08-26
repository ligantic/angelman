from report.report_configuration import get_configuration


def get_angelman_configuration():
    angelman_report_configuration = get_configuration()
    demographic_model = angelman_report_configuration["demographic_model"]
    if "patientEmailPreferences" in demographic_model:
        del demographic_model["patientEmailPreferences"]

    return angelman_report_configuration
