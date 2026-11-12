import sqlite3
import hashlib
import os
import datetime
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

    # Migration: add upload_id column — links each transaction row back to the
    # exact upload_trail entry that inserted it, so a delete can identify the
    # right rows without guessing from filename/entity/bank/date (which collide
    # whenever the same statement filename is re-uploaded for a later period).
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN upload_id INTEGER")
        conn.commit()
    except Exception:
        pass  # Already exists

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_txn_upload_id ON transactions(upload_id)"
        )
        conn.commit()
    except Exception:
        pass

    # Migration: ord_key = position of the row within its day, used wherever "the last
    # transaction of the day" matters (closing balances). Defaults to the load order (id);
    # rows from a complete statement day are re-stamped with the statement's own order.
    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN ord_key INTEGER")
        conn.commit()
    except Exception:
        pass  # Already exists
    if conn.execute("SELECT 1 FROM transactions WHERE ord_key IS NULL LIMIT 1").fetchone():
        conn.execute("UPDATE transactions SET ord_key = id WHERE ord_key IS NULL")
        conn.commit()
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_txn_bank_date_ord ON transactions(bank, date, ord_key)")
        conn.commit()
    except Exception:
        pass

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

    # New schema: one row per (entity, entry_date), upsert on conflict
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cash_register_v2 (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity      TEXT NOT NULL DEFAULT 'Stores',
            entry_date  TEXT NOT NULL,
            value       REAL NOT NULL DEFAULT 0,
            updated_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(entity, entry_date)
        )
    """)
    conn.commit()

    # One-time migration: carry forward old cash_register's latest value
    # as today's entry in cash_register_v2, if v2 is empty
    existing_v2 = conn.execute(
        "SELECT COUNT(*) FROM cash_register_v2").fetchone()[0]
    if existing_v2 == 0:
        old = conn.execute("""
            SELECT value FROM cash_register
            ORDER BY updated_at DESC LIMIT 1
        """).fetchone()
        if old:
            import datetime as _dt
            conn.execute("""
                INSERT OR IGNORE INTO cash_register_v2
                (entity, entry_date, value)
                VALUES ('Stores', ?, ?)
            """, [str(_dt.date.today()), old["value"]])
            conn.commit()
            print(f"[DB] Migrated old cash_register value {old['value']} to cash_register_v2")

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

    # manual_investments — off-statement FD/MF entries
    conn.execute("""
        CREATE TABLE IF NOT EXISTS manual_investments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_date  TEXT NOT NULL,
            scheme_name TEXT NOT NULL,
            scheme_type TEXT NOT NULL,
            amount      REAL NOT NULL,
            entry_type  TEXT NOT NULL,
            entity      TEXT DEFAULT 'Ventures',
            notes       TEXT,
            created_at  TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.commit()

    # Capital-gain support: units / NAV on manual MF entries, historical lots, open lots, FD rate card
    for _col in ("units REAL", "nav REAL"):
        try:
            conn.execute(f"ALTER TABLE manual_investments ADD COLUMN {_col}")
            conn.commit()
        except Exception:
            pass  # Already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS mf_historical_lots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entity        TEXT NOT NULL,
            fund_type     TEXT,
            scheme_name   TEXT,
            purchase_date TEXT NOT NULL,
            units         REAL NOT NULL,
            purchase_nav  REAL NOT NULL,
            sale_date     TEXT NOT NULL,
            units_sold    REAL NOT NULL,
            sale_nav      REAL NOT NULL,
            fd_rate       REAL,
            imported_at   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mf_opening_lots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            entity        TEXT NOT NULL,
            scheme_name   TEXT NOT NULL,
            fund_type     TEXT,
            purchase_date TEXT NOT NULL,
            units         REAL NOT NULL,
            nav           REAL NOT NULL,
            imported_at   TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fd_rate_card (
            min_days INTEGER PRIMARY KEY,
            label    TEXT NOT NULL,
            rate     REAL NOT NULL
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM fd_rate_card").fetchone()[0] == 0:
        conn.executemany("INSERT INTO fd_rate_card (min_days, label, rate) VALUES (?,?,?)", [
            (0,   "Under 7 days",   0.0),
            (7,   "7 - 14 days",    0.0475),
            (15,  "15 - 29 days",   0.0475),
            (30,  "30 - 45 days",   0.055),
            (46,  "46 - 60 days",   0.0575),
            (61,  "61 - 89 days",   0.06),
            (90,  "90 - 119 days",  0.065),
            (120, "120 days & above", 0.07),
        ])
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


def make_fingerprint(entity, bank, date, narration, debit, credit, occurrence=0):
    """
    occurrence = 0 for the first copy of an identical row (date+narration+amounts),
    1, 2, ... for further identical copies in the same statement. Occurrence 0 keeps
    the historical fingerprint, so existing data and re-uploads still de-duplicate,
    while genuinely repeated transactions (e.g. two identical cheques the same day)
    are no longer dropped as "duplicates".
    """
    raw = f"{entity}|{bank}|{date}|{narration}|{debit}|{credit}"
    if occurrence:
        raw += f"|#{occurrence}"
    return hashlib.md5(raw.encode()).hexdigest()


def insert_transactions(rows):
    conn = get_connection()
    c = conn.cursor()
    inserted = 0
    skipped  = 0
    seen_in_batch = {}      # identical-row counter within this statement
    day_rows = {}           # (bank, date) -> [(fingerprint, statement position)]

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

        _key = (row["entity"], row["bank"], row["date"],
                row["narration"], row["debit"], row["credit"])
        _occ = seen_in_batch.get(_key, 0)
        seen_in_batch[_key] = _occ + 1
        fp = make_fingerprint(*_key, occurrence=_occ)
        fy = _date_to_fy(row["date"])
        if row.get("stmt_seq") is not None and row.get("final_group") != "OPENING BALANCE":
            day_rows.setdefault((row["bank"], row["date"]), []).append(
                (fp, int(row["stmt_seq"])))
        try:
            c.execute("""
                INSERT INTO transactions
                (fingerprint, entity, bank, date, narration,
                 debit, credit, balance, category, final_group,
                 group_name, main_group, source_file, manually_overridden,
                 financial_year, upload_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                fy,
                row.get("upload_id"),
            ))
            inserted += 1
        except sqlite3.IntegrityError:
            skipped += 1   # duplicate fingerprint — expected
        except Exception as exc:
            skipped += 1
            print(f"[DB] ERROR inserting row ({row.get('bank')} {row.get('date')}): {exc}")

    # New rows take their load order as ord_key (same as id)
    c.execute("UPDATE transactions SET ord_key = id WHERE ord_key IS NULL")

    # If this statement contains EVERY row now stored for a day, it is authoritative for
    # that day's order: re-stamp all of the day's rows (new and already-loaded) with the
    # statement's own row order. Partial statements leave the order untouched.
    for (bank, date), items in day_rows.items():
        stored = c.execute(
            "SELECT COUNT(*) FROM transactions "
            "WHERE bank=? AND date=? AND final_group != 'OPENING BALANCE'",
            [bank, date]).fetchone()[0]
        if stored == len(items):
            c.executemany("UPDATE transactions SET ord_key=? WHERE fingerprint=?",
                          [(seq, fp) for fp, seq in items])

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


def reserve_upload_trail(filename, entity, bank):
    """
    Insert a placeholder upload_trail row BEFORE processing, so the returned
    trail_id can be stamped onto each transaction row as upload_id. This is
    what makes delete_upload() able to identify the exact rows a given
    upload created, even if the same filename is re-uploaded later.
    """
    conn = get_connection()
    conn.execute("""
        INSERT INTO upload_trail
        (filename, entity, bank, financial_year, rows_inserted, date_from, date_to)
        VALUES (?, ?, ?, NULL, 0, NULL, NULL)
    """, [filename, entity, bank])
    conn.commit()
    trail_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return trail_id


def finalize_upload_trail(trail_id, financial_year, rows_inserted, date_from, date_to):
    """Fill in the stats for a trail row created by reserve_upload_trail()."""
    conn = get_connection()
    conn.execute("""
        UPDATE upload_trail
        SET financial_year=?, rows_inserted=?, date_from=?, date_to=?
        WHERE id=?
    """, [financial_year, rows_inserted, date_from, date_to, trail_id])
    conn.commit()
    conn.close()


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


def _upload_match_clause(conn, trail):
    """
    Decide how to identify the transaction rows belonging to this upload.
    Preferred: exact upload_id link (stamped at insert time by reserve_upload_trail).
    Fallback: legacy heuristic (source_file+entity+bank+date range) for uploads
    that predate upload_id tracking — flagged as such since filename reuse
    (e.g. the same monthly statement name re-uploaded later) can make this
    heuristic ambiguous.
    Returns (where_sql, params, match_mode).
    """
    has_upload_id = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE upload_id=?",
        [trail["id"]]
    ).fetchone()[0]
    if has_upload_id:
        return "upload_id = ?", [trail["id"]], "upload_id"
    return (
        "source_file = ? AND entity = ? AND bank = ? AND date BETWEEN ? AND ?",
        [trail["filename"], trail["entity"], trail["bank"],
         trail["date_from"], trail["date_to"]],
        "legacy_heuristic",
    )


def check_upload_delete_impact(trail_id):
    """
    Inspect (without deleting) what a delete_upload(trail_id) call would affect.
    Returns dict: trail, match_mode, total_matched, manually_overridden_count.
    """
    conn = get_connection()
    trail = conn.execute(
        "SELECT * FROM upload_trail WHERE id=?", [trail_id]).fetchone()
    if not trail:
        conn.close()
        return {"trail": None, "match_mode": "none",
                "total_matched": 0, "manually_overridden_count": 0}
    trail = dict(trail)
    where, params, match_mode = _upload_match_clause(conn, trail)

    total = conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE {where}", params
    ).fetchone()[0]
    overridden = conn.execute(
        f"SELECT COUNT(*) FROM transactions WHERE {where} "
        f"AND COALESCE(manually_overridden,0)=1", params
    ).fetchone()[0]
    conn.close()
    return {
        "trail": trail,
        "match_mode": match_mode,
        "total_matched": total,
        "manually_overridden_count": overridden,
    }


def delete_upload(trail_id, include_manually_overridden=False):
    """
    Deletes the upload_trail row AND every transaction row that came from it.
    Matches by the exact upload_id link when available; only falls back to the
    source_file+entity+bank+date heuristic for uploads that predate upload_id
    tracking (see _upload_match_clause).
    manually_overridden rows are excluded unless include_manually_overridden=True
    is explicitly passed — call check_upload_delete_impact() first to find out
    if any exist so the caller can ask for confirmation.
    Returns dict: deleted, manually_overridden_skipped, match_mode.
    """
    conn = get_connection()
    trail = conn.execute(
        "SELECT * FROM upload_trail WHERE id=?", [trail_id]).fetchone()
    if not trail:
        conn.close()
        return {"deleted": 0, "manually_overridden_skipped": 0, "match_mode": "none"}
    trail = dict(trail)
    where, params, match_mode = _upload_match_clause(conn, trail)

    overridden_skipped = 0
    if not include_manually_overridden:
        overridden_skipped = conn.execute(
            f"SELECT COUNT(*) FROM transactions WHERE {where} "
            f"AND COALESCE(manually_overridden,0)=1", params
        ).fetchone()[0]
        result = conn.execute(
            f"DELETE FROM transactions WHERE {where} "
            f"AND COALESCE(manually_overridden,0)=0", params
        )
    else:
        result = conn.execute(f"DELETE FROM transactions WHERE {where}", params)

    deleted_rows = result.rowcount
    conn.execute("UPDATE upload_trail SET deleted=1 WHERE id=?", [trail_id])
    conn.commit()
    conn.close()
    return {
        "deleted": deleted_rows,
        "manually_overridden_skipped": overridden_skipped,
        "match_mode": match_mode,
    }


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


def get_uncategorized(entity=None, bank=None,
                      month=None, financial_year=None):
    conn   = get_connection()
    where  = """WHERE (final_group='Uncategorized'
                OR final_group IS NULL
                OR TRIM(final_group)='')
                AND final_group != 'OPENING BALANCE'"""
    params = []
    if entity and entity != "All":
        where += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        where += " AND bank=?"; params.append(bank)
    if month and month != "All":
        where += " AND strftime('%Y-%m',date)=?"; params.append(month)
    if financial_year and financial_year != "All":
        where += " AND financial_year=?"; params.append(financial_year)

    rows = conn.execute(f"""
        SELECT narration, entity, COUNT(*) as count,
               SUM(debit) as total_debit
        FROM transactions {where}
        GROUP BY narration, entity
        ORDER BY count DESC
    """, params).fetchall()
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

    today          = datetime.date.today()
    current_month  = today.strftime("%Y-%m")
    fy_clause      = ""
    fy_params_base = []
    if financial_year and financial_year != "All":
        fy_clause      = "AND financial_year=?"
        fy_params_base = [financial_year]

    conn    = get_connection()
    results = []

    for entity, banks in ENTITIES.items():
        for bank in banks:
            row = conn.execute(f"""
                SELECT MAX(date) as last_date,
                       COUNT(*)  as total_rows
                FROM transactions
                WHERE bank=?
                AND final_group != 'OPENING BALANCE'
                {fy_clause}
            """, [bank] + fy_params_base).fetchone()

            last_date  = row["last_date"]  if row else None
            total_rows = row["total_rows"] if row else 0

            closing_bal = None
            if last_date:
                cb_row = conn.execute("""
                    SELECT balance FROM transactions
                    WHERE bank=?
                    AND date=?
                    AND final_group != 'OPENING BALANCE'
                    AND balance IS NOT NULL
                    ORDER BY ord_key DESC LIMIT 1
                """, [bank, last_date]).fetchone()
                if cb_row:
                    closing_bal = cb_row["balance"]

            if last_date:
                last_dt     = datetime.date.fromisoformat(last_date)
                days_ago    = (today - last_dt).days
                has_current = last_dt.strftime("%Y-%m") == current_month
            else:
                days_ago    = 999
                has_current = False

            results.append({
                "entity":      entity,
                "bank":        bank,
                "last_date":   last_date or "Never loaded",
                "days_ago":    days_ago,
                "has_current": has_current,
                "total_rows":  total_rows,
                "closing_bal": closing_bal,
                "status": (
                    "ok"      if has_current else
                    "warning" if days_ago <= 40 else
                    "missing"
                ),
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


def get_transaction_count(entity=None, bank=None, month=None, financial_year=None,
                          date_from=None, date_to=None):
    """Count only — never loads rows into memory."""
    conn   = get_connection()
    query  = "SELECT COUNT(*) as cnt FROM transactions WHERE final_group != 'OPENING BALANCE'"
    params = []
    if entity and entity != "All":
        query += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        query += " AND bank=?"; params.append(bank)
    if date_from and date_to:
        query += " AND date >= ? AND date <= ?"; params.extend([str(date_from), str(date_to)])
    elif month and month != "All":
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
        ORDER BY bank, date DESC, ord_key DESC
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


def get_entity_closing_balance(entity, financial_year=None):
    """
    Returns total closing balance for a specific entity.
    Uses last transaction balance per bank for that entity.
    Falls back to OB row for banks with no transactions.
    """
    conn      = get_connection()
    fy_clause = ""
    fy_params = []
    if financial_year and financial_year != "All":
        fy_clause = "AND financial_year=?"
        fy_params = [financial_year]

    banks = conn.execute(f"""
        SELECT DISTINCT bank FROM transactions
        WHERE entity=? {fy_clause}
    """, [entity] + fy_params).fetchall()

    total = 0
    for b in banks:
        bank = b["bank"]
        row  = conn.execute(f"""
            SELECT balance FROM transactions
            WHERE bank=? AND entity=?
            AND final_group != 'OPENING BALANCE'
            AND balance IS NOT NULL
            {fy_clause}
            ORDER BY date DESC, ord_key DESC LIMIT 1
        """, [bank, entity] + fy_params).fetchone()

        if row and row["balance"] is not None:
            total += row["balance"]
        else:
            ob = conn.execute("""
                SELECT balance FROM transactions
                WHERE bank=? AND entity=?
                AND final_group='OPENING BALANCE'
                ORDER BY date DESC LIMIT 1
            """, [bank, entity]).fetchone()
            if ob and ob["balance"] is not None:
                total += ob["balance"]

    conn.close()
    return total


def get_summary_with_bank(entity=None, bank=None,
                          month=None, date_from=None, date_to=None):
    """
    Summary query that accepts bank AND date_from/date_to filters.
    Fixes the bug where _cached_summary() ignored bank and date range.
    """
    conn   = get_connection()
    where  = "WHERE final_group != 'OPENING BALANCE'"
    params = []

    if entity and entity != "All":
        where += " AND entity=?"; params.append(entity)
    if bank and bank != "All":
        where += " AND bank=?"; params.append(bank)
    if date_from and date_to:
        where += " AND date BETWEEN ? AND ?"
        params += [date_from, date_to]
    elif month and month != "All":
        where += " AND strftime('%Y-%m',date)=?"; params.append(month)

    row = conn.execute(f"""
        SELECT
            ROUND(SUM(CASE WHEN credit>0 THEN credit ELSE 0 END),2) as cr,
            ROUND(SUM(CASE WHEN debit>0  THEN debit  ELSE 0 END),2) as dr,
            COUNT(*) as cnt
        FROM transactions {where}
    """, params).fetchone()
    conn.close()
    return {
        "total_receipts": row["cr"] or 0,
        "total_payouts":  row["dr"] or 0,
        "txn_count":      row["cnt"] or 0,
    }


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
        f" ORDER BY date DESC, ord_key DESC LIMIT ? OFFSET ?",
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
            + date_cond + " ORDER BY date ASC, ord_key ASC LIMIT 1",
            [bank] + date_p
        ).fetchone()
        opening_balances[bank] = r[0] if r else None

        r = conn.execute(
            "SELECT balance FROM transactions WHERE bank=? AND balance IS NOT NULL"
            + date_cond + " ORDER BY date DESC, ord_key DESC LIMIT 1",
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


def get_investment_movements(entity=None, date_from=None, date_to=None):
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
    if date_from:
        where += " AND t.date>=?"; params.append(date_from)
    if date_to:
        where += " AND t.date<=?"; params.append(date_to)

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


def get_investment_events(entity=None):
    """
    Every investment balance movement, all sources, as one flat list.
    Each row: date, scheme_name, scheme_type ('FD'/'MF'), entity, delta, source.
    delta > 0 = invested (balance up), delta < 0 = redeemed (balance down).
    Register opening values are emitted with date=None (present from the start).
    Untagged bank INVESTMENT transactions are returned as scheme 'Untagged', type 'FD'
    (consistent with the Cash Flow tab, which derives FD = combined - MF).
    """
    conn = get_connection()
    ent_sql, ent_p = "", []
    if entity and entity != "All":
        ent_sql, ent_p = " AND entity=?", [entity]

    events = []
    for r in conn.execute(
            f"SELECT scheme_name, scheme_type, entity, opening_value "
            f"FROM investment_register WHERE 1=1{ent_sql}", ent_p).fetchall():
        events.append({"date": None, "scheme_name": r["scheme_name"],
                       "scheme_type": r["scheme_type"], "entity": r["entity"],
                       "delta": r["opening_value"] or 0, "source": "Opening"})

    for r in conn.execute(f"""
        SELECT t.date, t.entity, t.debit, t.credit,
               COALESCE(NULLIF(m.scheme_name,''), 'Untagged') AS scheme_name,
               COALESCE(NULLIF(m.scheme_type,''), 'FD')       AS scheme_type
        FROM transactions t
        LEFT JOIN investment_txn_mapping m ON t.id = m.transaction_id
        WHERE UPPER(t.main_group)='INVESTMENT'{ent_sql.replace('entity', 't.entity')}
    """, ent_p).fetchall():
        delta = (r["debit"] or 0) - (r["credit"] or 0)
        if delta:
            events.append({"date": r["date"], "scheme_name": r["scheme_name"],
                           "scheme_type": r["scheme_type"], "entity": r["entity"],
                           "delta": delta, "source": "Bank Txn"})

    for r in conn.execute(
            f"SELECT entry_date, scheme_name, scheme_type, entity, amount, entry_type "
            f"FROM manual_investments WHERE 1=1{ent_sql}", ent_p).fetchall():
        sign = 1 if r["entry_type"] == "Invested" else -1
        events.append({"date": r["entry_date"], "scheme_name": r["scheme_name"],
                       "scheme_type": r["scheme_type"], "entity": r["entity"],
                       "delta": sign * (r["amount"] or 0), "source": "Manual"})
    conn.close()
    return events


def get_investment_summary(entity=None, date_from=None, date_to=None):
    """
    Returns full investment portfolio summary:
    - Opening values from investment_register
    - Movements from transactions table
    - Current value = opening + invested - redeemed
    """
    schemes  = get_investment_register()
    # Per-scheme invested/redeemed come from get_investment_movements(); the
    # row-level get_investment_transactions() has no such totals.
    txn_data = get_investment_movements(
        entity=entity, date_from=date_from, date_to=date_to)
    txn_map  = {}
    for r in txn_data:
        agg = txn_map.setdefault(r["scheme_name"],
                                 {"total_invested": 0, "total_redeemed": 0, "txn_count": 0})
        agg["total_invested"] += r["invested"] or 0
        agg["total_redeemed"] += r["redeemed"] or 0
        agg["txn_count"]      += r["txn_count"] or 0

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
            ORDER BY date DESC, ord_key DESC
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


def get_account_balances_asof(as_of_date, entity_filter=None, bank_filter=None):
    """
    Per-account balance AS ON a specific date, filtered by entity and/or bank.
    Returns list of dicts: bank_id, bank, purpose, entity, acc_no, balance.
    """
    conn = get_connection()
    results = []

    for bank_id, meta in ACCOUNT_META.items():
        if entity_filter and entity_filter != "All" and meta["entity"] != entity_filter:
            continue
        if bank_filter and bank_filter != "All" and bank_id != bank_filter:
            continue

        row = conn.execute("""
            SELECT balance FROM transactions
            WHERE bank=?
            AND date <= ?
            AND final_group != 'OPENING BALANCE'
            AND balance IS NOT NULL
            ORDER BY date DESC, ord_key DESC LIMIT 1
        """, [bank_id, as_of_date]).fetchone()

        if row and row["balance"] is not None:
            balance = row["balance"]
        else:
            ob = conn.execute("""
                SELECT balance FROM transactions
                WHERE bank=? AND final_group='OPENING BALANCE'
                ORDER BY date DESC LIMIT 1
            """, [bank_id]).fetchone()
            balance = ob["balance"] if (ob and ob["balance"] is not None) else 0.0

        results.append({
            "bank_id": bank_id,
            "bank":    meta["bank"],
            "purpose": meta["purpose"],
            "entity":  meta["entity"],
            "acc_no":  bank_id.split("-")[1] if "-" in bank_id else bank_id,
            "balance": round(balance, 2),
        })

    conn.close()
    return results


def set_cash_entry(entity, entry_date, value):
    """Upsert cash value for a specific entity+date. Overwrites if exists."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO cash_register_v2 (entity, entry_date, value, updated_at)
        VALUES (?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(entity, entry_date) DO UPDATE SET
            value=excluded.value,
            updated_at=datetime('now','localtime')
    """, [entity, entry_date, value])
    conn.commit()
    conn.close()


def get_cash_asof(entity, as_of_date):
    """
    Cash at Stores value AS ON a specific date.
    Uses last entry on or before as_of_date (carry-forward logic,
    same pattern as bank balance as-of).
    """
    conn = get_connection()
    row = conn.execute("""
        SELECT value FROM cash_register_v2
        WHERE entity=? AND entry_date <= ?
        ORDER BY entry_date DESC LIMIT 1
    """, [entity, as_of_date]).fetchone()
    conn.close()
    return row["value"] if row else 0


def get_cash_history(entity=None):
    """Full audit trail of all cash entries, most recent first."""
    conn = get_connection()
    where  = ""
    params = []
    if entity and entity != "All":
        where = "WHERE entity=?"
        params = [entity]
    rows = conn.execute(f"""
        SELECT id, entity, entry_date, value, updated_at
        FROM cash_register_v2
        {where}
        ORDER BY entry_date DESC, entity
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_cash_entry(entry_id):
    conn = get_connection()
    conn.execute("DELETE FROM cash_register_v2 WHERE id=?", [entry_id])
    conn.commit()
    conn.close()


def import_cash_excel(filepath):
    """
    Bulk import historical cash-at-stores data.
    Expected columns: Entity | Date | Value
    Upserts — re-uploading same entity+date overwrites the value.
    """
    import pandas as pd

    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        return {"inserted": 0, "errors": 1, "error_rows": [str(e)]}

    df.columns = [str(c).strip() for c in df.columns]

    COL_MAP = {
        "entity": ["Entity", "ENTITY"],
        "date":   ["Date", "DATE"],
        "value":  ["Value", "VALUE", "Amount", "Cash Value"],
    }
    def find_col(cands):
        for c in cands:
            if c in df.columns:
                return c
        return None
    cols = {k: find_col(v) for k, v in COL_MAP.items()}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        return {"inserted": 0, "errors": 1,
                "error_rows": [f"Missing columns: {missing}. Available: {list(df.columns)}"]}

    conn = get_connection()
    inserted, skipped, errors = 0, 0, 0
    error_rows = []

    for idx, row in df.iterrows():
        try:
            entity = str(row.get(cols["entity"]) or "").strip().title()
            if entity not in ("Stores", "Ventures"):
                skipped += 1
                error_rows.append(f"Row {idx+2}: Invalid entity '{entity}'")
                continue

            date_raw = str(row.get(cols["date"]) or "").strip()
            if not date_raw or date_raw in ("nan","None","-"):
                skipped += 1
                error_rows.append(f"Row {idx+2}: Missing date")
                continue
            entry_date = pd.to_datetime(date_raw).strftime("%Y-%m-%d")

            val_raw = str(row.get(cols["value"]) or "").strip()
            if not val_raw or val_raw in ("nan","None","-"):
                skipped += 1
                error_rows.append(f"Row {idx+2}: Missing value")
                continue
            value = float(val_raw.replace(",","").replace("₹","").strip())

            conn.execute("""
                INSERT INTO cash_register_v2 (entity, entry_date, value, updated_at)
                VALUES (?, ?, ?, datetime('now','localtime'))
                ON CONFLICT(entity, entry_date) DO UPDATE SET
                    value=excluded.value,
                    updated_at=datetime('now','localtime')
            """, [entity, entry_date, value])
            inserted += 1

        except Exception as e:
            errors += 1
            error_rows.append(f"Row {idx+2}: {str(e)}")

    conn.commit()
    conn.close()
    return {"inserted": inserted, "skipped": skipped,
             "errors": errors, "error_rows": error_rows}


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


def add_manual_investment(entry_date, scheme_name, scheme_type,
                          amount, entry_type, entity, notes="", units=None, nav=None):
    """
    units + nav (MF only): the entry takes part in FIFO capital-gain matching and its
    `amount` (the balance impact at cost) is maintained automatically:
      purchase   -> units x NAV
      redemption -> cost of the oldest purchase lots it consumes (FIFO)
    Returns the new entry id.
    """
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO manual_investments
        (entry_date, scheme_name, scheme_type, amount, entry_type, entity, notes, units, nav)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, [entry_date, scheme_name, scheme_type, amount, entry_type, entity, notes, units, nav])
    entry_id = cur.lastrowid
    conn.commit()
    conn.close()
    if units and nav:
        refresh_fifo_amounts()
    return entry_id


def get_manual_investments():
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM manual_investments ORDER BY entry_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_manual_investment(entry_id):
    conn = get_connection()
    conn.execute("DELETE FROM manual_investments WHERE id=?", [entry_id])
    conn.commit()
    conn.close()
    refresh_fifo_amounts()      # later redemptions may now match different lots


def get_manual_investment_totals():
    """Per-scheme net totals from manual entries (not in bank statements)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            scheme_name,
            scheme_type,
            entity,
            ROUND(SUM(CASE WHEN entry_type='Invested' THEN amount ELSE 0 END), 2) as invested,
            ROUND(SUM(CASE WHEN entry_type='Redeemed' THEN amount ELSE 0 END), 2) as redeemed,
            COUNT(*) as entry_count
        FROM manual_investments
        GROUP BY scheme_name, scheme_type, entity
        ORDER BY scheme_type, scheme_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def import_investment_excel(filepath):
    """
    Import investment transactions from Excel.
    Expected columns:
    Date | Scheme Name | Scheme Number | Type (FD/MF) |
    Amount | Entry Type (Invested/Redeemed) | Entity
    All fields mandatory.
    Returns dict: inserted, skipped, errors, error_rows
    """
    import pandas as pd

    try:
        df = pd.read_excel(filepath, dtype=str)
    except Exception as e:
        return {"inserted": 0, "skipped": 0,
                "errors": 1, "error_rows": [str(e)]}

    df.columns = [str(c).strip() for c in df.columns]

    COL_MAP = {
        "date":        ["Date", "DATE"],
        "scheme_name": ["Scheme Name", "SchemeName", "SCHEME NAME"],
        "scheme_no":   ["Scheme Number", "SchemeNumber", "SCHEME NUMBER",
                        "Scheme No", "Scheme No."],
        "type":        ["Type", "TYPE", "Scheme Type"],
        "amount":      ["Amount", "AMOUNT"],
        "entry_type":  ["Entry Type", "EntryType", "Invested or Redeemed",
                        "Type", "ENTRY TYPE"],
        "entity":      ["Entity", "ENTITY"],
    }

    def find_col(candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    cols = {k: find_col(v) for k, v in COL_MAP.items()}
    missing = [k for k, v in cols.items() if v is None]
    if missing:
        return {
            "inserted": 0, "skipped": 0, "errors": 1,
            "error_rows": [
                f"Missing columns: {missing}. "
                f"Available: {list(df.columns)}"
            ]
        }

    conn       = get_connection()
    inserted   = 0
    skipped    = 0
    errors     = 0
    error_rows = []

    for idx, row in df.iterrows():
        try:
            date_raw    = str(row.get(cols["date"])        or "").strip()
            scheme_name = str(row.get(cols["scheme_name"]) or "").strip()
            scheme_no   = str(row.get(cols["scheme_no"])   or "").strip()
            stype       = str(row.get(cols["type"])        or "").strip()
            amount_raw  = str(row.get(cols["amount"])      or "").strip()
            entry_type  = str(row.get(cols["entry_type"])  or "").strip()
            entity      = str(row.get(cols["entity"])      or "").strip()

            missing_vals = []
            if not date_raw    or date_raw    in ("nan", "None", "-"): missing_vals.append("Date")
            if not scheme_name or scheme_name in ("nan", "None", "-"): missing_vals.append("Scheme Name")
            if not scheme_no   or scheme_no   in ("nan", "None", "-"): missing_vals.append("Scheme Number")
            if not stype       or stype       in ("nan", "None", "-"): missing_vals.append("Type")
            if not amount_raw  or amount_raw  in ("nan", "None", "-"): missing_vals.append("Amount")
            if not entry_type  or entry_type  in ("nan", "None", "-"): missing_vals.append("Entry Type")
            if not entity      or entity      in ("nan", "None", "-"): missing_vals.append("Entity")

            if missing_vals:
                skipped += 1
                error_rows.append(f"Row {idx+2}: Missing {missing_vals}")
                continue

            import pandas as _pd
            try:
                entry_date = _pd.to_datetime(date_raw).strftime("%Y-%m-%d")
            except Exception:
                skipped += 1
                error_rows.append(f"Row {idx+2}: Invalid date '{date_raw}'")
                continue

            try:
                amount = abs(float(
                    amount_raw.replace(",", "").replace("₹", "").strip()))
            except Exception:
                skipped += 1
                error_rows.append(f"Row {idx+2}: Invalid amount '{amount_raw}'")
                continue

            stype_clean = stype.upper()
            if stype_clean not in ("FD", "MF"):
                skipped += 1
                error_rows.append(
                    f"Row {idx+2}: Type must be FD or MF, got '{stype}'")
                continue

            et_clean = entry_type.strip().title()
            if et_clean not in ("Invested", "Redeemed"):
                skipped += 1
                error_rows.append(
                    f"Row {idx+2}: Entry Type must be "
                    f"Invested or Redeemed, got '{entry_type}'")
                continue

            entity_clean = entity.strip().title()
            if entity_clean not in ("Stores", "Ventures"):
                skipped += 1
                error_rows.append(
                    f"Row {idx+2}: Entity must be "
                    f"Stores or Ventures, got '{entity}'")
                continue

            _notes = f"Scheme No: {scheme_no}"
            _dupe = conn.execute("""
                SELECT COUNT(*) FROM manual_investments
                WHERE entry_date=? AND scheme_name=? AND scheme_type=?
                  AND amount=? AND entry_type=? AND entity=? AND notes=?
            """, [entry_date, scheme_name, stype_clean,
                  amount, et_clean, entity_clean, _notes]).fetchone()[0]
            if _dupe:
                skipped += 1
                error_rows.append(
                    f"Row {idx+2}: Duplicate of an existing entry "
                    f"({scheme_name}, {entry_date}, {et_clean} "
                    f"{amount:,.0f}) — skipped")
                continue

            conn.execute("""
                INSERT INTO manual_investments
                (entry_date, scheme_name, scheme_type, amount,
                 entry_type, entity, notes)
                VALUES (?,?,?,?,?,?,?)
            """, [entry_date, scheme_name, stype_clean,
                  amount, et_clean, entity_clean, _notes])
            inserted += 1

        except Exception as e:
            errors += 1
            error_rows.append(f"Row {idx+2}: {str(e)}")

    conn.commit()
    conn.close()
    return {
        "inserted":   inserted,
        "skipped":    skipped,
        "errors":     errors,
        "error_rows": error_rows,
    }


def get_investment_kpis(entity=None):
    """
    Returns Opening, MF Balance, FD Balance, Closing for Investment tab flash cards.
    Closing = Opening (register) + bank txn movements + manual entries.
    """
    conn = get_connection()

    where_reg  = ""
    params_reg = []
    if entity and entity != "All":
        where_reg  = "WHERE entity=?"
        params_reg = [entity]

    reg_rows = conn.execute(f"""
        SELECT scheme_type, SUM(opening_value) as opening
        FROM investment_register
        {where_reg}
        GROUP BY scheme_type
    """, params_reg).fetchall()

    fd_opening    = sum(r["opening"] or 0 for r in reg_rows if r["scheme_type"] == "FD")
    mf_opening    = sum(r["opening"] or 0 for r in reg_rows if r["scheme_type"] == "MF")
    total_opening = fd_opening + mf_opening

    where_txn  = "WHERE UPPER(main_group)='INVESTMENT'"
    params_txn = []
    if entity and entity != "All":
        where_txn  += " AND entity=?"
        params_txn  = [entity]

    txn_rows = conn.execute(f"""
        SELECT
            COALESCE(m.scheme_type, '') as scheme_type,
            ROUND(SUM(CASE WHEN t.debit>0  THEN t.debit  ELSE 0 END),2) as invested,
            ROUND(SUM(CASE WHEN t.credit>0 THEN t.credit ELSE 0 END),2) as redeemed
        FROM transactions t
        LEFT JOIN investment_txn_mapping m ON t.id=m.transaction_id
        {where_txn}
        GROUP BY m.scheme_type
    """, params_txn).fetchall()

    fd_txn_net = sum(
        (r["invested"] or 0) - (r["redeemed"] or 0)
        for r in txn_rows if r["scheme_type"] == "FD")
    mf_txn_net = sum(
        (r["invested"] or 0) - (r["redeemed"] or 0)
        for r in txn_rows if r["scheme_type"] == "MF")

    where_man  = "WHERE 1=1"
    params_man = []
    if entity and entity != "All":
        where_man  += " AND entity=?"
        params_man  = [entity]

    man_rows = conn.execute(f"""
        SELECT scheme_type,
               SUM(CASE WHEN entry_type='Invested' THEN amount ELSE 0 END) as inv,
               SUM(CASE WHEN entry_type='Redeemed' THEN amount ELSE 0 END) as red
        FROM manual_investments
        {where_man}
        GROUP BY scheme_type
    """, params_man).fetchall()

    fd_man_net = sum(
        (r["inv"] or 0) - (r["red"] or 0)
        for r in man_rows if r["scheme_type"] == "FD")
    mf_man_net = sum(
        (r["inv"] or 0) - (r["red"] or 0)
        for r in man_rows if r["scheme_type"] == "MF")

    fd_balance = fd_opening + fd_txn_net + fd_man_net
    mf_balance = mf_opening + mf_txn_net + mf_man_net
    closing    = fd_balance + mf_balance

    conn.close()
    return {
        "opening":    total_opening,
        "fd_balance": fd_balance,
        "mf_balance": mf_balance,
        "closing":    closing,
    }


def get_entity_investment_balances():
    """
    Returns FD and MF balances per entity.
    Used for top banner and account balance summary.
    """
    result = {}
    for entity in ["Stores", "Ventures"]:
        kpis = get_investment_kpis(entity=entity)
        result[entity] = {
            "fd_balance": kpis["fd_balance"],
            "mf_balance": kpis["mf_balance"],
        }
    return result


def get_entity_bank_balance_asof(entity, as_of_date):
    """Bank balance for an entity AS ON a specific date."""
    conn = get_connection()
    banks = conn.execute(
        "SELECT DISTINCT bank FROM transactions WHERE entity=?",
        [entity]).fetchall()

    total = 0
    for b in banks:
        bank = b["bank"]
        row = conn.execute("""
            SELECT balance FROM transactions
            WHERE bank=? AND entity=?
            AND date <= ?
            AND final_group != 'OPENING BALANCE'
            AND balance IS NOT NULL
            ORDER BY date DESC, ord_key DESC LIMIT 1
        """, [bank, entity, as_of_date]).fetchone()

        if row and row["balance"] is not None:
            total += row["balance"]
        else:
            ob = conn.execute("""
                SELECT balance FROM transactions
                WHERE bank=? AND entity=?
                AND final_group='OPENING BALANCE'
                ORDER BY date DESC LIMIT 1
            """, [bank, entity]).fetchone()
            if ob and ob["balance"] is not None:
                total += ob["balance"]

    conn.close()
    return total


def get_entity_investment_asof(entity, as_of_date):
    """Combined FD+MF value for an entity AS ON a specific date."""
    conn = get_connection()

    reg_row = conn.execute("""
        SELECT SUM(opening_value) as total
        FROM investment_register WHERE entity=?
    """, [entity]).fetchone()
    opening = (reg_row["total"] or 0) if reg_row else 0

    txn_row = conn.execute("""
        SELECT
            ROUND(SUM(CASE WHEN debit>0  THEN debit  ELSE 0 END),2) as inv,
            ROUND(SUM(CASE WHEN credit>0 THEN credit ELSE 0 END),2) as red
        FROM transactions
        WHERE entity=?
        AND UPPER(main_group)='INVESTMENT'
        AND date <= ?
    """, [entity, as_of_date]).fetchone()
    txn_net = ((txn_row["inv"] or 0) - (txn_row["red"] or 0)) if txn_row else 0

    man_row = conn.execute("""
        SELECT
            SUM(CASE WHEN entry_type='Invested' THEN amount ELSE 0 END) as inv,
            SUM(CASE WHEN entry_type='Redeemed' THEN amount ELSE 0 END) as red
        FROM manual_investments
        WHERE entity=?
        AND entry_date <= ?
    """, [entity, as_of_date]).fetchone()
    man_net = ((man_row["inv"] or 0) - (man_row["red"] or 0)) if man_row else 0

    conn.close()
    return opening + txn_net + man_net


def get_data_integrity_report(today=None, since="2026-04-01"):
    """
    Detects statements that were never uploaded / only partly loaded.
    Checks dates from `since` (the live statement period; the FY2025-26 Excel import
    has no reliable day-level balances).

    breaks  : list of {bank, date, expected, actual, diff, after_gap, gap_days}
        For every loaded day: previous day's closing balance + credits - debits
        must equal that day's closing balance (the balance printed by the bank).
        A difference means transactions are missing (or duplicated).
    missing : list of {bank, from, to, days, kind}
        kind 'gap'        – days with no rows whose absence is confirmed by a balance
                            break on the next loaded day (busy accounts only; a quiet
                            day with genuinely no transactions is not flagged)
        kind 'not loaded' – nothing loaded for the most recent days (3+ days)
    """
    import pandas as pd

    today = today or datetime.date.today()
    conn = get_connection()
    df = pd.read_sql_query(
        "SELECT id, bank, date, debit, credit, balance FROM transactions "
        "WHERE final_group != 'OPENING BALANCE' AND date >= '2025-04-01' "
        "ORDER BY bank, date, ord_key", conn)
    conn.close()

    missing, breaks, daily_banks = [], [], []
    since_ts = pd.Timestamp(since)
    for bank, g in df.groupby("bank"):
        g = g.copy()
        g["d"] = pd.to_datetime(g["date"])
        dates = pd.DatetimeIndex(sorted(g["d"].unique()))
        if len(dates) < 30:
            continue

        # ── balance continuity, day by day ──
        day = g.groupby("d").agg(cr=("credit", "sum"), dr=("debit", "sum"))
        close = g.dropna(subset=["balance"]).groupby("d")["balance"].last()
        day = day.join(close.rename("close"), how="inner")
        bank_breaks, prev_close, prev_date = {}, None, None
        for d, r in day.iterrows():
            if prev_close is not None and d >= since_ts:
                expected = prev_close + r["cr"] - r["dr"]
                diff = round(r["close"] - expected, 2)
                if abs(diff) > 1:
                    bank_breaks[d] = {
                        "bank": bank, "date": d.strftime("%Y-%m-%d"),
                        "expected": round(expected, 2), "actual": round(r["close"], 2),
                        "diff": diff,
                        "after_gap": (d - prev_date).days > 1,
                        "gap_days": (d - prev_date).days - 1,
                    }
            prev_close, prev_date = r["close"], d
        breaks.extend(bank_breaks.values())

        # ── missing days (busy accounts only) ──
        recent = dates[dates >= dates.max() - pd.Timedelta(days=120)]
        span   = (dates.max() - max(dates.min(), dates.max() - pd.Timedelta(days=120))).days + 1
        if not (span > 0 and len(recent) / span >= 0.90):
            continue
        daily_banks.append(bank)
        live = dates[dates >= since_ts]
        if len(live):
            gaps = pd.date_range(live.min(), live.max(), freq="D").difference(dates)
            rng = []
            for d in gaps:
                if rng and (d - rng[-1][1]).days == 1:
                    rng[-1][1] = d
                else:
                    rng.append([d, d])
            for a_, b_ in rng:
                nxt = dates[dates > b_]
                if len(nxt) and nxt[0] in bank_breaks:      # absence confirmed by a balance break
                    missing.append({"bank": bank, "from": a_.strftime("%Y-%m-%d"),
                                    "to": b_.strftime("%Y-%m-%d"),
                                    "days": (b_ - a_).days + 1, "kind": "gap"})
        if (pd.Timestamp(today) - dates.max()).days >= 3:
            a_ = dates.max() + pd.Timedelta(days=1)
            b_ = pd.Timestamp(today) - pd.Timedelta(days=1)
            missing.append({"bank": bank, "from": a_.strftime("%Y-%m-%d"),
                            "to": b_.strftime("%Y-%m-%d"),
                            "days": (b_ - a_).days + 1, "kind": "not loaded"})

    missing.sort(key=lambda x: (x["from"], x["bank"]), reverse=True)
    breaks.sort(key=lambda x: (x["date"], x["bank"]), reverse=True)
    return {"missing": missing, "breaks": breaks, "daily_banks": daily_banks,
            "net_diff": round(sum(b["diff"] for b in breaks), 2)}


def get_latest_data_date():
    """Most recent transaction date in DB — used as default 'as on' date."""
    conn = get_connection()
    row = conn.execute("""
        SELECT MAX(date) as latest FROM transactions
        WHERE final_group != 'OPENING BALANCE'
    """).fetchone()
    conn.close()
    return row["latest"] if row and row["latest"] else None


def get_daywise_totals():
    """
    Day-by-day total balance for EVERY calendar day from the first transaction
    to the latest data date. Always all entities / all banks (no filters).

    Each row: date, bank, fd, mf, cash, total — the same components and the same
    as-on carry-forward rules as the header banner (get_entity_bank_balance_asof,
    get_entity_investment_asof, get_investment_mf_asof, get_cash_asof), so the
    last row equals the banner's Total Cash Position.
    Returns a list of dicts, newest date first.
    """
    import pandas as pd

    conn = get_connection()
    tx = pd.read_sql_query(
        "SELECT entity, bank, date, balance FROM transactions "
        "WHERE final_group != 'OPENING BALANCE' AND balance IS NOT NULL "
        "ORDER BY date, ord_key", conn)
    pairs = [(r["entity"], r["bank"]) for r in conn.execute(
        "SELECT DISTINCT entity, bank FROM transactions").fetchall()]
    ob = {}
    for r in conn.execute(
            "SELECT entity, bank, balance FROM transactions "
            "WHERE final_group='OPENING BALANCE' ORDER BY date").fetchall():
        if r["balance"] is not None:
            ob[(r["entity"], r["bank"])] = r["balance"]
    cash_rows = pd.read_sql_query(
        "SELECT entity, entry_date, value FROM cash_register_v2 ORDER BY entry_date", conn)
    conn.close()

    latest = get_latest_data_date()
    if tx.empty or not latest:
        return []
    days = pd.date_range(tx["date"].min(), latest, freq="D")
    tx["date"] = pd.to_datetime(tx["date"])

    # ── Bank: last balance on or before each day, per (entity, bank) ──────────
    bank_total = pd.Series(0.0, index=days)
    for pair in pairs:
        sub = tx[(tx["entity"] == pair[0]) & (tx["bank"] == pair[1])]
        s = sub.groupby("date")["balance"].last()
        s = s.reindex(s.index.union(days)).ffill().reindex(days)
        bank_total += s.fillna(ob.get(pair, 0.0))

    # ── FD / MF: opening + cumulative movements up to each day ────────────────
    ev = pd.DataFrame(get_investment_events(None))
    fd = pd.Series(0.0, index=days)
    mf = pd.Series(0.0, index=days)
    if not ev.empty:
        for stype, target in (("MF", mf), ("FD", fd)):
            e = ev[ev["scheme_type"] == stype] if stype == "MF" else ev[ev["scheme_type"] != "MF"]
            opening = e.loc[e["date"].isna(), "delta"].sum()
            d = e[e["date"].notna()].copy()
            d["date"] = pd.to_datetime(d["date"])
            mv = d.groupby("date")["delta"].sum()
            cum = mv.reindex(mv.index.union(days)).fillna(0).cumsum().reindex(days)
            target += opening + cum.fillna(0)

    # ── Cash at Stores: last entry on or before each day, per entity ─────────
    cash = pd.Series(0.0, index=days)
    if not cash_rows.empty:
        cash_rows["entry_date"] = pd.to_datetime(cash_rows["entry_date"])
        for _ent, g in cash_rows.groupby("entity"):
            s = g.groupby("entry_date")["value"].last()
            s = s.reindex(s.index.union(days)).ffill().reindex(days)
            cash += s.fillna(0.0)

    out = pd.DataFrame({"date": days.strftime("%Y-%m-%d"), "bank": bank_total.values,
                        "fd": fd.values, "mf": mf.values, "cash": cash.values})
    out["total"] = out["bank"] + out["fd"] + out["mf"] + out["cash"]
    return out.iloc[::-1].to_dict("records")


# ═════════════════════════ Capital gains: lots, FIFO, FD comparison ═════════════════════════

def _fund_type(text):
    t = (text or "").lower()
    if "arbitrage" in t:
        return "Arbitrage"
    if "money" in t:
        return "Money Market"
    if "liquid" in t:
        return "Liquid"
    return "Other"


def _scheme_key(name):
    import re
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _fy_label(date_str):
    y, m = int(date_str[:4]), int(date_str[5:7])
    start = y if m >= 4 else y - 1
    return f"FY {start}-{str(start + 1)[2:]}"


def get_fd_rate_card():
    conn = get_connection()
    rows = conn.execute("SELECT min_days, label, rate FROM fd_rate_card ORDER BY min_days").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_fd_rate_card(rows):
    """rows: list of {min_days, label, rate} — replaces the whole card."""
    conn = get_connection()
    conn.execute("DELETE FROM fd_rate_card")
    conn.executemany("INSERT INTO fd_rate_card (min_days, label, rate) VALUES (?,?,?)",
                     [(int(r["min_days"]), str(r["label"]), float(r["rate"])) for r in rows])
    conn.commit()
    conn.close()


def _slab_for_days(days, card):
    pick = card[0]
    for slab in card:
        if days >= slab["min_days"]:
            pick = slab
    return pick


def import_cg_sheet(filepath):
    """
    One-time load of the historical capital-gain workbook (one sheet per entity:
    names containing CKVPL/Ventures or CKSPL/Stores). Hidden sheets are ignored.
    Every lot is re-derived from the raw inputs (purchase date, units, NAV, sale date,
    units sold, sale NAV) — the sheet's own formulas are not trusted. Replaces all
    previously loaded historical lots.
    Returns {"loaded": {entity: n}, "skipped": n, "gain": {entity: gain}, "sheet_gain_diff": x, "errors": [...]}
    """
    import openpyxl
    import datetime as _dtm

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def dstr(v):
        if isinstance(v, _dtm.datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, _dtm.date):
            return v.strftime("%Y-%m-%d")
        return None

    try:
        wb = openpyxl.load_workbook(filepath, data_only=True)
    except Exception as exc:
        return {"loaded": {}, "skipped": 0, "gain": {}, "sheet_gain_diff": 0, "errors": [str(exc)]}

    lots, skipped, errors = [], 0, []
    sheet_gain = {}
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        up = ws.title.upper()
        entity = ("Ventures" if ("CKVPL" in up or "VENTURES" in up) else
                  "Stores" if ("CKSPL" in up or "STORES" in up) else None)
        if not entity:
            continue

        hdr_row, hdr = None, None
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=15, values_only=True), 1):
            vals = [str(v).strip().upper() if v is not None else "" for v in row]
            if "PURCHASE DATE" in vals and "UNITS SOLD" in vals:
                hdr_row, hdr = i, vals
                break
        if hdr is None:
            errors.append(f"Sheet '{ws.title}': header row (PURCHASE DATE / UNITS SOLD) not found")
            continue
        c_p = hdr.index("PURCHASE DATE")
        c_units, c_pnav = c_p + 1, c_p + 2
        c_sale = next(i for i in range(c_p + 1, len(hdr)) if hdr[i].startswith("DATE"))
        c_us = hdr.index("UNITS SOLD")
        c_snav = c_us + 1
        c_gain = hdr.index("CAP. GAIN") if "CAP. GAIN" in hdr else None
        c_rate = hdr.index("INTEREST %") if "INTEREST %" in hdr else None

        last_ft, last_raw = "Other", ""
        for row in ws.iter_rows(min_row=hdr_row + 1, values_only=True):
            row = list(row) + [None] * (len(hdr) + 2 - len(row))
            a = str(row[0]).strip() if row[0] else ""
            b = str(row[1]).strip() if row[1] else ""
            raw = b or (a if a and not a.upper().startswith("FY") else "")
            if raw:
                last_ft, last_raw = _fund_type(raw), raw
            pdt, sdt = dstr(row[c_p]), dstr(row[c_sale])
            units, pnav = num(row[c_units]), num(row[c_pnav])
            us, snav = num(row[c_us]), num(row[c_snav])
            if not (pdt and sdt and units and pnav and us and snav):
                if row[c_p] is not None or row[c_sale] is not None:
                    skipped += 1
                continue
            rate = num(row[c_rate]) if c_rate is not None else None
            lots.append((entity, last_ft, last_raw or last_ft, pdt, units, pnav, sdt, us, snav,
                         rate if rate else None))
            if c_gain is not None and num(row[c_gain]) is not None:
                sheet_gain[entity] = sheet_gain.get(entity, 0) + num(row[c_gain])

    if not lots:
        return {"loaded": {}, "skipped": skipped, "gain": {}, "sheet_gain_diff": 0,
                "errors": errors or ["No capital-gain lots found in the workbook."]}

    conn = get_connection()
    conn.execute("DELETE FROM mf_historical_lots")
    conn.executemany("""
        INSERT INTO mf_historical_lots
        (entity, fund_type, scheme_name, purchase_date, units, purchase_nav,
         sale_date, units_sold, sale_nav, fd_rate)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, lots)
    conn.commit()
    conn.close()

    loaded, gain = {}, {}
    for l in lots:
        loaded[l[0]] = loaded.get(l[0], 0) + 1
        gain[l[0]] = gain.get(l[0], 0) + (l[8] - l[5]) * l[7]
    diff = round(sum(gain.values()) - sum(sheet_gain.values()), 2) if sheet_gain else 0
    return {"loaded": loaded, "skipped": skipped,
            "gain": {k: round(v, 2) for k, v in gain.items()},
            "sheet_gain_diff": diff, "errors": errors}


def import_opening_lots(filepath):
    """
    Open (still held) purchase lots, loaded once so FIFO can match future redemptions.
    Columns: Entity | Scheme Name | Fund Type (optional) | Purchase Date | Units | NAV
    Replaces all previously loaded opening lots.
    """
    import pandas as pd
    try:
        df = pd.read_excel(filepath)
    except Exception as exc:
        return {"loaded": 0, "errors": [str(exc)]}
    df.columns = [str(c).strip() for c in df.columns]
    low = {c.lower(): c for c in df.columns}

    def col(*names):
        for n in names:
            if n in low:
                return low[n]
        return None

    c_ent, c_sch = col("entity"), col("scheme name", "scheme")
    c_ft, c_dt = col("fund type", "type"), col("purchase date", "date")
    c_un, c_nav = col("units"), col("nav", "purchase nav")
    missing = [n for n, c in [("Entity", c_ent), ("Scheme Name", c_sch), ("Purchase Date", c_dt),
                              ("Units", c_un), ("NAV", c_nav)] if c is None]
    if missing:
        return {"loaded": 0, "errors": [f"Missing columns: {missing}. Found: {list(df.columns)}"]}

    rows, errors = [], []
    for i, r in df.iterrows():
        try:
            ent = str(r[c_ent]).strip().title()
            if ent not in ("Stores", "Ventures"):
                raise ValueError(f"Entity must be Stores or Ventures, got '{r[c_ent]}'")
            sch = str(r[c_sch]).strip()
            dt = pd.to_datetime(r[c_dt]).strftime("%Y-%m-%d")
            units, nav = float(r[c_un]), float(r[c_nav])
            if units <= 0 or nav <= 0:
                raise ValueError("Units and NAV must be positive")
            ft = _fund_type(str(r[c_ft]) if c_ft and str(r[c_ft]) != "nan" else sch)
            rows.append((ent, sch, ft, dt, units, nav))
        except Exception as exc:
            errors.append(f"Row {i + 2}: {exc}")
    if errors:
        return {"loaded": 0, "errors": errors}
    conn = get_connection()
    conn.execute("DELETE FROM mf_opening_lots")
    conn.executemany("INSERT INTO mf_opening_lots (entity, scheme_name, fund_type, purchase_date, units, nav) "
                     "VALUES (?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    refresh_fifo_amounts()
    return {"loaded": len(rows), "errors": []}


def get_opening_lots():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM mf_opening_lots ORDER BY entity, scheme_name, purchase_date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compute_fifo(entity=None):
    """
    FIFO matching, recomputed from scratch from the inputs (so edits/deletes are always consistent):
      lots      = opening lots + MF 'Invested' entries that carry units and NAV
      redeems   = MF 'Redeemed' entries that carry units and NAV
    Each redemption consumes the oldest lots of the same entity+scheme first.
    Returns {"closed": [...], "open": [...], "unmatched": [...]}.
    """
    conn = get_connection()
    ent_sql, ent_p = "", []
    if entity and entity != "All":
        ent_sql, ent_p = " AND entity=?", [entity]

    events = []   # (date, order, seq, kind, payload)
    for r in conn.execute(f"SELECT * FROM mf_opening_lots WHERE 1=1{ent_sql}", ent_p).fetchall():
        events.append((r["purchase_date"], 0, r["id"], "P", dict(
            entity=r["entity"], scheme=r["scheme_name"], fund=r["fund_type"] or _fund_type(r["scheme_name"]),
            date=r["purchase_date"], units=r["units"], nav=r["nav"], src="Opening")))
    for r in conn.execute(
            f"SELECT * FROM manual_investments WHERE scheme_type='MF' AND units>0 AND nav>0{ent_sql} "
            f"ORDER BY entry_date, id", ent_p).fetchall():
        d = dict(entity=r["entity"], scheme=r["scheme_name"], fund=_fund_type(r["scheme_name"]),
                 date=r["entry_date"], units=r["units"], nav=r["nav"], entry_id=r["id"])
        if r["entry_type"] == "Invested":
            d["src"] = "Purchase"
            events.append((r["entry_date"], 0, r["id"] + 10_000_000, "P", d))
        else:
            events.append((r["entry_date"], 1, r["id"], "R", d))
    conn.close()
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    books, closed, unmatched = {}, [], []
    for _date, _o, _seq, kind, d in events:
        key = (d["entity"], _scheme_key(d["scheme"]))
        book = books.setdefault(key, [])
        if kind == "P":
            book.append(dict(d, left=d["units"]))
            continue
        need = d["units"]
        for lot in book:
            if need <= 1e-9:
                break
            if lot["left"] <= 1e-9 or lot["date"] > d["date"]:
                continue
            take = min(lot["left"], need)
            lot["left"] -= take
            need -= take
            closed.append(dict(
                entity=d["entity"], fund_type=d["fund"], scheme_name=d["scheme"],
                purchase_date=lot["date"], units=take, purchase_nav=lot["nav"],
                sale_date=d["date"], units_sold=take, sale_nav=d["nav"],
                fd_rate=None, source="FIFO", entry_id=d["entry_id"]))
        if need > 1e-6:
            unmatched.append(dict(entry_id=d["entry_id"], entity=d["entity"], scheme_name=d["scheme"],
                                  date=d["date"], units_short=round(need, 3), nav=d["nav"]))
    open_lots = [dict(l, units=l["left"]) for b in books.values() for l in b if l["left"] > 1e-6]
    return {"closed": closed, "open": open_lots, "unmatched": unmatched}


def refresh_fifo_amounts():
    """
    Keep manual_investments.amount (the balance impact, at cost) in step with FIFO for entries
    that carry units/NAV: purchase = units x NAV; redemption = FIFO cost consumed
    (units that could not be matched are valued at the redemption NAV).
    """
    res = compute_fifo(None)
    cost_by_entry = {}
    for l in res["closed"]:
        cost_by_entry[l["entry_id"]] = cost_by_entry.get(l["entry_id"], 0) + l["units_sold"] * l["purchase_nav"]
    short_by_entry = {u["entry_id"]: u["units_short"] * u["nav"] for u in res["unmatched"]}
    conn = get_connection()
    for r in conn.execute("SELECT id, entry_type, units, nav FROM manual_investments "
                          "WHERE scheme_type='MF' AND units>0 AND nav>0").fetchall():
        if r["entry_type"] == "Invested":
            amt = r["units"] * r["nav"]
        else:
            amt = cost_by_entry.get(r["id"], 0) + short_by_entry.get(r["id"], 0)
        conn.execute("UPDATE manual_investments SET amount=? WHERE id=?", [round(amt, 2), r["id"]])
    conn.commit()
    conn.close()


def get_capital_gain_lots(entity=None):
    """
    Every realised lot (historical sheet + FIFO from entries) with gain, days, ROI,
    annualised return and the FD comparison:
        FD interest = cost x FD rate x days / 365 (0 when held under 7 days, like the sheet)
        benefit     = gain - FD interest      (positive: the mutual fund beat an FD)
        missed      = FD interest - gain when positive (opportunity cost of choosing the MF)
    FD rate: the sheet's own rate when it has one, otherwise the rate card slab for the holding period.
    """
    import datetime as _dtm
    card = get_fd_rate_card()
    conn = get_connection()
    ent_sql, ent_p = "", []
    if entity and entity != "All":
        ent_sql, ent_p = " WHERE entity=?", [entity]
    hist = [dict(r) for r in conn.execute(f"SELECT * FROM mf_historical_lots{ent_sql}", ent_p).fetchall()]
    conn.close()
    rows = [dict(h, source="Sheet") for h in hist] + compute_fifo(entity)["closed"]

    out = []
    for r in rows:
        cost = r["units"] * r["purchase_nav"]
        proceeds = r["units_sold"] * r["sale_nav"]
        gain = proceeds - cost
        days = (_dtm.date.fromisoformat(r["sale_date"]) - _dtm.date.fromisoformat(r["purchase_date"])).days
        slab = _slab_for_days(days, card)
        rate = r.get("fd_rate") or slab["rate"]
        fd_days = days if days >= 7 else 0
        fd_int = cost * rate * fd_days / 365
        out.append(dict(
            entity=r["entity"], fund_type=r.get("fund_type") or "Other", scheme_name=r.get("scheme_name"),
            source=r["source"], purchase_date=r["purchase_date"], sale_date=r["sale_date"],
            units=r["units"], purchase_nav=r["purchase_nav"], sale_nav=r["sale_nav"],
            cost=cost, proceeds=proceeds, gain=gain, days=days,
            roi=gain / cost if cost else 0.0,
            ann=(gain / cost / days * 365) if (cost and days > 0) else 0.0,
            slab=slab["label"], slab_min=slab["min_days"], fd_rate=rate, fd_interest=fd_int,
            benefit=gain - fd_int, missed=max(0.0, fd_int - gain),
            fy=_fy_label(r["sale_date"]), month=r["sale_date"][:7]))
    out.sort(key=lambda x: (x["sale_date"], x["purchase_date"]))
    return out


if __name__ == "__main__":
    init_db()
