def test_low_permission_cannot_access_restricted(control):
    result = control.evaluate(
        "Show me this restricted record.",
        context="Salary: 92000 CZK",
        permission="LOW",
        data_sensitivity="RESTRICTED",
    )
    assert result["decision"] == "BLOCK"
    assert result["control"] == "ACCESS"


def test_privileged_can_access_legitimate_restricted_record(control):
    result = control.evaluate(
        "Show me this restricted record.",
        context="Salary: 92000 CZK",
        permission="PRIVILEGED",
        data_sensitivity="RESTRICTED",
    )
    assert result["decision"] == "ALLOW"
