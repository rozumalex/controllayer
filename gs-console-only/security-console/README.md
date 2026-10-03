# AI Control Layer — Console Only

This package intentionally contains **no datasets**.

Put the previously generated banking CSVs into:

```text
security-console/
├── app.py
├── prompt_guard.py
├── demo_engine.py
├── data_bootstrap.py
├── config.yaml
├── signatures.yaml
├── pages/
│   └── 1_Security_Admin.py
└── demo-data/
    ├── clients.csv
    ├── accounts.csv
    ├── trades.csv
    ├── transactions.csv
    ├── employees.csv
    ├── research.csv
    ├── data_catalog.csv
    └── identity_profiles.csv   # optional
```

The console automatically creates `demo-data/demo.db` from the CSV files.

## What the Playground does

Judges type their own prompt.

The console:
1. detects the relevant dataset
2. determines requested fields
3. evaluates prompt-injection risk
4. evaluates current field sensitivity
5. applies LOW / STANDARD / PRIVILEGED access
6. returns ALLOW / REDACT / BLOCK
7. logs the entire decision

## Prompt-injection techniques implemented

- Unicode NFKC normalization
- zero-width/control-character cleanup
- URL decoding
- exact signature matching
- fuzzy matching with RapidFuzz
- Base64 decode-and-rescan
- hex decode-and-rescan
- structural role/instruction marker detection
- permission-escalation language detection
- optional local Ollama semantic classifier
- sensitivity-aware blocking threshold

The UI exposes the techniques and risk score so judges can see *why* a prompt was blocked.

## Security Admin

The second Streamlit page lets judges:
- inspect field classifications
- change PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED live
- rerun the same prompt and see different behavior
- inspect security logs
- inspect policy-change history

## Optional semantic guard

By default `semantic_guard.enabled` is false so the console works without Ollama.

To use a local semantic judge, edit `config.yaml`:

```yaml
semantic_guard:
  enabled: true
  provider: ollama
  url: http://127.0.0.1:11434
  model: llama3.2:3b
```

The deterministic layers continue working if the local model is unavailable.
