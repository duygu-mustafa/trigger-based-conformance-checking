"""DuckDB access to a large event-log file, one stay at a time.

BatchConformanceRunner opens a single Parquet or CSV file as a DuckDB view
(`events`) and holds the combined Declare model. main.py and api.py query
the view per stay (`runner.con`, keyed by `runner._batch_key_column`) and do the
episode segmentation and constraint evaluation themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb


class BatchConformanceRunner:
    """DuckDB view over one event file plus the Declare model to evaluate.

    A canonical event log (case_id/activity/timestamp columns) is keyed by
    case_id; a raw extraction file is keyed by stay_id.
    """

    def __init__(
        self,
        input_file: str | Path,
        model_builder: Any,
    ):
        self.input_file = Path(input_file)
        self.model = model_builder()
        self._is_event_log_input = False  
        self._batch_key_column = "stay_id"
        
        # Initialize DuckDB connection
        self.con = duckdb.connect(database=":memory:")
        self._setup_view()

    def _setup_view(self) -> None:
        """Create a DuckDB view over the input file for easy querying."""
        ext = self.input_file.suffix.lower()
        file_path = str(self.input_file).replace("'", "''")
        
        if ext in {".parquet", ".pq"}:
            self.con.execute(f"CREATE VIEW events AS SELECT * FROM read_parquet('{file_path}')")
        elif ext in {".csv", ".gz"}:
            self.con.execute(f"CREATE VIEW events AS SELECT * FROM read_csv_auto('{file_path}')")
        else:
            raise ValueError(f"Unsupported file format: {ext}")

        columns = {row[1] for row in self.con.execute("PRAGMA table_info('events')").fetchall()}
        # Canonical event-log inputs already have checker-ready columns.
        self._is_event_log_input = {"case_id", "activity", "timestamp"}.issubset(columns)
        self._batch_key_column = "case_id" if self._is_event_log_input else "stay_id"

    def get_stay_ids(self) -> list[str]:
        """Retrieve all unique batch ids from the source file."""
        rows = self.con.execute(
            f"SELECT DISTINCT {self._batch_key_column} FROM events "
            f"WHERE {self._batch_key_column} IS NOT NULL"
        ).fetchall()
        return [str(r[0]) for r in rows]
