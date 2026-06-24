import sqlite3
import hashlib
import os
import datetime
import functools
from config import DATABASE_FILE


def get_connection():
    os.makedirs(os.path.dirname(DATABASE_FILE), exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT UNIQUE,
            entity      TEXT NOT NULL,
            bank        TEXT NOT NULL,
            date        TEXT NOT NULL,
            narration   TEXT,
            debit       REAL DEFAULT 0,
            credit      REAL DEFAULT 0,
            balance     REAL,
            category    TEXT DEFAULT 'Uncategorized',
            final_group TEXT,
            group_name  TEXT,
            main_group  TEXT,
            source_file TEXT,
            loaded_at   TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS processed_files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filepath_key TEXT UNIQUE,
            filename     TEXT,
            entity       TEXT,
            bank         TEXT,
            row_count    INTEGER,
            processed_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)

    c.executescript("""
        CREATE INDEX IF NOT EXISTS idx_txn_entity   ON transactions(entity);
        CREATE INDEX IF NOT EXISTS idx_txn_bank     ON transactions(bank);
        CREATE INDEX IF NOT EXISTS idx_txn_date     ON transactions(date);
        CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(final_group);
        CREATE INDEX IF NOT EXISTS idx_txn_entity_bank_date ON transactions(entity, bank, date);
    """)

    conn.commit()

    # Migration: add manually_overridden column (safe no-op if already exists)
    try:
        conn.execute("""
            ALTER TABLE transactions
            ADD COLUMN manually_overridden INTEGER DEFAULT 0
        """)
        conn.commit()
    except Exception:
        pass  # Already exists

    # Migration: add financial_year column
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN financial_year TEXT")
        conn.commit()
    except Exception:
        pass  # Already exists

    # Backfill financial_year for any rows that don't have it yet
    conn.execute("""
        UPDATE transactions
        SET financial_year = CASE
            WHEN CAST(strftime('%m', date) AS INTEGER) >= 4
            THEN 'FY' || substr(strftime('%Y', date), 3, 2)
                     || substr(strftime('%Y', date(date, '+1 year')), 3, 2)
            ELSE 'FY' || substr(strftime('%Y', date(date, '-1 year')), 3, 2)
                     || substr(strftime('%Y', date), 3, 2)
        END
        WHERE financial_year IS NULL
    """)
    conn.commit()

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_txn_fy ON transactions(financial_year)"
        )
        conn.commit()
    except Exception:
        pass

    # Audit trail for manual category changes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS category_audit (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id  INTEGER NOT NULL,
            bank            TEXT,
            entity          TEXT,
            narration       TEXT,
            old_category    TEXT,
            new_category    TEXT,
            old_group       TEXT,
            new_group       TEXT,
            old_main_group  TEXT,
            new_main_group  TEXT,
            changed_at      TEXT DEFAULT (datetime('now','localtime')),
            change_type     TEXT DEFAULT 'manual'
        )
    """)
    conn.commit()

    # Investment register table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS investment_register (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            scheme_name   TEXT NOT NULL,
            scheme_type   TEXT NOT NULL,
            entity        TEXT NOT NULL,
            opening_value REAL DEFAULT 0,
            opening_date  TEXT DEFAULT '2026-04-01',
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    existing = conn.execute(
        "SELECT COUNT(*) FROM investment_register").fetchone()[0]
    if existing == 0:
        default_schemes = [
            ("FD-1",        "FD", "Stores",   0, "2026-04-01"),
            ("FD-2",        "FD", "Stores",   0, "2026-04-01"),
            ("FD-3",        "FD", "Stores",   0, "2026-04-01"),
            ("FD-4",        "FD", "Stores",   0, "2026-04-01"),
            ("MF-Scheme-1", "MF", "Ventures", 0, "2026-04-01"),
            ("MF-Scheme-2", "MF", "Ventures", 0, "2026-04-01"),
            ("MF-Scheme-3", "MF", "Ventures", 0, "2026-04-01"),
        ]
        conn.executemany("""
            INSERT INTO investment_register
            (scheme_name, scheme_type, entity, opening_value, opening_date)
            VALUES (?,?,?,?,?)
        """, default_schemes)
    conn.commit()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cash_register (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            value      REAL    NOT NULL DEFAULT 0,
            updated_at TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS upload_trail (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            filename       TEXT NOT NULL,
            entity         TEXT,
            bank           TEXT,
            financial_year TEXT,
            rows_inserted  INTEGER DEFAULT 0,
            date_from      TEXT,
            date_to        TEXT,
            uploaded_at    TEXT DEFAULT (datetime('now','localtime')),
            deleted        INTEGER DEFAULT 0
        )
    """)
    conn.commit()

    # A2 — Investment transaction tagging
    conn.execute("""
        CREATE TABLE IF NOT EXISTS investment_txn_mapping (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_id  INTEGER NOT NULL UNIQUE,
            scheme_name     TEXT,
            scheme_number   TEXT,
            scheme_type     TEXT,
            notes           TEXT,
            tagged_at       TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (transaction_id) REFERENCES transactions(id)
        )
    """)
    conn.commit()

    # A1 — One-time: protect all FY2526 imported rows from keyword reload
    already_done = conn.execute("""
        SELECT COUNT(*) FROM transactions
        WHERE financial_year='FY2526'
        AND manually_overridden=1
        AND source_file NOT IN ('manual_entry','ob_fix')
    """).fetchone()[0]

    if already_done == 0:
        result = conn.execute("""
            UPDATE transactions
            SET manually_overridden=1
            WHERE financial_year='FY2526'
            AND COALESCE(manually_overridden,0)=0
            AND final_group != 'OPENING BALANCE'
        """)
        conn.commit()
        if result.rowcount:
            print(f"[DB] Protected {result.rowcount:,} FY2526 rows from reload")

    # A4 — Compound indexes for common filter patterns
    _indexes = [
        "CREATE INDEX IF NOT EXISTS idx_main_group  ON transactions(main_group)",
        "CREATE INDEX IF NOT EXISTS idx_fy_fg       ON transactions(financial_year, final_group)",
        "CREATE INDEX IF NOT EXISTS idx_fy_entity   ON transactions(financial_year, entity)",
        "CREATE INDEX IF NOT EXISTS idx_fy_bank     ON transactions(financial_year, bank)",
        "CREATE INDEX IF NOT EXISTS idx_fy_date     ON transactions(financial_year, date)",
        "CREATE INDEX IF NOT EXISTS idx_mo_override ON transactions(manually_overridden)",
    ]
    for _sql in _indexes:
        try:
            conn.execute(_sql)
        except Exception:
            pass
    conn.commit()

    conn.close()
    print("[DB] Database initialized.")


def _date_to_fy(date_str):
    """Return 'FY2526' style string for any YYYY-MM-DD date."""
    try:
        year  = int(date_str[:4])
        month = int(date_str[5:7])
        if month >= 4:
            return f"FY{str(year)[2:]}{str(year + 1)[2:]}"
        return f"FY{str(year - 1)[2:]}{str(year)[2:]}"
    except Exception:
        return None


def make_fingerprint(entity, bank, date, narration, debit, credit):
    raw = f"{entity}|{bank}|{date}|{narration}|{debit}|{credit}"
    return hashlib.md5(raw.encode()).hexdigest()


def insert_transactions(rows):
    conn = get_connection()
    c = conn.cursor()
    inserted = 0
    skipped  = 0

    for row in rows:
        # Skip duplicate Opening Balance rows — keep only first per bank
        if row.get("final_group") == "OPENING BALANCE":
            existing = c.execute("""
                SELECT COUNT(*) FROM transactions
                WHERE bank = ? AND final_group = 'OPENING BALANCE'
            """, [row["bank"]]).fetchone()[0]
            if existing > 0:
                skipped += 1
                print(f"[OB] Skipping duplicate OB for {row['bank']}")
                continue

        fp = make_fingerprint(
            row["entity"], row["bank"], row["date"],
            row["narration"], row["debit"], row["credit"]
        )
        fy = _date_to_fy(row["date"])
        try:
            c.execute("""
                INSERT INTO transactions
                (fingerprint, entity, bank, date, narration,
                 debit, credit, balance, category, final_group,
                 group_name, main_group, source_file, manually_overridden,
                 financial_year)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fp,
                row["entity"], row["bank"], row["date"], row["narration"],
                row["debit"], row["credit"], row.get("balance"),
                row.get("category")    or "Uncategorized",
                row.get("final_group") or "Uncategorized",
                row.get("group_name")  or "",
                row.get("main_group")  or "",
                row.get("source_file"),
                int(row.get("manually_overridden", 0)),
                fy
            ))
            inserted += 1
        except Exception:
            skipped += 1

    conn.commit()
    conn.close()
    return inserted, skipped


def mark_file_processed(filepath, entity, bank, row_count):
    """Composite key bank+filename so same filename in different accounts doesn't collide."""
    conn = get_connection()
    filename = os.path.basename(filepath)
    filepath_key = f"{bank}::{filename}"
    try:
        conn.execute("""
            INSERT OR REPLACE INTO processed_files (filepath_key, filename, entity, bank, row_count)
            VALUES (?,?,?,?,?)
        """, (filepath_key, filename, entity, bank, row_count))
        conn.commit()
    finally:
        conn.close()


def log_upload(filename, entity, bank, financial_year,
               rows_inserted, date_from, date_to):
    conn = get_connection()
    conn.execute("""
        INSERT INTO upload_trail
        (filename, entity, bank, financial_year,
         rows_inserted, date_from, date_to)
        VALUES (?,?,?,?,?,?,?)
    """, [filename, entity, bank, financial_year,
          rows_inserted, date_from, date_to])
    conn.commit()
    trail_id = conn.execute(
        "SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return trail_id


def get_upload_trail():
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, filename, entity, bank, financial_year,
               rows_inserted, date_from, date_to,
               uploaded_at, deleted
        FROM upload_trail
        WHERE deleted = 0
        ORDER BY uploaded_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_upload(trail_id):
    """
    Deletes all transactions from a specific upload.
    Matches by source_file, entity, bank, and date range.
    Marks trail record as deleted.
    Returns count of deleted rows.
    """
    conn = get_connection()
    trail = conn.execute(
        "SELECT * FROM upload_trail WHERE id=?",
        [trail_id]).fetchone()
    if not trail:
        conn.close()
        return 0
    trail = dict(trail)
    result = conn.execute("""
        DELETE FROM transactions
        WHERE source_file = ?
        AND entity = ?
        AND bank = ?
        AND date BETWEEN ? AND ?
        AND COALESCE(manually_overridden, 0) = 0
    """, [trail["filename"], trail["entity"], trail["bank"],
          trail["date_from"], trail["date_to"]])
    deleted_rows = result.rowcount
    conn.execute(
        "UPDATE upload_trail SET deleted=1 WHERE id=?",
        [trail_id])
    conn.commit()
    conn.close()
    return deleted_rows


def get_all_transactions(entity=None, bank=None, month=None, category=None,
                         date_from=None, date_to=None, financial_year=None):
    conn = get_connection()
    query = """
        SELECT id, entity, bank, date, narration,
               debit, credit, balance,
               category, final_group, group_name, main_group,
               source_file, loaded_at,
               COALESCE(manually_overridden, 0) as manually_overridden
        FROM transactions WHERE 1=1
    """
    params = []
    if financial_year:
        query += " AND financial_year=?"
        params.append(financial_year)
    if entity and entity != "All":
        query += " AND entity=?"
        params.append(entity)
    if bank and bank != "All":
        query += " AND bank=?"
        params.append(bank)
    if date_from and date_to:
        query += " AND date >= ? AND date <= ?"
        params.extend([str(date_from), str(date_to)])
    elif month and month != "All":
        query += " AND strftime('%Y-%m', date)=?"
        params.append(month)
    if category and category != "All":
        query += " AND final_group=?"
        params.append(category)
    query += " ORDER BY date DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_uncategorized(financial_year=None):
    conn = get_connection()
    fy_clause = " AND financial_year=?" if financial_year else ""
    fy_param  = [financial_year]        if financial_year else []
    rows = conn.execute(f"""
        SELECT narration, entity, COUNT(*) as count, SUM(debit) as total_debit
        FROM transactions
        WHERE (category='Uncategorized' OR final_group IS NULL OR final_group='')
        {fy_clause}
        GROUP BY narration, entity
        ORDER BY count DESC
    """, fy_param).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def manual_categorize(transaction_ids, final_group, group_name, main_group):
    """
    Manually assign category to a list of transaction IDs.
    Writes an audit row for each change.
    Sets manually_overridden=1 so reload_categories() never touches these rows.
    Returns count of updated rows.
    """
    if not transaction_ids:
        return 0
    conn = get_connection()
    updated = 0

    for txn_id in [int(i) for i in transaction_ids]:
        current = conn.execute("""
            SELECT bank, entity, narration,
                   final_group, group_name, main_group
            FROM transactions WHERE id=?
        """, [txn_id]).fetchone()
        if not current:
            continue

        # Audit log — capture before state
        conn.execute("""
            INSERT INTO category_audit
            (transaction_id, bank, entity, narration,
             old_category, new_category,
             old_group,    new_group,
             old_main_group, new_main_group,
             change_type)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            txn_id,
            current["bank"], current["entity"], current["narration"],
            current["final_group"], final_group,
            current["group_name"],  group_name,
            current["main_group"],  main_group,
            "manual"
        ))

        conn.execute("""
            UPDATE transactions
            SET final_group         = ?,
                group_name          = ?,
                main_group          = ?,
                category            = ?,
                manually_overridden = 1
            WHERE id = ?
        """, [final_group, group_name, main_group, final_group, txn_id])

        updated += 1

    conn.commit()
    conn.close()
    return updated


def get_all_categories():
    """
    Returns all distinct final_group values from DB transactions,
    sorted alphabetically. Excludes system categories.
    """
    conn = get_connection()
    rows = conn.execute("""
        SELECT DISTINCT
            final_group,
            MAX(group_name) as group_name,
            MAX(main_group) as main_group
        FROM transactions
        WHERE final_group IS NOT NULL
          AND TRIM(final_group) != ''
          AND final_group NOT IN ('Uncategorized', 'OPENING BALANCE')
        GROUP BY final_group
        ORDER BY final_group ASC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revert_manual_category(transaction_id):
    """
    Revert a transaction to its previous category using the audit trail.
    Clears manually_overridden flag so the row is visible to reload_categories() again.
    Returns True on success, False if no audit history exists.
    """
    conn = get_connection()

    prev = conn.execute("""
        SELECT old_category, old_group, old_main_group
        FROM category_audit
        WHERE transaction_id = ?
        ORDER BY changed_at DESC
        LIMIT 1
    """, [int(transaction_id)]).fetchone()

    if not prev:
        conn.close()
        return False

    old_cat  = prev["old_category"]   or "Uncategorized"
    old_grp  = prev["old_group"]      or ""
    old_main = prev["old_main_group"] or ""

    # Log the revert itself
    conn.execute("""
        INSERT INTO category_audit
        (transaction_id, old_category, new_category, change_type)
        VALUES (?, (SELECT final_group FROM transactions WHERE id=?), ?, 'revert')
    """, [int(transaction_id), int(transaction_id), old_cat])

    conn.execute("""
        UPDATE transactions
        SET final_group         = ?,
            group_name          = ?,
            main_group          = ?,
            category            = ?,
            manually_overridden = 0
        WHERE id = ?
    """, [old_cat, old_grp, old_main, old_cat, int(transaction_id)])

    conn.commit()
    conn.close()
    return True


def get_category_audit(transaction_id=None, limit=50):
    """Return audit log rows, optionally filtered to one transaction."""
    conn = get_connection()
    if transaction_id:
        rows = conn.execute("""
            SELECT * FROM category_audit
            WHERE transaction_id = ?
            ORDER BY changed_at DESC
        """, [int(transaction_id)]).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM category_audit
            ORDER BY changed_at DESC LIMIT ?
        """, [limit]).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_summary(entity=None, bank=None, month=None, date_from=None, date_to=None,
                financial_year=None):
    conn = get_connection()
    filters = "WHERE 1=1"
    params = []

    if financial_year:
        filters += " AND financial_year=?"
        params.append(financial_year)
    if entity and entity != "All":
        filters += " AND entity=?"
        params.append(entity)
    if bank and bank != "All":
        filters += " AND bank=?"
        params.append(bank)
    if date_from and date_to:
        filters += " AND date >= ? AND date <= ?"
        params.extend([str(date_from), str(date_to)])
    elif month and month != "All":
        filters += " AND strftime('%Y-%m', date)=?"
        params.append(month)

    totals = conn.execute(f"""
        SELECT
            ROUND(SUM(credit),2) as total_inflow,
            ROUND(SUM(debit),2)  as total_outflow,
            ROUND(SUM(credit)-SUM(debit),2) as net_flow
        FROM transactions {filters}
    """, params).fetchone()

    by_entity = conn.execute(f"""
        SELECT entity,
            ROUND(SUM(credit),2) as inflow,
            ROUND(SUM(debit),2)  as outflow
        FROM transactions {filters}
        GROUP BY entity
    """, params).fetchall()

    by_category = conn.execute(f"""
        SELECT final_group, group_name, main_group,
            ROUND(SUM(debit),2) as total
        FROM transactions {filters} AND debit > 0
        GROUP BY final_group
        ORDER BY total DESC
    """, params).fetchall()

    by_month = conn.execute(f"""
        SELECT strftime('%Y-%m', date) as month,
            ROUND(SUM(credit),2) as inflow,
            ROUND(SUM(debit),2)  as outflow
        FROM transactions {filters}
        GROUP BY month ORDER BY month
    """, params).fetchall()

    conn.close()
    return {
        "totals":      dict(totals) if totals else {},
        "by_entity":   [dict(r) for r in by_entity],
        "by_category": [dict(r) for r in by_category],
        "by_month":    [dict(r) for r in by_month]
    }


def get_large_debits(threshold, financial_year=None):
    conn = get_connection()
    fy_clause = " AND financial_year=?" if financial_year else ""
    fy_param  = [financial_year]        if financial_year else []
    rows = conn.execute(f"""
        SELECT entity, bank, date, narration, debit, final_group
        FROM transactions
        WHERE debit >= ? {fy_clause}
        ORDER BY debit DESC LIMIT 50
    """, [threshold] + fy_param).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_missing_statements(financial_year=None):
    from config import ENTITIES

    today         = datetime.date.today()
    current_month = today.strftime("%Y-%m")
    conn          = get_connection()
    results       = []

    fy_clause = " AND financial_year=?" if financial_year else ""
    fy_param  = [financial_year]        if financial_year else []

    for entity, banks in ENTITIES.items():
        for bank in banks:
            row = conn.execute(f"""
                SELECT MAX(date) as last_date, COUNT(*) as total_rows
                FROM transactions
                WHERE bank = ?
                AND final_group != 'OPENING BALANCE'
                {fy_clause}
            """, [bank] + fy_param).fetchone()

            last_date  = row["last_date"]  if row else None
            total_rows = row["total_rows"] if row else 0

            if last_date:
                last_dt     = datetime.date.fromisoformat(last_date)
                days_ago    = (today - last_dt).days
                has_current = last_dt.strftime("%Y-%m") == current_month
            else:
                last_dt     = None
                days_ago    = 999
                has_current = False

            if has_current:
                status = "ok"
            elif days_ago <= 40:
                status = "warning"
            else:
                status = "missing"

            results.append({
                "entity":      entity,
                "bank":        bank,
                "last_date":   last_date or "Never loaded",
                "days_ago":    days_ago,
                "has_current": has_current,
                "total_rows":  total_rows,
                "status":      status,
            })

    conn.close()
    return results


def get_available_months(financial_year=None):
    """Lightweight distinct month list for sidebar dropdown."""
    conn      = get_connection()
    fy_clause = ""
    fy_params = []
    if financial_year and financial_year != "All":
        fy_clause = "AND financial_year=?"
        fy_params = [financial_year]
    rows = conn.execute(f"""
        SELECT DISTINCT strftime('%Y-%m', date) as month
        FROM transactions
        WHERE 1=1 {fy_clause}
        ORDER BY month DESC
    """, fy_params).fetchall()
    conn.close()
    return [r["month"] for r in rows if r["month"]]


def get_transaction_count(entity=None, bank=None, month=None, financial_year=None):
    """Count only — never loads rows into memory."""
    conn   = get_connection()
    query  = "SELECT COUNT(*) as cnt FROM transactions WHERE final_group != 'OPENING BALANCE'"
    params = []
    if entity and entity != "All":
        query += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        query += " AND bank=?"; params.append(bank)
    if month and month != "All":
        query += " AND strftime('%Y-%m', date)=?"; params.append(month)
    if financial_year and financial_year != "All":
        query += " AND financial_year=?"; params.append(financial_year)
    result = conn.execute(query, params).fetchone()
    conn.close()
    return result["cnt"] if result else 0


def get_closing_balance(entity=None, bank=None, month=None, financial_year=None,
                        date_from=None, date_to=None):
    """
    Get closing balance per bank using a single SQL query — never loads all rows.
    Returns {"by_bank": {bank: balance}, "dates": {bank: date}, "total": float}.
    """
    conn   = get_connection()
    params = []
    where  = "WHERE final_group != 'OPENING BALANCE' AND balance IS NOT NULL"
    if entity and entity != "All":
        where += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        where += " AND bank=?"; params.append(bank)
    if date_from and date_to:
        where += " AND date >= ? AND date <= ?"; params.extend([str(date_from), str(date_to)])
    elif month and month != "All":
        where += " AND strftime('%Y-%m', date)=?"; params.append(month)
    if financial_year and financial_year != "All":
        where += " AND financial_year=?"; params.append(financial_year)

    # ORDER BY date DESC, id DESC so the first row per bank is the latest transaction
    rows = conn.execute(f"""
        SELECT bank, balance, date
        FROM transactions
        {where}
        ORDER BY bank, date DESC, id DESC
    """, params).fetchall()

    seen_banks = set()
    by_bank    = {}
    dates      = {}
    for r in rows:
        bk = r["bank"]
        if bk not in seen_banks:
            seen_banks.add(bk)
            by_bank[bk] = r["balance"]
            dates[bk]   = r["date"]

    # Fallback: banks with NO transactions (e.g. SBI-0211 with only an OB row)
    # use their OPENING BALANCE row balance as closing balance
    ob_params = []
    ob_where  = "WHERE final_group = 'OPENING BALANCE'"
    if entity and entity != "All":
        ob_where += " AND entity=?"; ob_params.append(entity)
    if bank and bank != "All":
        ob_where += " AND bank=?"; ob_params.append(bank)
    if financial_year and financial_year != "All":
        ob_where += " AND financial_year=?"; ob_params.append(financial_year)

    all_banks = conn.execute(f"""
        SELECT DISTINCT bank FROM transactions {ob_where}
    """, ob_params).fetchall()

    for b in all_banks:
        bk = b["bank"]
        if bk not in by_bank:
            ob = conn.execute("""
                SELECT balance FROM transactions
                WHERE bank=? AND final_group='OPENING BALANCE'
                ORDER BY date DESC LIMIT 1
            """, [bk]).fetchone()
            if ob and ob["balance"] is not None:
                by_bank[bk] = ob["balance"]
                dates[bk]   = None

    total = sum(v for v in by_bank.values() if v is not None)
    conn.close()
    return {"by_bank": by_bank, "dates": dates, "total": total}


def get_paginated_transactions(entity=None, bank=None, month=None,
                               category=None, financial_year=None,
                               search=None, main_group=None,
                               manually_overridden_only=False,
                               date_from=None, date_to=None,
                               page=1, page_size=500):
    """
    Returns one page of transactions (OPENING BALANCE rows excluded).
    Also returns total_count, total_pages for pagination display.
    """
    conn   = get_connection()
    where  = "WHERE final_group != 'OPENING BALANCE'"
    params = []

    if entity and entity != "All":
        where += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        where += " AND bank=?"; params.append(bank)
    if date_from and date_to:
        where += " AND date >= ? AND date <= ?"; params.extend([str(date_from), str(date_to)])
    elif month and month != "All":
        where += " AND strftime('%Y-%m', date)=?"; params.append(month)
    if category and category != "All":
        where += " AND final_group=?"; params.append(category)
    if main_group and main_group != "All":
        where += " AND main_group=?"; params.append(main_group)
    if financial_year and financial_year != "All":
        where += " AND financial_year=?"; params.append(financial_year)
    if search:
        where += " AND narration LIKE ?"; params.append(f"%{search}%")
    if manually_overridden_only:
        where += " AND COALESCE(manually_overridden, 0)=1"

    total  = conn.execute(f"SELECT COUNT(*) FROM transactions {where}", params).fetchone()[0]
    offset = (page - 1) * page_size
    rows   = conn.execute(
        f"SELECT id, entity, bank, date, narration, debit, credit, balance,"
        f"       category, final_group, group_name, main_group,"
        f"       source_file, loaded_at,"
        f"       COALESCE(manually_overridden, 0) as manually_overridden"
        f" FROM transactions {where}"
        f" ORDER BY date DESC, id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    ).fetchall()

    conn.close()
    return {
        "rows":        [dict(r) for r in rows],
        "total_count": total,
        "page":        page,
        "page_size":   page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


def reload_categories():
    """Reset ALL categories to Uncategorized, then re-apply all keywords from scratch."""
    from categorizer import categorize_narration, load_keywords

    # Step 1: Load keywords — abort if none loaded
    keywords = load_keywords()
    if not keywords:
        print("[RELOAD] ERROR: 0 keywords loaded — aborting. Check keywords_master.xlsx")
        return 0

    conn = get_connection()

    # Step 2: Reset only non-manual, non-FY2526-protected rows
    # manually_overridden=1 covers: FY2526 imported rows, manual overrides, OB rows
    conn.execute("""
        UPDATE transactions
        SET category      = 'Uncategorized',
            final_group   = 'Uncategorized',
            group_name    = '',
            main_group    = ''
        WHERE final_group != 'OPENING BALANCE'
          AND COALESCE(manually_overridden, 0) = 0
    """)
    conn.commit()
    print(f"[RELOAD] Reset complete. Re-applying {len(keywords)} keyword rules...")

    # Step 3: Fetch only rows that were reset (not manually overridden)
    rows = conn.execute("""
        SELECT id, narration, entity, debit, credit
        FROM transactions
        WHERE final_group = 'Uncategorized'
          AND COALESCE(manually_overridden, 0) = 0
    """).fetchall()

    # Step 4: Match and update in batches of 500
    updated = 0
    batch   = []
    for row in rows:
        result = categorize_narration(
            row["narration"], row["entity"], keywords,
            debit=float(row["debit"]  or 0),
            credit=float(row["credit"] or 0),
        )
        if result:
            batch.append((
                result["final_group"],
                result["final_group"],
                result.get("group_name", ""),
                result.get("main_group", ""),
                row["id"]
            ))
            updated += 1
        if len(batch) >= 500:
            conn.executemany("""
                UPDATE transactions
                SET category=?, final_group=?, group_name=?, main_group=?
                WHERE id=?
            """, batch)
            conn.commit()
            batch = []

    # Commit remaining rows
    if batch:
        conn.executemany("""
            UPDATE transactions
            SET category=?, final_group=?, group_name=?, main_group=?
            WHERE id=?
        """, batch)
        conn.commit()

    conn.close()
    print(f"[RELOAD] Done — {updated} rows categorized, "
          f"{len(rows) - updated} remain Uncategorized")
    return updated


def get_cashflow(entity=None, date_from=None, date_to=None):
    """
    Returns cash flow data for a single entity and date range.

    opening_balances : {bank_id: float}  — balance from earliest txn in period per account
    closing_balances : {bank_id: float}  — balance from latest  txn in period per account
    receipts         : {final_group: sum(credit)}  credits only
    payouts          : {final_group: sum(debit)}   debits only, inter-company/bank excluded
    """
    from config import ENTITIES
    conn = get_connection()

    df_s = str(date_from) if date_from else None
    df_e = str(date_to)   if date_to   else None

    # Accounts in scope for this entity
    if entity and entity != "All":
        accounts = [(entity, b) for b in ENTITIES.get(entity, [])]
    else:
        accounts = [(e, b) for e, bs in ENTITIES.items() for b in bs]

    date_cond = (" AND date >= ? AND date <= ?" if df_s and df_e else "")
    date_p    = ([df_s, df_e]                   if df_s and df_e else [])

    # Opening balance: balance from earliest transaction in period per account
    opening_balances = {}
    closing_balances = {}
    for _ent, bank in accounts:
        r = conn.execute(
            "SELECT balance FROM transactions WHERE bank=? AND balance IS NOT NULL"
            + date_cond + " ORDER BY date ASC, id ASC LIMIT 1",
            [bank] + date_p
        ).fetchone()
        opening_balances[bank] = r[0] if r else None

        r = conn.execute(
            "SELECT balance FROM transactions WHERE bank=? AND balance IS NOT NULL"
            + date_cond + " ORDER BY date DESC, id DESC LIMIT 1",
            [bank] + date_p
        ).fetchone()
        closing_balances[bank] = r[0] if r else None

    # Build WHERE for receipts / payouts
    conds, params = ["1=1"], []
    if entity and entity != "All":
        conds.append("entity = ?")
        params.append(entity)
    if df_s and df_e:
        conds.append("date >= ? AND date <= ?")
        params.extend([df_s, df_e])
    where = "WHERE " + " AND ".join(conds)

    receipts = {}
    for fg, tot in conn.execute(
        f"SELECT final_group, ROUND(SUM(credit),2) FROM transactions "
        f"{where} AND credit > 0 AND final_group IS NOT NULL GROUP BY final_group",
        params
    ).fetchall():
        receipts[fg] = tot or 0

    payouts = {}
    for fg, tot in conn.execute(
        f"SELECT final_group, ROUND(SUM(debit),2) FROM transactions "
        f"{where} AND debit > 0 AND final_group IS NOT NULL "
        f"GROUP BY final_group",
        params
    ).fetchall():
        payouts[fg] = tot or 0

    conn.close()
    return {
        "opening_balances": opening_balances,
        "closing_balances": closing_balances,
        "receipts":         receipts,
        "payouts":          payouts,
    }


def get_investment_register():
    """Get all schemes with opening values."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM investment_register
        ORDER BY scheme_type, scheme_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_investment_opening(scheme_name, opening_value, opening_date, entity):
    """Update opening value for a scheme."""
    conn = get_connection()
    conn.execute("""
        UPDATE investment_register
        SET opening_value = ?,
            opening_date  = ?,
            entity        = ?,
            updated_at    = datetime('now','localtime')
        WHERE scheme_name = ?
    """, [opening_value, opening_date, entity, scheme_name])
    conn.commit()
    conn.close()


def add_investment_scheme(scheme_name, scheme_type, entity, opening_value, opening_date):
    """Add a new investment scheme."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO investment_register
        (scheme_name, scheme_type, entity, opening_value, opening_date)
        VALUES (?,?,?,?,?)
    """, [scheme_name, scheme_type, entity, opening_value, opening_date])
    conn.commit()
    conn.close()


def delete_investment_scheme(scheme_name):
    """Delete a scheme from the register."""
    conn = get_connection()
    conn.execute(
        "DELETE FROM investment_register WHERE scheme_name=?",
        [scheme_name])
    conn.commit()
    conn.close()


def get_investment_transactions(date_from=None, date_to=None, entity=None):
    """
    Get all transactions with main_group='INVESTMENT'.
    LEFT JOINs investment_txn_mapping for scheme tagging details.
    Returns individual rows (not aggregated) for the tagging UI.
    """
    conn   = get_connection()
    where  = "WHERE UPPER(t.main_group)='INVESTMENT'"
    params = []
    if date_from:
        where += " AND t.date >= ?"; params.append(date_from)
    if date_to:
        where += " AND t.date <= ?"; params.append(date_to)
    if entity and entity != "All":
        where += " AND t.entity = ?"; params.append(entity)

    rows = conn.execute(f"""
        SELECT t.id, t.date, t.entity, t.bank,
               t.narration, t.debit, t.credit,
               t.final_group, t.financial_year,
               COALESCE(m.scheme_name,   '') as scheme_name,
               COALESCE(m.scheme_number, '') as scheme_number,
               COALESCE(m.scheme_type,   '') as scheme_type,
               COALESCE(m.notes,         '') as notes
        FROM transactions t
        LEFT JOIN investment_txn_mapping m ON t.id = m.transaction_id
        {where}
        ORDER BY t.date DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def tag_investment_transaction(transaction_id, scheme_name,
                               scheme_number, scheme_type, notes=""):
    """Tag or update a transaction with investment scheme details."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO investment_txn_mapping
            (transaction_id, scheme_name, scheme_number, scheme_type, notes)
        VALUES (?,?,?,?,?)
        ON CONFLICT(transaction_id) DO UPDATE SET
            scheme_name   = excluded.scheme_name,
            scheme_number = excluded.scheme_number,
            scheme_type   = excluded.scheme_type,
            notes         = excluded.notes,
            tagged_at     = datetime('now','localtime')
    """, [transaction_id, scheme_name, scheme_number, scheme_type, notes])
    conn.commit()
    conn.close()


def get_investment_movements(entity=None):
    """
    Aggregates investment transactions by scheme (via tagging).
    Returns per-scheme invested/redeemed totals.
    Untagged transactions are grouped under 'Untagged'.
    """
    conn   = get_connection()
    where  = "WHERE UPPER(t.main_group)='INVESTMENT'"
    params = []
    if entity and entity != "All":
        where += " AND t.entity=?"; params.append(entity)

    rows = conn.execute(f"""
        SELECT
            COALESCE(NULLIF(m.scheme_name,   ''), 'Untagged') as scheme_name,
            COALESCE(NULLIF(m.scheme_number, ''), '—')        as scheme_number,
            COALESCE(NULLIF(m.scheme_type,   ''), '?')        as scheme_type,
            t.entity,
            ROUND(SUM(CASE WHEN t.debit  > 0 THEN t.debit  ELSE 0 END), 2) as invested,
            ROUND(SUM(CASE WHEN t.credit > 0 THEN t.credit ELSE 0 END), 2) as redeemed,
            COUNT(*) as txn_count
        FROM transactions t
        LEFT JOIN investment_txn_mapping m ON t.id = m.transaction_id
        {where}
        GROUP BY scheme_name, scheme_number, scheme_type, t.entity
        ORDER BY invested DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_investment_summary(entity=None, date_from=None, date_to=None):
    """
    Returns full investment portfolio summary:
    - Opening values from investment_register
    - Movements from transactions table
    - Current value = opening + invested - redeemed
    """
    schemes  = get_investment_register()
    txn_data = get_investment_transactions(
        entity=entity, date_from=date_from, date_to=date_to)
    txn_map  = {r["scheme_name"]: r for r in txn_data}

    results = []
    for scheme in schemes:
        if entity and entity != "All" and scheme["entity"] != entity:
            continue
        name     = scheme["scheme_name"]
        txn      = txn_map.get(name, {})
        invested = txn.get("total_invested", 0) or 0
        redeemed = txn.get("total_redeemed", 0) or 0
        opening  = scheme["opening_value"] or 0
        current  = opening + invested - redeemed

        results.append({
            "scheme_name":   name,
            "scheme_type":   scheme["scheme_type"],
            "entity":        scheme["entity"],
            "opening_date":  scheme["opening_date"],
            "opening_value": opening,
            "invested":      invested,
            "redeemed":      redeemed,
            "current_value": current,
            "txn_count":     txn.get("txn_count", 0),
        })

    return results


def get_transfer_reconciliation():
    """Net difference between receipt and payout sides for interbank/intercompany groups."""
    conn = get_connection()

    def _net(prefix):
        r = conn.execute("""
            SELECT
                ROUND(SUM(CASE WHEN credit > 0 THEN credit ELSE 0 END), 2) as cr,
                ROUND(SUM(CASE WHEN debit  > 0 THEN debit  ELSE 0 END), 2) as dr
            FROM transactions
            WHERE UPPER(final_group) LIKE UPPER(?)
               OR UPPER(group_name)  LIKE UPPER(?)
               OR UPPER(main_group)  LIKE UPPER(?)
        """, [f"{prefix}%"] * 3).fetchone()
        return round((r["cr"] or 0) - (r["dr"] or 0), 2)

    ib = _net("INTERBANK")
    ic = _net("INTERCOMPANY")
    conn.close()
    return {
        "interbank_net":    ib if abs(ib) > 1 else None,
        "intercompany_net": ic if abs(ic) > 1 else None,
    }


def get_monthly_trend(months=15):
    """Last N months of receipts vs payouts, excluding internal transfers."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT strftime('%Y-%m', date) as month,
               ROUND(SUM(credit), 2)   as receipts,
               ROUND(SUM(debit),  2)   as payouts
        FROM transactions
        WHERE final_group != 'OPENING BALANCE'
          AND UPPER(main_group) NOT LIKE 'INTERBANK%'
          AND UPPER(main_group) NOT LIKE 'INTERCOMPANY%'
        GROUP BY month
        ORDER BY month DESC
        LIMIT ?
    """, [months]).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_yoy_comparison(current_month):
    """Compare current_month receipts/payouts to same month last year."""
    yr, mo = int(current_month[:4]), int(current_month[5:])
    last_yr_month = f"{yr - 1}-{mo:02d}"
    conn = get_connection()

    def _fetch(m):
        r = conn.execute("""
            SELECT ROUND(SUM(credit), 2) as cr,
                   ROUND(SUM(debit),  2) as dr
            FROM transactions
            WHERE strftime('%Y-%m', date) = ?
              AND final_group != 'OPENING BALANCE'
              AND UPPER(main_group) NOT LIKE 'INTERBANK%'
              AND UPPER(main_group) NOT LIKE 'INTERCOMPANY%'
        """, [m]).fetchone()
        return {"month": m, "receipts": r["cr"] or 0, "payouts": r["dr"] or 0}

    result = {"current": _fetch(current_month), "last_year": _fetch(last_yr_month)}
    conn.close()
    return result


def get_top_expenses_comparison(current_month):
    """Top-8 expense categories for current month vs prior month."""
    yr, mo = int(current_month[:4]), int(current_month[5:])
    last_month = f"{yr}-{mo - 1:02d}" if mo > 1 else f"{yr - 1}-12"
    conn = get_connection()

    def _fetch(m):
        rows = conn.execute("""
            SELECT final_group, ROUND(SUM(debit), 2) as total
            FROM transactions
            WHERE strftime('%Y-%m', date) = ?
              AND debit > 0
              AND final_group NOT IN ('OPENING BALANCE', 'Uncategorized')
              AND UPPER(main_group) NOT LIKE 'INTERBANK%'
              AND UPPER(main_group) NOT LIKE 'INTERCOMPANY%'
            GROUP BY final_group
            ORDER BY total DESC
            LIMIT 8
        """, [m]).fetchall()
        return {r["final_group"]: r["total"] or 0 for r in rows}

    curr = _fetch(current_month)
    prev = _fetch(last_month)
    cats = sorted(set(list(curr) + list(prev)),
                  key=lambda x: curr.get(x, 0), reverse=True)[:8]
    conn.close()
    return {
        "categories":    cats,
        "current":       [curr.get(c, 0) for c in cats],
        "previous":      [prev.get(c, 0) for c in cats],
        "current_month": current_month,
        "prev_month":    last_month,
    }


def get_weekly_cash_position(weeks=12):
    """Net cash flow (credits − debits) per calendar week for last N weeks."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT strftime('%Y-W%W', date) as wk,
               MIN(date)                as week_start,
               ROUND(SUM(credit) - SUM(debit), 2) as net_flow
        FROM transactions
        WHERE final_group != 'OPENING BALANCE'
          AND UPPER(main_group) NOT LIKE 'INTERBANK%'
          AND UPPER(main_group) NOT LIKE 'INTERCOMPANY%'
        GROUP BY wk
        ORDER BY wk DESC
        LIMIT ?
    """, [weeks]).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


ACCOUNT_META = {
    "AXIS-8218": {"bank": "AXIS", "purpose": "OD (30CR)",          "entity": "Stores"},
    "AXIS-7647": {"bank": "AXIS", "purpose": "CC Receiving",        "entity": "Stores"},
    "HDFC-5881": {"bank": "HDFC", "purpose": "Current Account",     "entity": "Stores"},
    "AXIS-5623": {"bank": "AXIS", "purpose": "CC",                  "entity": "Ventures"},
    "HDFC-7862": {"bank": "HDFC", "purpose": "EMI",                 "entity": "Ventures"},
    "HDFC-7640": {"bank": "HDFC", "purpose": "Current Account",     "entity": "Ventures"},
    "SBI-0211":  {"bank": "SBI",  "purpose": "Statutory Payments",  "entity": "Ventures"},
}


def get_account_balances(financial_year=None):
    """
    Per-account closing balance for the Account Balance Summary table.
    Returns list of dicts: bank_id, bank, purpose, entity, acc_no, balance.
    """
    conn = get_connection()

    rows = []
    for bank_id, meta in ACCOUNT_META.items():
        params = [bank_id, bank_id]
        fy_clause = ""
        if financial_year and financial_year != "All":
            fy_clause = "AND financial_year = ?"
            params.insert(0, financial_year)
            params.insert(3, financial_year)  # second occurrence after bank_id

        # Rebuild cleanly to keep param order correct
        fy_filter = f"AND financial_year = ?" if (financial_year and financial_year != "All") else ""
        fy_params = [financial_year] if (financial_year and financial_year != "All") else []

        # Try normal closing balance (last balance from non-OB transactions)
        tx_row = conn.execute(f"""
            SELECT balance FROM transactions
            WHERE bank = ?
              {fy_filter}
              AND final_group != 'OPENING BALANCE'
            ORDER BY date DESC, rowid DESC
            LIMIT 1
        """, [bank_id] + fy_params).fetchone()

        if tx_row and tx_row["balance"] is not None:
            balance = tx_row["balance"]
        else:
            # OB fallback for accounts with no transactions (e.g. SBI-0211)
            ob_row = conn.execute(f"""
                SELECT balance FROM transactions
                WHERE bank = ?
                  {fy_filter}
                  AND final_group = 'OPENING BALANCE'
                ORDER BY date DESC LIMIT 1
            """, [bank_id] + fy_params).fetchone()
            balance = ob_row["balance"] if (ob_row and ob_row["balance"] is not None) else 0.0

        rows.append({
            "bank_id": bank_id,
            "bank":    meta["bank"],
            "purpose": meta["purpose"],
            "entity":  meta["entity"],
            "acc_no":  bank_id.split("-")[1] if "-" in bank_id else bank_id,
            "balance": round(balance, 2),
        })

    conn.close()
    return rows


def get_cash_at_stores():
    """Return current Cash at Stores value (0.0 if never set)."""
    conn = get_connection()
    row = conn.execute(
        "SELECT value FROM cash_register ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return row["value"] if row else 0.0


def set_cash_at_stores(value: float):
    """Insert a new Cash at Stores entry (keeps history)."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO cash_register (value) VALUES (?)", [round(float(value), 2)]
    )
    conn.commit()
    conn.close()


@functools.lru_cache(maxsize=32)
def get_tab_summary_cached(entity, bank, month, financial_year):
    """
    Lightweight summary for header band only.
    Uses SQL aggregates — never loads all rows into memory.
    """
    conn   = get_connection()
    where  = "WHERE final_group != 'OPENING BALANCE'"
    params = []
    if entity and entity != "All":
        where += " AND entity=?";        params.append(entity)
    if bank and bank != "All":
        where += " AND bank=?";          params.append(bank)
    if month and month != "All":
        where += " AND strftime('%Y-%m',date)=?"; params.append(month)
    if financial_year and financial_year != "All":
        where += " AND financial_year=?"; params.append(financial_year)

    r = conn.execute(f"""
        SELECT
            ROUND(SUM(CASE WHEN credit > 0 THEN credit ELSE 0 END), 2) as total_cr,
            ROUND(SUM(CASE WHEN debit  > 0 THEN debit  ELSE 0 END), 2) as total_dr,
            COUNT(*) as txn_count
        FROM transactions {where}
    """, params).fetchone()
    conn.close()
    return {
        "total_receipts": r["total_cr"] or 0,
        "total_payouts":  r["total_dr"] or 0,
        "txn_count":      r["txn_count"] or 0,
    }


if __name__ == "__main__":
    init_db()
