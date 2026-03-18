"""PostgreSQL connection helpers for MIMIC-IV queries."""

from __future__ import annotations

import os

import psycopg2


def get_postgres_connection():
    """Create a PostgreSQL connection using environment variables.

    Defaults match the local settings used in the notebooks.
    """
    return psycopg2.connect(
        user=os.getenv("MIMIC_DB_USER", "postgres"),
        password=os.getenv("MIMIC_DB_PASSWORD", "postgres"),
        host=os.getenv("MIMIC_DB_HOST", "127.0.0.1"),
        port=os.getenv("MIMIC_DB_PORT", "5432"),
        database=os.getenv("MIMIC_DB_NAME", "mimiciv"),
    )
