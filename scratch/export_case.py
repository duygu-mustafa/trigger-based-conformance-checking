import pandas as pd
import json
import math
import yaml
from pathlib import Path

RELEVANT_ACTIVITIES = {
    'InvasiveVentilationStarted',
    'SBTStarted',
    'SBTCompleted',
    'SBTFailed',
    'SBTStopped',
    'Intubation',
    'Extubation',
    'SBTDeferred',
    'InvasiveVentilationEnded',
    'PaO2',
    'FiO2',
    'SpO2',
    'PEEP',
    'hemoglobin',
    'heart_rate',
    'sbp',
    'map',
    'respiratory_rate',
    'temperature_c'
}

def clean_val(v):
    if v is None: return None
    if isinstance(v, float) and math.isnan(v): return None
    return v

def load_constraints():
    constraints = {}
    config_dir = Path('configs/declare')
    for yaml_file in config_dir.glob('*.yaml'):
        if yaml_file.name == 'weights.yaml': continue
        with open(yaml_file, 'r') as f:
            data = yaml.safe_load(f)
            if not data or 'model' not in data: continue
            for c in data['model'].get('constraints', []):
                cid = c.get('id')
                if cid:
                    constraints[cid] = {
                        'label': c.get('label'),
                        'description': c.get('rationale'),
                        'min_gap_hours': c.get('min_gap_hours'),
                        'max_gap_hours': c.get('max_gap_hours'),
                        'template': c.get('template'),
                        'activation': c.get('activation'),
                        'target': c.get('target')
                    }
    return constraints

def export_case_data(case_id, event_log_path, results_path, output_path):
    # Load event log
    df = pd.read_parquet(event_log_path)
    case_df = df[df['case_id'] == str(case_id)].copy()
    case_df['timestamp'] = pd.to_datetime(case_df['timestamp'])
    
    # Filter for relevant activities
    filtered_df = case_df[case_df['activity'].isin(RELEVANT_ACTIVITIES)].copy()
    filtered_df = filtered_df.sort_values('timestamp')
    
    # Convert events to list of dicts
    events = []
    for _, row in filtered_df.iterrows():
        e = row.to_dict()
        e['timestamp'] = e['timestamp'].isoformat()
        for k in e:
            e[k] = clean_val(e[k])
        events.append(e)
    
    # Load results
    results_df = pd.read_csv(results_path)
    case_results = results_df[results_df['stay_id'] == int(case_id)].to_dict('records')
    for r in case_results:
        for k in r:
            r[k] = clean_val(r[k])
    
    data = {
        'case_id': str(case_id),
        'events': events,
        'conformance': case_results,
        'constraint_definitions': load_constraints()
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"Exported {len(events)} events, {len(case_results)} conformance episodes, and {len(data['constraint_definitions'])} constraints for case {case_id} to {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--case_id', type=str, default='35616431')
    args = parser.parse_args()
    
    export_case_data(
        args.case_id, 
        'data/icu_event_log.parquet', 
        'data/results/sample_results.csv', 
        Path(f'frontend/src/data/case_{args.case_id}.json')
    )
