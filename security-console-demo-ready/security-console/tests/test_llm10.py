def test_normal_token_request_allowed(control):
    result = control.evaluate(
        "Write a short summary.",
        permission="STANDARD",
        data_sensitivity="PUBLIC",
        max_tokens=256,
    )
    assert result["decision"] == "ALLOW"


def test_excessive_token_request_blocked(control):
    result = control.evaluate(
        "Write a detailed report.",
        permission="STANDARD",
        data_sensitivity="PUBLIC",
        max_tokens=50000,
    )
    assert result["decision"] == "BLOCK"
    assert result["control"] == "LLM10"
