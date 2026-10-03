from pathlib import Path
import csv
import sqlite3
import yaml

BASE = Path(__file__).parent
CONFIG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
DATA_DIR = BASE / CONFIG["data"]["folder"]
DB_PATH = DATA_DIR / CONFIG["data"]["database"]

DATASETS = ["clients", "accounts", "trades", "transactions", "employees", "research"]
REQUIRED_FILES = [f"{name}.csv" for name in DATASETS] + ["data_catalog.csv"]

def dataset_status():
    DATA_DIR.mkdir(exist_ok=True)
    missing = [name for name in REQUIRED_FILES if not (DATA_DIR / name).exists()]
    return {"ready": not missing, "missing": missing, "data_dir": str(DATA_DIR), "db_exists": DB_PATH.exists()}

def _signature():
    sig = []
    for name in REQUIRED_FILES:
        p = DATA_DIR / name
        if p.exists():
            st = p.stat()
            sig.append((name, st.st_size, int(st.st_mtime)))
    return tuple(sorted(sig))

def _stored_signature(conn):
    try:
        return tuple(conn.execute(
            "SELECT filename,size,mtime FROM _dataset_signature ORDER BY filename"
        ).fetchall())
    except sqlite3.Error:
        return ()

def ensure_database(force=False):
    status = dataset_status()
    if not status["ready"]:
        raise FileNotFoundError("Missing dataset files: " + ", ".join(status["missing"]))

    current = _signature()
    rebuild = force or not DB_PATH.exists()

    if DB_PATH.exists() and not rebuild:
        with sqlite3.connect(DB_PATH) as conn:
            rebuild = _stored_signature(conn) != current

    if not rebuild:
        return DB_PATH

    if DB_PATH.exists():
        DB_PATH.unlink()

    with sqlite3.connect(DB_PATH) as conn:
        for dataset in DATASETS + ["data_catalog"]:
            path = DATA_DIR / f"{dataset}.csv"
            with path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                headers = next(reader)
                columns = ", ".join([f'"{h}" TEXT' for h in headers])
                conn.execute(f'CREATE TABLE "{dataset}" ({columns})')
                placeholders = ",".join(["?"] * len(headers))
                batch = []
                for row in reader:
                    batch.append(row)
                    if len(batch) >= 5000:
                        conn.executemany(f'INSERT INTO "{dataset}" VALUES ({placeholders})', batch)
                        batch.clear()
                if batch:
                    conn.executemany(f'INSERT INTO "{dataset}" VALUES ({placeholders})', batch)

        identity_path = DATA_DIR / "identity_profiles.csv"
        if identity_path.exists():
            with identity_path.open("r", encoding="utf-8", newline="") as f:
                reader = csv.reader(f)
                headers = next(reader)
                columns = ", ".join([f'"{h}" TEXT' for h in headers])
                conn.execute(f'CREATE TABLE identity_profiles ({columns})')
                placeholders = ",".join(["?"] * len(headers))
                conn.executemany(f'INSERT INTO identity_profiles VALUES ({placeholders})', reader)

        conn.execute("""
            CREATE TABLE security_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                identity TEXT,
                permission TEXT,
                prompt TEXT,
                dataset TEXT,
                decision TEXT,
                prompt_risk_score INTEGER,
                injection_categories TEXT,
                detection_techniques TEXT,
                decoded_payloads TEXT,
                semantic_score REAL,
                returned_rows INTEGER,
                visible_fields TEXT,
                redacted_fields TEXT,
                blocked_fields TEXT,
                reason TEXT,
                latency_ms REAL
            )
        """)
        conn.execute("""
            CREATE TABLE policy_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                table_name TEXT,
                field_name TEXT,
                old_sensitivity TEXT,
                new_sensitivity TEXT
            )
        """)
        conn.execute("CREATE TABLE _dataset_signature(filename TEXT, size INTEGER, mtime INTEGER)")
        conn.executemany("INSERT INTO _dataset_signature VALUES (?,?,?)", current)
        conn.commit()

    return DB_PATH
