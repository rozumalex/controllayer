from __future__ import annotations
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from data_bootstrap import ensure_database, DB_PATH
from prompt_guard import analyze_prompt

BASE = Path(__file__).parent
CONFIG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
PERMISSION_RANK = CONFIG["permissions"]

TABLE_KEYWORDS = {
    "clients": ["client","clients","kyc","relationship","aum","onboarding","beneficial owner","risk rating"],
    "accounts": ["account","accounts","balance","swift","iban","margin","portfolio value","credit exposure"],
    "trades": ["trade","trades","trading","pnl","notional","var","venue","instrument","desk"],
    "transactions": ["transaction","transactions","payment","payments","beneficiary","aml","fraud","wire","sepa"],
    "employees": ["employee","employees","staff","salary","bonus","manager","api token","clearance"],
    "research": ["research","report","reports","rating","target price","analyst","embargo","coverage"],
}
ID_PATTERNS = {
    "clients": r"\bCLT-\d{6}\b",
    "accounts": r"\bACC-\d{7}\b",
    "trades": r"\bTRD-\d{8}\b",
    "transactions": r"\bTXN-\d{9}\b",
    "employees": r"\bEMP-\d{5}\b",
    "research": r"\bRES-\d{7}\b",
}
DEFAULT_FIELDS = {
    "clients": ["client_id","client_name","client_type","country","sector","relationship_division","risk_rating","kyc_status"],
    "accounts": ["account_id","client_id","account_type","currency","jurisdiction","status","cash_balance_usd","portfolio_value_usd"],
    "trades": ["trade_id","client_id","asset_class","instrument","side","notional_usd","currency","status","pnl_usd"],
    "transactions": ["transaction_id","client_id","transaction_type","amount_usd","currency","origin_country","destination_country","status","aml_risk_score"],
    "employees": ["employee_id","name","division","title","office","clearance_level","base_salary_usd"],
    "research": ["research_id","title","research_type","asset_class","coverage_symbol","publication_date","audience","rating","summary"],
}

def connect():
    ensure_database()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def detect_table(prompt):
    p = prompt.lower()
    scores = {t: sum(1 for k in kws if k in p) for t,kws in TABLE_KEYWORDS.items()}
    for t,pat in ID_PATTERNS.items():
        if re.search(pat, prompt, re.I):
            scores[t] += 5
    return max(scores, key=scores.get) if max(scores.values()) > 0 else "clients"

def all_fields(conn, table):
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]

def catalog(conn):
    rows = conn.execute("SELECT table_name,field_name,sensitivity FROM data_catalog").fetchall()
    return {(r["table_name"],r["field_name"]):r["sensitivity"] for r in rows}

def requested_fields(prompt, table, fields):
    p = prompt.lower()
    synonyms = {
        "risk_rating":["risk rating"], "kyc_status":["kyc"], "sanctions_screening":["sanctions"],
        "aum_usd_mn":["aum","assets under management"], "credit_limit_usd_mn":["credit limit"],
        "tax_id_demo":["tax id"], "beneficial_owner":["beneficial owner"],
        "cash_balance_usd":["cash balance","balance"], "credit_exposure_usd":["credit exposure"],
        "margin_requirement_usd":["margin"], "portfolio_value_usd":["portfolio value"],
        "iban_or_local_account_demo":["iban","bank account"], "notional_usd":["notional"],
        "pnl_usd":["pnl","profit","loss"], "var_1d_usd":["var","value at risk"],
        "aml_risk_score":["aml score","aml risk"], "fraud_score":["fraud score"],
        "beneficiary_name":["beneficiary"], "beneficiary_account_demo":["beneficiary account"],
        "investigation_notes":["investigation notes","case notes"], "base_salary_usd":["salary","base salary"],
        "bonus_usd":["bonus"], "api_token_demo":["api token","token","secret"],
        "clearance_level":["clearance"], "performance_rating":["performance"],
        "target_price_demo":["target price"], "internal_draft_notes":["draft notes","internal notes"],
        "embargo_until":["embargo"], "rating":["rating"], "summary":["summary"]
    }
    selected = []
    for field in fields:
        label = field.replace("_"," ")
        if label in p or any(word in p for word in synonyms.get(field,[])):
            selected.append(field)
    if any(x in p for x in ["everything","all fields","all data","dump all"]):
        return fields
    return selected or [f for f in DEFAULT_FIELDS[table] if f in fields]

def filters_for(prompt, table):
    p = prompt.lower()
    clauses, params = [], []
    matches = re.findall(ID_PATTERNS[table], prompt, re.I)
    if matches:
        idcol = {
            "clients":"client_id","accounts":"account_id","trades":"trade_id",
            "transactions":"transaction_id","employees":"employee_id","research":"research_id"
        }[table]
        clauses.append(f"{idcol} = ?")
        params.append(matches[0].upper())

    if table == "clients":
        if "high risk" in p:
            clauses.append("risk_rating = 'HIGH'")
        if "pending kyc" in p or "kyc pending" in p:
            clauses.append("kyc_status = 'PENDING_REVIEW'")
    elif table == "transactions":
        if "high aml" in p:
            clauses.append("CAST(aml_risk_score AS REAL) >= 70")
        if "high fraud" in p:
            clauses.append("CAST(fraud_score AS REAL) >= 70")
        m = re.search(r"(?:over|above|greater than)\s*\$?\s*([\d,.]+)\s*(m|million|k|thousand)?", p)
        if m:
            amount = float(m.group(1).replace(",",""))
            if m.group(2) in ("m","million"): amount *= 1_000_000
            if m.group(2) in ("k","thousand"): amount *= 1_000
            clauses.append("CAST(amount_usd AS REAL) > ?")
            params.append(amount)
    elif table == "trades":
        if "loss" in p or "negative pnl" in p:
            clauses.append("CAST(pnl_usd AS REAL) < 0")
        for ac in ["equities","rates","credit","fx","commodities"]:
            if ac in p:
                clauses.append("LOWER(asset_class) = ?")
                params.append(ac.lower())
                break
    elif table == "employees":
        if "privileged" in p:
            clauses.append("privileged_access = 'true'")
    elif table == "research":
        if "internal" in p:
            clauses.append("audience = 'INTERNAL_ONLY'")
    return clauses, params

def field_policy(permission, table, fields, cat):
    rank = PERMISSION_RANK[permission]
    visible, redacted, blocked = [], [], []
    for f in fields:
        s = cat.get((table,f),"INTERNAL")
        if s == "PUBLIC":
            visible.append(f)
        elif s == "INTERNAL":
            (visible if rank >= 2 else blocked).append(f)
        elif s == "CONFIDENTIAL":
            if rank >= 3: visible.append(f)
            elif rank == 2: redacted.append(f)
            else: blocked.append(f)
        elif s == "RESTRICTED":
            (visible if rank >= 3 else blocked).append(f)
    return visible, redacted, blocked

def strongest_sensitivity(table, fields, cat):
    order = {"PUBLIC":1,"INTERNAL":2,"CONFIDENTIAL":3,"RESTRICTED":4}
    levels = [cat.get((table,f),"INTERNAL") for f in fields]
    return max(levels, key=lambda x: order[x]) if levels else "PUBLIC"

def log(conn, identity, permission, prompt, dataset, decision, guard, rows, visible, redacted, blocked, reason, latency):
    conn.execute("""
        INSERT INTO security_logs
        (timestamp,identity,permission,prompt,dataset,decision,prompt_risk_score,injection_categories,
         detection_techniques,decoded_payloads,semantic_score,returned_rows,visible_fields,redacted_fields,
         blocked_fields,reason,latency_ms)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datetime.now(timezone.utc).isoformat(), identity, permission, prompt, dataset, decision,
        guard["risk_score"], ",".join(guard["categories"]), ",".join(guard["techniques"]),
        str(guard["decoded_payloads"]), guard["semantic_score"], rows, ",".join(visible),
        ",".join(redacted), ",".join(blocked), reason, latency
    ))
    conn.commit()

def execute(prompt, identity="judge-standard", permission="STANDARD", limit=25):
    started = time.perf_counter()
    with connect() as conn:
        table = detect_table(prompt)
        fields = all_fields(conn, table)
        selected = requested_fields(prompt, table, fields)
        cat = catalog(conn)
        target_sensitivity = strongest_sensitivity(table, selected, cat)

        guard = analyze_prompt(prompt, target_sensitivity)
        if guard["decision"] == "BLOCK":
            latency = round((time.perf_counter()-started)*1000,2)
            reason = "Prompt-injection guard blocked the request before database access."
            log(conn, identity, permission, prompt, table, "BLOCK", guard, 0, [], [], selected, reason, latency)
            return {
                "decision":"BLOCK", "dataset":table, "rows":[], "visible_fields":[],
                "redacted_fields":[], "blocked_fields":selected, "reason":reason,
                "latency_ms":latency, "guard":guard, "target_sensitivity":target_sensitivity
            }

        visible, redacted, blocked = field_policy(permission, table, selected, cat)
        if blocked and not visible and not redacted:
            latency = round((time.perf_counter()-started)*1000,2)
            reason = "Requested fields exceed current permission level."
            log(conn, identity, permission, prompt, table, "BLOCK", guard, 0, visible, redacted, blocked, reason, latency)
            return {
                "decision":"BLOCK", "dataset":table, "rows":[], "visible_fields":visible,
                "redacted_fields":redacted, "blocked_fields":blocked, "reason":reason,
                "latency_ms":latency, "guard":guard, "target_sensitivity":target_sensitivity
            }

        clauses, params = filters_for(prompt, table)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        safe_fields = ",".join([f'"{f}"' for f in selected])
        sql = f'SELECT {safe_fields} FROM "{table}"{where} LIMIT ?'
        raw = [dict(r) for r in conn.execute(sql, (*params, limit)).fetchall()]

        rendered = []
        for row in raw:
            out = {}
            for f in selected:
                if f in visible: out[f] = row.get(f)
                elif f in redacted: out[f] = "[REDACTED]"
                else: out[f] = "[DENIED]"
            rendered.append(out)

        decision = "REDACT" if (redacted or blocked or guard["decision"]=="WARN") else "ALLOW"
        latency = round((time.perf_counter()-started)*1000,2)
        reason = "Prompt and field-level sensitivity policies evaluated."
        log(conn, identity, permission, prompt, table, decision, guard, len(rendered), visible, redacted, blocked, reason, latency)

        return {
            "decision":decision, "dataset":table, "rows":rendered, "visible_fields":visible,
            "redacted_fields":redacted, "blocked_fields":blocked, "reason":reason,
            "latency_ms":latency, "guard":guard, "target_sensitivity":target_sensitivity
        }
