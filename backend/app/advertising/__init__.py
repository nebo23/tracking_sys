"""Advertising spend and conversion delivery (specification 014, D-063 and D-064).

currencies holds the allow-listed spend currencies; spend stores and reads spend facts; roas is
the in-memory ROAS contract; delivery holds conversion destinations, the delivery outbox and
the worker's delivery step. Meta is the initial provider; every provider call goes through the
connector runtime and its adapters.
"""
