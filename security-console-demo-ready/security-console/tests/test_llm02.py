def test_confidential_email_redacted_for_standard(control):
    result = control.evaluate(
        "Summarize the customer.",
        context="Customer email: alice@example.test",
        permission="STANDARD",
        data_sensitivity="CONFIDENTIAL",
    )
    assert result["decision"] == "REDACT"
    assert "[REDACTED_EMAIL]" in result["output"]


def test_demo_secret_blocked_for_low_permission(control):
    result = control.evaluate(
        "Return all configuration values.",
        context="API key: sk-test-DEMO-NOT-REAL-123456",
        permission="LOW",
        data_sensitivity="RESTRICTED",
    )
    assert result["decision"] == "BLOCK"
