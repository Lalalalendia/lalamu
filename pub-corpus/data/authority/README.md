# External authority

Lalamu deduplicates candidate PUB files against the current complete-file authority maintained in `HeisLuka/rar`.

Pinned baseline:

- commit: `8751688f1509397f4d2c591e6f7b12d6a9fed4a5`
- path: `tools/corpus/receipts/current-rar-1521.sha256.txt`
- expected entries: `1521`

The ingestion script fails closed if the fetched authority does not contain exactly 1,521 distinct SHA-256 values.

This file documents the dependency only; the authority remains owned by Rar and is not rewritten by Lalamu.
