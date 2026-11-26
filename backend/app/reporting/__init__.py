"""Specification 016 reporting over stored facts (016-A: D-072; 016-B: D-089).

The modules here are pure and in memory: they take report inputs that the reporting service
read in one consistent database snapshot and return the complete report result.

- common: the report error, pagination, comparisons, exact amounts and exact shares.
- periods: source-native calendar periods with an inclusive start and an exclusive end.
- catalog: the closed reporting catalog of metric classes (016 D3).
- digest: canonical hashing of report inputs and revisions (016 D7).
- social, spend and revenue: the three 016-A report families (016 D1).
- credit: the 016-B attribution family over stored 008-B credit.
- csv_export and credit_csv: the typed, bounded CSV serialization of a report result.

Nothing here calls a provider, writes to the database, keeps a file or caches a result.
"""
