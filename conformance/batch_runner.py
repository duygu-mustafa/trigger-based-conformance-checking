"""Batch conformance runner for large-scale ICU event logs.

This module provides a class to process ICU events from a single large file
(Parquet or CSV) in batches grouped by stay_id, using DuckDB for efficient
filtering and streaming.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import duckdb
import pandas as pd
from tqdm import tqdm

from conformance.checker import check_log_conformance
from conformance.results import TraceResult
from derive import raw_to_event_log


class BatchConformanceRunner:
    """Processes ICU stay events in batches from a single source file."""

    def __init__(
        self,
        input_file: str | Path,
        model_builder: Any,
        item_dictionary_path: str | Path | None = None,
        activity_mapping_path: str | Path | None = None,
    ):
        self.input_file = Path(input_file)
        self.model = model_builder()
        self.item_dictionary_path = item_dictionary_path
        self.activity_mapping_path = activity_mapping_path
        
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

    def get_stay_ids(self) -> list[int]:
        """Retrieve all unique stay_ids from the source file."""
        rows = self.con.execute("SELECT DISTINCT stay_id FROM events WHERE stay_id IS NOT NULL").fetchall()
        return [int(r[0]) for r in rows]

    def process_batch(self, stay_ids: Iterable[int]) -> list[TraceResult]:
        """Process a specific batch of stay_ids."""
        results = []
        for stay_id in stay_ids:
            try:
                # Fetch only columns needed for the pipeline to save memory
                df = self.con.execute("SELECT * FROM events WHERE stay_id = ?", [stay_id]).df()
                
                if df.empty:
                    continue
                
                # 1. Transform raw data to event log
                event_log = raw_to_event_log(
                    df,
                    item_dictionary_path=self.item_dictionary_path,
                    activity_mapping_path=self.activity_mapping_path
                )
                
                # 2. Run conformance checker
                result = check_log_conformance(event_log, self.model)
                results.append(result)
            except Exception as e:
                print(f"Error processing stay_id {stay_id}: {e}")
                
        return results

    def run_all(self, batch_size: int = 100) -> list[TraceResult]:
        """Run conformance checking for all stay_ids in the file."""
        all_stay_ids = self.get_stay_ids()
        all_results = []
        
        for i in tqdm(range(0, len(all_stay_ids), batch_size), desc="Batch Processing"):
            batch = all_stay_ids[i:i + batch_size]
            all_results.extend(self.process_batch(batch))
            
        return all_results
