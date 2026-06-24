import pandas as pd, hashlib, sqlite3, sys
from config import DATABASE_FILE

FY_START    = '2025-04-01'
FY_END      = '2026-03-31'
ENTITY_MAP  = {'CKSPL': 'Stores', 'CKVPL': 'Ventures'}
ACCOUNT_MAP = {'8218': 'AXIS-8218', '7647': 'AXIS-7647', '5881': 'HDFC-5881',
               '5623': 'AXIS-5623', '7862': 'HDFC-7862', '7640': 'HDFC-7640'}

EXCEL_PATH = r'D:\Desktop\Claude\Bank Flow\Bank Flow\input Files\Bank Flow FY25-26.xlsx'


def make_fp(entity, bank, date, narr, debit, credit):
    raw = f'{entity}|{bank}|{date}|{narr}|{debit}|{credit}'
    return hashlib.md5(raw.encode()).hexdigest()


def clean_amt(v):
    if pd.isna(v) or str(v).strip() in ('', '-', 'nan', 'None'):
        return 0.0
    try:
        return abs(float(str(v).replace(',', '').strip()))
    except Exception:
        return 0.0


def clean_str(v):
    s = str(v or '').strip()
    return '' if s in ('-', 'nan', 'None') else s


def flush(conn, batch):
    u = nf = 0
    sql = """
        UPDATE transactions
        SET final_group=?, category=?, group_name=?, main_group=?, manually_overridden=1
        WHERE fingerprint=? AND financial_year='FY2526'
    """
    for fg, cat, grp, mg, fp in batch:
        r = conn.execute(sql, [fg, cat, grp, mg, fp])
        if r.rowcount > 0:
            u += 1
        else:
            nf += 1
    conn.commit()
    return u, nf


print(f'Reading {EXCEL_PATH}...')
df_raw = pd.read_excel(EXCEL_PATH, sheet_name='Sheet1', dtype=str, header=None)

header_row = None
for i, row in df_raw.iterrows():
    if 'Company' in str(row.values):
        header_row = i
        break

if header_row is None:
    print('[ERROR] Cannot find header row with Company column')
    sys.exit(1)

print(f'Header found at row index: {header_row}')
df_raw.columns = [str(c).strip() for c in df_raw.iloc[header_row]]
df = df_raw.iloc[header_row + 1:].reset_index(drop=True)

seen = {}
new_cols = []
for c in df.columns:
    if c in seen:
        seen[c] += 1
        new_cols.append(f'{c}_{seen[c]}')
    else:
        seen[c] = 0
        new_cols.append(c)
df.columns = new_cols

print(f'Rows to process: {len(df):,}')
visible_cols = [c for c in df.columns if not c.startswith('Unnamed')][:12]
print(f'Columns: {visible_cols}')

sample_date = df['Value Date'].iloc[0]
print(f'Sample date value: {repr(sample_date)}')

conn = sqlite3.connect(DATABASE_FILE)
updated = not_found = skipped = errors = 0
BATCH = 2000
batch = []

for idx, row in df.iterrows():
    try:
        company = str(row.get('Company') or '').strip().upper()
        entity = ENTITY_MAP.get(company)
        if not entity:
            skipped += 1
            continue

        acc = str(row.get('Account Number') or '').strip().replace('.0', '')
        last4 = acc[-4:] if len(acc) >= 4 else acc
        bank = ACCOUNT_MAP.get(last4)
        if not bank:
            skipped += 1
            continue

        date_raw = row.get('Value Date')
        if pd.isna(date_raw) or not str(date_raw).strip():
            skipped += 1
            continue
        try:
            date = pd.to_datetime(str(date_raw)).strftime('%Y-%m-%d')
        except Exception:
            skipped += 1
            continue
        if not (FY_START <= date <= FY_END):
            skipped += 1
            continue

        narr = str(row.get('Description') or '').strip()
        if not narr or narr in ('-', 'nan', 'None'):
            skipped += 1
            continue

        debit  = clean_amt(row.get('DebitAmount'))
        credit = clean_amt(row.get('CreditAmount'))
        if debit == 0 and credit == 0:
            skipped += 1
            continue

        fg  = clean_str(row.get('FINAL GROUP')) or 'Uncategorized'
        grp = clean_str(row.get('GROUP'))
        mg  = clean_str(row.get('MAIN GROUP'))
        if not mg:
            pr = clean_str(row.get('Payment/Receipt'))
            mg = pr if pr in ('Receipt', 'Payment') else ('Receipt' if credit > 0 else 'Payment')

        fp = make_fp(entity, bank, date, narr, debit, credit)
        batch.append((fg, fg, grp, mg, fp))

        if len(batch) >= BATCH:
            u, nf = flush(conn, batch)
            updated += u
            not_found += nf
            batch = []
            print(f'  {updated:,} updated | {not_found:,} not found...')

    except Exception as e:
        errors += 1
        if errors <= 5:
            print(f'  [ROW {idx} ERROR] {e}')

if batch:
    u, nf = flush(conn, batch)
    updated += u
    not_found += nf

conn.commit()

print()
print('=== RESULT ===')
print(f'Updated:   {updated:,}')
print(f'Not found: {not_found:,}')
print(f'Skipped:   {skipped:,}')
print(f'Errors:    {errors:,}')
print()

rows = conn.execute(
    "SELECT financial_year, COUNT(*) as cnt FROM transactions "
    "WHERE final_group='Uncategorized' GROUP BY financial_year ORDER BY financial_year"
).fetchall()
if rows:
    for r in rows:
        print(f'Uncategorized FY={r[0]}: {r[1]:,}')
else:
    print('Uncategorized: 0 rows across all FYs')

conn.close()
