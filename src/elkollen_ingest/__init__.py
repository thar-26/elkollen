"""Ingestion jobs for Elkollen. Each source writes append-only rows to the RAW layer."""

from elkollen_ingest.elpris import AREAS

__all__ = ["AREAS"]
