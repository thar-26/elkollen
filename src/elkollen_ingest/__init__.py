"""Ingestion jobs for Elkollen. Each source writes append-only rows to the RAW layer."""

AREAS: tuple[str, ...] = ("SE1", "SE2", "SE3", "SE4")
