"""Specification 016-A reporting over stored facts (D-072, entry review decisions D1-D12).

The modules here are pure and in memory: they take report inputs that the reporting service
read in one consistent database snapshot and return the complete report result.

- common: the report error, pagination, comparisons and exact amounts.
- periods: source-native calendar periods with an inclusive start and an exclusive end.
- catalog: the closed reporting catalog of metric classes (D3).
- digest: canonical hashing of report inputs and revisions (D7).
- social, spend and revenue: the three report families (D1).
- csv_export: the typed, bounded CSV serialization of a report result (D9).

Nothing here calls a provider, writes to the database, keeps a file or caches a result (D10).
Attribution, funnels, content revenue and ROAS stay dependency_unavailable (016-B).
"""
