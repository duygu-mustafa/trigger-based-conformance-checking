import pandas as pd
import json
from pathlib import Path

def export_case_data(case_id, event_log_path, output_path):
    df = pd.read_parquet(event_log_path)
    case_df = df[df['case_id'] == str(case_id)].copy()
    case_df['timestamp'] = pd.to_datetime(case_df['timestamp'])
    case_df = case_df.sort_values('timestamp')
    
    # Convert to list of dicts with string timestamps
    events = case_df.to_dict('records')
    for e in events:
        e['timestamp'] = e['timestamp'].isoformat()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(events, f, indent=2)
    print(f"Exported {len(events)} events for case {case_id} to {output_path}")

if __name__ == "__main__":
    export_case_data('35616431', 'data/icu_event_log.parquet', Path('frontend/src/data/case_35616431.json'))
