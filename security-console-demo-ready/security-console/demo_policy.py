import re
import sqlite3
from pathlib import Path

PERMISSION_RANK = {"LOW": 1, "STANDARD": 2, "PRIVILEGED": 3}
CLASS_RANK = {"PUBLIC": 1, "INTERNAL": 2, "CONFIDENTIAL": 2, "RESTRICTED": 3}
INJECTION_PATTERNS = [
    r"ignore .*policy", r"ignore .*instructions", r"you are now an administrator",
    r"bypass .*rules", r"do not redact", r"reveal .*system prompt",
]

def is_injection(prompt):
    return any(re.search(p, prompt.lower(), re.I) for p in INJECTION_PATTERNS)

def requested_fields(prompt):
    p = prompt.lower()
    mapping = {
        "name":["who is","name"], "job_title":["who is","job","role","title"],
        "department":["department","team"], "email":["email","contact"],
        "phone":["phone","contact"], "salary":["salary","pay","compensation"],
        "iban":["iban","bank account","bank"], "api_key":["api key","api credential","credentials","secret"],
    }
    result = [f for f, words in mapping.items() if any(w in p for w in words)]
    return list(dict.fromkeys(result)) or ["name","job_title"]

def evaluate(prompt, permission, db_path=None):
    db_path = Path(db_path or Path(__file__).parent / "demo-data" / "demo.db")
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT field_name, classification FROM data_classification WHERE table_name='employees'"
        ).fetchall()
    classes = dict(rows)
    fields = requested_fields(prompt)
    if is_injection(prompt):
        return "BLOCK"
    rank = PERMISSION_RANK[permission]
    visible = redacted = blocked = 0
    for f in fields:
        sensitivity = classes.get(f, "PUBLIC")
        required = CLASS_RANK[sensitivity]
        if rank >= required:
            visible += 1
        elif permission == "LOW" and sensitivity == "INTERNAL":
            redacted += 1
        elif permission == "STANDARD" and sensitivity == "RESTRICTED":
            redacted += 1
        else:
            blocked += 1
    if blocked and not visible and not redacted:
        return "BLOCK"
    if blocked or redacted:
        return "PARTIAL"
    return "ALLOW"
