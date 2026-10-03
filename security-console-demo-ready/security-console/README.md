# AI Control Layer — Demo-Ready Security Console

This version includes the synthetic SQLite database and can run the case study without the real team infrastructure.

## Repository structure

```text
security-console-demo-ready/
├── app.py
├── client.py
├── mock_server.py
├── attacks.yaml
├── requirements.txt
├── demo-data/
│   ├── demo.db
│   ├── employees.csv
│   ├── data_classification.csv
│   ├── permission_levels.csv
│   ├── classification_policy.yaml
│   └── case_study*.csv
└── tests/
```

## Main demo

Open **Case Study Playground** and test the same prompt under LOW, STANDARD and PRIVILEGED permissions.

Expected headline behavior:

- CASE-01 normal lookup: LOW = PARTIAL; STANDARD/PRIVILEGED = ALLOW
- CASE-02 sensitive data: LOW = BLOCK; STANDARD = PARTIAL; PRIVILEGED = ALLOW
- CASE-03 policy bypass: everyone = BLOCK
- CASE-03B legitimate restricted request: PRIVILEGED = ALLOW

## Important architecture point

The local database evaluator is for a deterministic hackathon demo. The `External Gateway` tab keeps the original adapter so the UI can later point at the team's real Control Layer without redesigning the console.

All data is synthetic.
