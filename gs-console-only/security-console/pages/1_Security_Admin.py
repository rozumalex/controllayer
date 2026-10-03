from datetime import datetime, timezone
import sqlite3
import streamlit as st

from data_bootstrap import dataset_status, ensure_database, DB_PATH

st.set_page_config(page_title="Security Admin", page_icon="⚙️", layout="wide")
st.title("⚙️ Security Admin")

status = dataset_status()
if not status["ready"]:
    st.error("Datasets are missing. Install them in `demo-data/` first.")
    st.stop()

ensure_database()

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

policy_tab, logs_tab, posture_tab = st.tabs(["Sensitivity Policy", "Security Logs", "Posture"])

with policy_tab:
    with connect() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT DISTINCT table_name FROM data_catalog ORDER BY table_name"
        ).fetchall()]

    table = st.selectbox("Dataset", tables)

    with connect() as conn:
        fields = [dict(r) for r in conn.execute(
            "SELECT field_name,sensitivity,rationale FROM data_catalog WHERE table_name=? ORDER BY field_name",
            (table,)
        ).fetchall()]

    st.dataframe(fields, use_container_width=True, hide_index=True)

    st.subheader("Live policy change")
    field = st.selectbox("Field", [r["field_name"] for r in fields])
    current = next(r["sensitivity"] for r in fields if r["field_name"] == field)
    levels = ["PUBLIC","INTERNAL","CONFIDENTIAL","RESTRICTED"]
    new_level = st.selectbox("Sensitivity", levels, index=levels.index(current))

    if st.button("Apply policy change", type="primary"):
        with connect() as conn:
            conn.execute(
                "UPDATE data_catalog SET sensitivity=? WHERE table_name=? AND field_name=?",
                (new_level, table, field)
            )
            conn.execute(
                "INSERT INTO policy_changes(timestamp,table_name,field_name,old_sensitivity,new_sensitivity) VALUES(?,?,?,?,?)",
                (datetime.now(timezone.utc).isoformat(), table, field, current, new_level)
            )
            conn.commit()
        st.success(f"{table}.{field}: {current} → {new_level}")
        st.rerun()

    st.caption("Change a field, then rerun the same prompt in Playground. The decision changes immediately.")

with logs_tab:
    limit = st.selectbox("Show latest", [25,50,100,250], index=1)

    with connect() as conn:
        logs = [dict(r) for r in conn.execute("""
            SELECT timestamp,identity,permission,dataset,decision,prompt_risk_score,
                   injection_categories,detection_techniques,returned_rows,
                   visible_fields,redacted_fields,blocked_fields,prompt,reason,latency_ms
            FROM security_logs
            ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()]

    if logs:
        st.dataframe(logs, use_container_width=True, hide_index=True)
    else:
        st.info("No prompt events yet.")

    if st.button("Clear prompt logs"):
        with connect() as conn:
            conn.execute("DELETE FROM security_logs")
            conn.commit()
        st.rerun()

with posture_tab:
    with connect() as conn:
        decisions = [dict(r) for r in conn.execute("""
            SELECT decision, COUNT(*) AS count
            FROM security_logs GROUP BY decision
        """).fetchall()]
        changes = [dict(r) for r in conn.execute("""
            SELECT timestamp,table_name,field_name,old_sensitivity,new_sensitivity
            FROM policy_changes ORDER BY id DESC LIMIT 50
        """).fetchall()]

    st.subheader("Decisions")
    if decisions:
        st.dataframe(decisions, use_container_width=True, hide_index=True)
    else:
        st.write("No events yet.")

    st.subheader("Recent policy changes")
    if changes:
        st.dataframe(changes, use_container_width=True, hide_index=True)
    else:
        st.write("No policy changes yet.")
