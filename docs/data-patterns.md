# Data patterns: parser first, LLM for the remainder

Two patterns for turning semi-structured documents (bank statements, invoices,
receipts, exported reports) into reliable records without sending every
document to a model:

1. **Parser first.** Deterministic code (regex, a PDF table extractor, CSV or
   OFX readers) extracts each item and scores its confidence. Only the items
   the parser is unsure about go to an LLM.
2. **Cache by content hash.** Results are keyed by the SHA-256 of the file
   bytes plus the parser version, so unchanged files are never parsed twice.

Both patterns are shown with generic examples. No bank, ERP, or vendor is
assumed.

## 1. Parser first, LLM only for what is left

1. A deterministic parser extracts each item and returns `(value, confidence)`.
2. Confidence is a number from 0 to 1, built from checks the parser can run
   without a model:
   - all required fields were found;
   - each value has a valid format (date, identifier, amount);
   - the item's own parts add up (for example, quantity times unit price).

   Example: 3 of 3 fields found and all formats valid gives `0.95`. A missing
   field or an unexpected text layout gives `0.4`.
3. Items with `confidence >= 0.85` are accepted without a model call. Items
   below that threshold go to an LLM (a small model first, a larger one only if
   needed), together with the raw text snippet they came from.
4. The LLM answer goes through the same validation as step 2. If it fails,
   the item goes to human review and is listed in the report.
5. Count how many items were handled by the parser and how many by the LLM.
   That ratio is the savings metric: report it every run.

## 2. Check against independent totals

Never trust the items alone. The sum must close against a total that comes
from somewhere else in the document.

- **Account statement:** opening balance + credits - debits = closing balance.
- **Invoice:** sum of line items - discounts + taxes = invoice total.
- **Card or bill statement:** sum of charges = "total due" printed on the document.

Use `Decimal` with cents, never `float`, for these sums.

If the sum does not close, stop. Report the difference and the lowest-confidence
items. Do not adjust values to make the totals match.

## 3. Cache by SHA-256 of the content

- The key is the hash of the file **bytes** plus a parser version string.
  File name and modification date are not part of the key.
- If the content or the parser changes, the hash or version changes and the old
  entry is simply no longer read. There is no manual invalidation.
- A result that failed the total check (section 2) is not cached.

Schema for a local SQLite cache:

```sql
CREATE TABLE IF NOT EXISTS cache (
    hash      TEXT NOT NULL,
    parser    TEXT NOT NULL,
    result    TEXT NOT NULL,           -- JSON
    created   TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (hash, parser)
);
```

Python (standard library only):

```python
import hashlib
import json
import sqlite3
from pathlib import Path

PARSER_VERSION = "statement-v3"  # bump this whenever the parser logic changes

def open_cache(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        " hash TEXT NOT NULL, parser TEXT NOT NULL, result TEXT NOT NULL,"
        " created TEXT DEFAULT CURRENT_TIMESTAMP,"
        " PRIMARY KEY (hash, parser))"
    )
    return db

def read_with_cache(db: sqlite3.Connection, document: Path, parse, totals_close) -> dict:
    digest = hashlib.sha256(document.read_bytes()).hexdigest()
    row = db.execute(
        "SELECT result FROM cache WHERE hash = ? AND parser = ?",
        (digest, PARSER_VERSION),
    ).fetchone()
    if row is not None:
        return json.loads(row[0])

    # Parser first; the LLM is called inside `parse`, only for low-confidence items.
    result = parse(document)
    if not totals_close(result):
        raise ValueError(f"totals do not close for {document.name}; not cached")

    db.execute(
        "INSERT OR REPLACE INTO cache (hash, parser, result) VALUES (?, ?, ?)",
        (digest, PARSER_VERSION, json.dumps(result, ensure_ascii=False)),
    )
    db.commit()
    return result
```

`totals_close` is the check from section 2: it returns `False` when the
items do not add up to the independent total, and a failed result is never
written to the cache.

## 4. Applying the patterns

For each document type, the typical order is:

1. Compute the content hash and look it up. Hit: return the cached result.
2. Run the parser and score each item.
3. Send only the low-confidence items to the LLM and validate the answers.
4. Check the totals. Failure: report, do not cache.
5. Store the checked result and record the parser/LLM counts.
