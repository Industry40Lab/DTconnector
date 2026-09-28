import pandas as pd
import json
from typing import Dict, List, Any, Optional
from pathlib import Path


# JSON field names used in the YAML config -> internal keys of find_column_mapping
FIELD_TO_KEY = {'name': 'name', 'processingTime': 'duration', 'personnel': 'resources',
                'outline_level': 'outline_level', 'precedence': 'predecessors', 'materials': 'materials',
                'id': 'id', 'start': 'start', 'finish': 'finish'}


def load_column_rules(config_path: Optional[str]) -> Dict:
    """Read 'excel_column_mapping' (direct and regex rules) from to_json_config.yaml, if given."""
    if not config_path or not Path(config_path).exists():
        return {}
    import yaml
    with open(config_path, 'r', encoding='utf-8') as f:
        return (yaml.safe_load(f) or {}).get('excel_column_mapping', {}) or {}


def read_excel_project_data(excel_file_path: str, config_path: Optional[str] = None) -> Dict:
    """
    Read Excel file (MS Project export) and convert to UML-compliant JSON structure.
    
    Expected Excel structure:
    - Name: Task name
    - Duration: Processing time 
    - Resource Names: Personnel
    - Outline Level: For nesting tasks
    - Predecessors: Task dependencies
    - Other columns for materials, etc.
    
    Args:
        excel_file_path: Path to the Excel file
        
    Returns:
        Dictionary with UML-compliant structure
    """
    
    # Read Excel file
    try:
        df = pd.read_excel(excel_file_path)
        print(f"Excel file loaded successfully. Shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        
        # Display first few rows to understand structure
        print("\nFirst 5 rows:")
        print(df.head().to_string())
        
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return {}
    
    # Clean and prepare data
    df = df.dropna(how='all')  # Remove completely empty rows
    df = df.fillna('')  # Fill NaN values with empty strings
    
    # Identify key columns (case-insensitive matching)
    column_mapping = find_column_mapping(df.columns, load_column_rules(config_path))
    print(f"\nColumn mapping: {column_mapping}")
    
    # Parse tasks with hierarchy
    products = parse_tasks_with_hierarchy(df, column_mapping)
    
    # Create UML-compliant structure
    result = {
        "products": products
    }
    
    return result


def find_column_mapping(columns: List[str], rules: Optional[Dict] = None) -> Dict[str, str]:
    """Map Excel columns to our expected fields.

    Rules from the YAML config take precedence: first direct column-name mappings, then regular
    expressions on column names (to absorb naming variants across departments); built-in name
    patterns are used for anything still unmapped.
    """
    import re
    mapping = {}
    rules = rules or {}
    for col_name, field in (rules.get('direct') or {}).items():
        key = FIELD_TO_KEY.get(field)
        for col in columns:
            if key and key not in mapping and str(col).strip().lower() == str(col_name).strip().lower():
                mapping[key] = col
    for rule in (rules.get('patterns') or []):
        key = FIELD_TO_KEY.get(rule.get('field'))
        if not key or key in mapping:
            continue
        for col in columns:
            if re.match(rule.get('pattern', ''), str(col).strip(), re.IGNORECASE):
                mapping[key] = col
                break
    columns_lower = [col.lower().strip() for col in columns]
    
    # Define column name patterns
    patterns = {
        'name': ['name', 'task name', 'task', 'activity'],
        'duration': ['duration', 'processing time', 'proc time', 'work'],
        'resources': ['resource names', 'resources', 'personnel', 'assigned to'],
        'outline_level': ['outline level', 'level', 'wbs level'],
        'predecessors': ['predecessors', 'precedence', 'dependencies'],
        'materials': ['materials', 'items', 'parts'],
        'start': ['start', 'start date'],
        'finish': ['finish', 'finish date', 'end date'],
        'id': ['id', 'unique id', 'task id']
    }
    
    for field, pattern_list in patterns.items():
        if field in mapping:
            continue
        for pattern in pattern_list:
            for i, col in enumerate(columns_lower):
                if pattern in col:
                    mapping[field] = columns[i]  # Use original case
                    break
            if field in mapping:
                break
    
    return mapping


def parse_tasks_with_hierarchy(df: pd.DataFrame, column_mapping: Dict[str, str]) -> List[Dict]:
    """Parse tasks and build hierarchical structure based on outline levels."""
    products = []
    task_stack = []  # Stack to track parent tasks at each level
    
    for idx, row in df.iterrows():
        # Skip rows that don't have a name
        if not column_mapping.get('name') or not str(row.get(column_mapping['name'], '')).strip():
            continue
            
        # Extract basic task information
        task = extract_task_info(row, column_mapping)
        
        # Add unique ID based on row number
        task['id'] = int(idx) + 1  # 1-based indexing
        
        # Get outline level (default to 1 if not found)
        outline_level = 1
        if column_mapping.get('outline_level'):
            try:
                outline_level = int(row.get(column_mapping['outline_level'], 1))
            except (ValueError, TypeError):
                outline_level = 1
        
        task['outline_level'] = outline_level
        
        # Handle hierarchy based on outline level
        if outline_level == 1:
            # Top-level product
            product = create_product_from_task(task)
            products.append(product)
            task_stack = [product]
        else:
            # Sub-task - find appropriate parent
            while len(task_stack) >= outline_level:
                task_stack.pop()
            
            if task_stack:
                parent = task_stack[-1]
                if 'tasks' not in parent:
                    parent['tasks'] = []
                parent['tasks'].append(task)
                task_stack.append(task)
    
    return products


def extract_task_info(row: pd.Series, column_mapping: Dict[str, str]) -> Dict:
    """Extract task information from Excel row."""
    task = {}

    # Task name
    if column_mapping.get('name'):
        task['name'] = str(row.get(column_mapping['name'], '')).strip()

    # Processing time (duration)
    if column_mapping.get('duration'):
        duration_val = row.get(column_mapping['duration'], 0)
        try:
            # Handle different duration formats
            if isinstance(duration_val, str):
                # Remove common suffixes like 'days', 'hrs', etc.
                duration_val = duration_val.replace('days', '').replace('hrs', '').replace('h', '').strip()
                task['processingTime'] = float(duration_val) if duration_val else 0.0
            else:
                task['processingTime'] = float(duration_val) if duration_val else 0.0
        except (ValueError, TypeError):
            task['processingTime'] = 0.0
    else:
        task['processingTime'] = 0.0

    # Personnel (resources)
    personnel = []
    if column_mapping.get('resources'):
        resources_val = str(row.get(column_mapping['resources'], '')).strip()
        if resources_val:
            # Split by common delimiters
            personnel = [r.strip() for r in resources_val.replace(';', ',').split(',') if r.strip()]
    task['personnel'] = personnel

    # Predecessors
    precedence = []
    if column_mapping.get('predecessors'):
        pred_val = str(row.get(column_mapping['predecessors'], '')).strip()
        if pred_val:
            # Handle different predecessor formats (1,2,3 or A,B,C)
            precedence = [p.strip() for p in pred_val.replace(';', ',').split(',') if p.strip()]
    task['precedence'] = precedence

    # Materials
    materials = []
    if column_mapping.get('materials'):
        mat_val = str(row.get(column_mapping['materials'], '')).strip()
        if mat_val:
            materials = [m.strip() for m in mat_val.replace(';', ',').split(',') if m.strip()]
    task['materials'] = materials

    return task


def create_product_from_task(task: Dict) -> Dict:
    """Create a product structure from a top-level task."""
    product = {
        "Name": task['name'],
        "tasks": []
    }

    # Convert the task itself into a sub-task if it has processing details
    if task.get('processingTime', 0) > 0 or task.get('personnel') or task.get('materials'):
        sub_task = {k: v for k, v in task.items() if k != 'outline_level'}
        if not sub_task.get('name'):
            sub_task['name'] = 'Main Task'
        product['tasks'].append(sub_task)

    return product


def save_json_output(data: Dict, output_file_path: str) -> None:
    """Save data to JSON file with pretty formatting."""
    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def excel_to_json_converter(excel_file_path: str, output_file_path: str = None, 
                           config_path: str = None) -> str:
    """
    Main converter function.
    
    Args:
        excel_file_path: Path to Excel file
        output_file_path: Output JSON file path (auto-generated if not provided)
        config_path: Optional config for additional mappings
        
    Returns:
        JSON string
    """
    
    # Read and parse Excel data
    data = read_excel_project_data(excel_file_path, config_path)
    
    if not data:
        print("No data extracted from Excel file")
        return "{}"
    
    # Apply config mappings if provided
    if config_path and Path(config_path).exists():
        try:
            from json_to_xml_with_config import ConfigMapper
            config_mapper = ConfigMapper(config_path)
            # Apply reverse key mappings (XML keys back to JSON keys)
            data = apply_reverse_key_mappings(data, config_mapper)
        except ImportError:
            print("Config mapper not available, skipping config application")
    
    # Generate output file path if not provided
    if not output_file_path:
        excel_path = Path(excel_file_path)
        output_file_path = excel_path.parent / f"{excel_path.stem}_parsed.json"
    
    # Save to file
    save_json_output(data, output_file_path)
    
    # Convert to JSON string
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    
    print(f"\nConversion completed!")
    print(f"Input: {excel_file_path}")
    print(f"Output: {output_file_path}")
    print(f"Products found: {len(data.get('products', []))}")
    
    return json_str


def apply_reverse_key_mappings(data: Dict, config_mapper) -> Dict:
    """Apply reverse key mappings for consistency with XML output."""
    # This would reverse the key mappings from the config
    # For now, keeping it simple since the main mappings are:
    # processingTime -> procTime (we keep processingTime in JSON)
    # personnel -> hr (we keep personnel in JSON)
    return data


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Convert a production spreadsheet (task hierarchy) to JSON.")
    ap.add_argument("excel_file"); ap.add_argument("json_file")
    ap.add_argument("--config", default="to_json_config.yaml")
    a = ap.parse_args()
    excel_to_json_converter(a.excel_file, a.json_file, a.config)
