# PUB corpus lane

Independent acquisition lane for Microsoft Publisher `.pub` files.

## Admission pipeline

```
discover -> exact-byte fetch -> SHA-256 -> CFB validation
         -> Publisher structural hints -> completeness/readability
         -> dedup against pinned Rar authority + local corpus
         -> retain bytes + provenance manifest
```

The current external dedup authority is pinned to:

- repository: `HeisLuka/rar`
- commit: `8751688f1509397f4d2c591e6f7b12d6a9fed4a5`
- receipt: `tools/corpus/receipts/current-rar-1521.sha256.txt`
- expected exact SHA count: **1,521**

That authority is read-only. Lalamu owns only its independent discovery/provenance lane.

## Rules

- A `.pub` suffix is never enough for admission.
- Exact writer/version is never inferred from a filename or page wording.
- Downloaded bytes must be a readable CFB container.
- Every declared stream must be readable at its declared length.
- Publisher-specific structural evidence must be present.
- Exact SHA-256 duplicates are rejected.
- Historical locators remain candidates until exact bytes are recovered and pass the same gates.

## Layout

```
data/
  candidates.json
  manifest.jsonl         # created when the first novel file is admitted
  authority/README.md
scripts/
  ingest_candidates.py
corpus/
  native/unclassified/   # SHA-named admitted .pub bytes
```

The GitHub Actions workflow runs the bounded candidate queue and commits only newly admitted artifacts.
