import json
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import Dict, List, Any, Union
import yaml
import re


class ConfigMapper:
    """Handles key and value mapping using flexible rules from YAML config."""
    
    def __init__(self, config_path: str = "to_xml_config.yaml"):
        """Load configuration from YAML file."""
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.key_mapping = self.config.get('key_mapping', {})
        self.value_mapping = self.config.get('value_mapping', {})
        self.predefined_data = self.config.get('predefined_data', {})
        self.settings = self.config.get('settings', {})
        self.case_sensitive = self.settings.get('case_sensitive', False)
        self.enable_regex = self.settings.get('enable_regex', True)
    
    def _apply_mapping_rules(self, input_value: str, mapping_config: dict) -> str:
        """
        Generic method to apply mapping rules (direct, aliases, patterns, fallback).
        
        Args:
            input_value: Value to map
            mapping_config: Configuration dict with direct, aliases, patterns, fallback
            
        Returns:
            Mapped value
        """
        if not self.case_sensitive:
            search_value = input_value
            value_lower = input_value.lower()
        else:
            search_value = input_value
            value_lower = input_value
        
        # 1. Direct mappings (exact match)
        direct = mapping_config.get('direct', {})
        if not self.case_sensitive:
            # Case insensitive search in direct mappings
            for key, value in direct.items():
                if key.lower() == value_lower:
                    return value
        else:
            if search_value in direct:
                return direct[search_value]
        
        # 2. Aliases (exact match in lists)
        aliases = mapping_config.get('aliases', [])
        for alias_group in aliases:
            sources = alias_group.get('sources', alias_group.get('names', []))  # Support both formats
            target = alias_group.get('target', alias_group.get('mu', ''))  # Support both formats
            
            if not self.case_sensitive:
                sources_lower = [s.lower() for s in sources]
                if value_lower in sources_lower:
                    return target
            else:
                if search_value in sources:
                    return target
        
        # 3. Patterns (regex match)
        if self.enable_regex:
            patterns = mapping_config.get('patterns', [])
            for pattern_rule in patterns:
                pattern = pattern_rule.get('pattern', '')
                template = pattern_rule.get('template', pattern_rule.get('mu_template', ''))  # Support both formats
                
                flags = 0 if self.case_sensitive else re.IGNORECASE
                match = re.match(pattern, search_value, flags)
                
                if match:
                    # Replace {match1}, {match2}, etc. with captured groups
                    result = template
                    for i, group in enumerate(match.groups(), 1):
                        result = result.replace(f'{{match{i}}}', group)
                        # Support .capitalize() and other string methods
                        result = result.replace(f'{{match{i}.capitalize()}}', group.capitalize())
                    return result
        
        # 4. Fallback
        fallback = mapping_config.get('fallback', {})
        if fallback.get('action') == 'keep_original':
            return input_value
        else:
            return fallback.get('target', fallback.get('mu', input_value))
    
    def map_key(self, key_name: str) -> str:
        """Map a JSON key name to XML key name using configured mappings."""
        return self._apply_mapping_rules(key_name, self.key_mapping)
    
    def map_value(self, value: str) -> str:
        """Map a JSON value to XML value using configured mappings."""
        return self._apply_mapping_rules(value, self.value_mapping)
    
    def product_mu(self, name: str) -> str:
        """MU path for a product (machine type): configured prefix + Plant-Simulation-safe name."""
        prefix = self.config.get('product_mu', {}).get('prefix', '.UserObjects.')
        return prefix + plant_sim_name(name) if name else ""

    def warehouse_settings(self) -> dict:
        """Field names used to read warehouse records (see 'warehouse' in to_xml_config.yaml)."""
        defaults = {'code_field': 'Code', 'quantity_field': 'Quantity',
                    'attributes': ['Area', 'Shelf Unit', 'Shelf Level'], 'mu_prefix': '.UserObjects.Parts.'}
        defaults.update(self.config.get('warehouse', {}) or {})
        return defaults

    def get_predefined_task_value(self, column_name: str):
        """Get predefined value for a task column, if configured."""
        task_columns = self.predefined_data.get('task_columns', {})
        return task_columns.get(column_name)


def dict_to_xml_element(data: Union[Dict, List, str, None], tag: str = "root") -> ET.Element:
    """Convert dictionary/list structure back to XML element."""
    element = ET.Element(tag)
    
    if data is None:
        return element
    elif isinstance(data, str):
        element.text = data
        return element
    elif isinstance(data, list):
        # Handle list by creating multiple child elements
        for i, item in enumerate(data):
            child = dict_to_xml_element(item, f"{tag}_item")
            element.append(child)
        return element
    elif isinstance(data, dict):
        # Define which properties should be XML attributes
        attribute_keys = {'XDim', 'YDim', 'Type', 'Name'}
        
        # Handle attributes (keys starting with @ or in attribute_keys) and special #text
        text_content = None
        
        for key, value in data.items():
            if key.startswith('@'):
                # Explicit attribute (with @ prefix)
                element.set(key[1:], str(value))
            elif key in attribute_keys:
                # Known attribute key
                element.set(key, str(value))
            elif key == '#text':
                text_content = value
            elif isinstance(value, list):
                # Multiple children with same tag
                for item in value:
                    child = dict_to_xml_element(item, key)
                    element.append(child)
            else:
                # Single child element
                child = dict_to_xml_element(value, key)
                element.append(child)
        
        if text_content:
            element.text = text_content
            
        return element
    else:
        element.text = str(data)
        return element


def json_to_xml_with_config(json_file_path: str, output_file_path: str = None, 
                           config_path: str = "to_xml_config.yaml", 
                           flatten_tasks: bool = True) -> str:
    """
    Convert JSON back to XML structure with mappings from config.
    
    Args:
        json_file_path: Path to the JSON file
        output_file_path: Optional path to save XML output
        config_path: Path to YAML configuration file
    
    Returns:
        XML string
    """
    
    # Load JSON
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    from flatten_tasks import flatten_to_leaf_tasks
    if flatten_tasks and isinstance(data, dict) and 'products' in data:
        data = flatten_to_leaf_tasks(data)
    
    # Initialize config mapper
    config_mapper = ConfigMapper(config_path)
    
    # Determine data type and use appropriate conversion
    if isinstance(data, list):
        # Warehouse records (one dict per stock record) - PlantSimulationTable with location attributes
        return warehouse_records_to_plant_simulation_table(data, config_mapper, output_file_path)
    if 'products' in data and isinstance(data['products'], list):
        # This is orders data - use PlantSimulationTable structure
        return json_to_plant_simulation_table(data, config_mapper, output_file_path, is_orders=True)
    elif 'PlantSimulationTable' in data:
        # This is warehouse data - use PlantSimulationTable structure  
        return json_to_plant_simulation_table(data, config_mapper, output_file_path, is_orders=False)
    else:
        # This is other data - use generic conversion
        return json_to_warehouse_xml_with_config(data, config_mapper, output_file_path)


def create_attributes_table_structure(attr_table: ET.Element, product: Dict = None) -> None:
    """Create the standard 18-column Attributes table structure."""
    # Attributes column headers
    attr_column_index = ET.SubElement(attr_table, "ColumnIndex", Type="string")
    attr_headers = ["Name of Attribute", "Integer", "Boolean", "String", "Real", "Time", "Date", 
                   "Datetime", "Object", "Length", "Weight", "Speed", "Acceleration", "Money", 
                   "Table", "List", "Stack", "Queue"]
    for header in attr_headers:
        cell = ET.SubElement(attr_column_index, "Cell")
        cell.text = header
    
    # Task attribute column
    task_attr_column = ET.SubElement(attr_table, "Column", Type="string")
    task_cell = ET.SubElement(task_attr_column, "Cell")
    task_cell.text = "Task"
    
    # Add product-level attributes to the last-column table format
    if product:
        standard_product_keys = {"Name", "MU", "Number", "tasks"}
        product_attrs = [(key, value) for key, value in product.items() if key not in standard_product_keys]
        for key, value in product_attrs:
            # Add attribute name to first column
            attr_name_cell = ET.SubElement(task_attr_column, "Cell")
            attr_name_cell.text = key
    
    ET.SubElement(task_attr_column, "Cell")  # Empty cell
    
    # Create columns for other attribute types
    attr_columns = {}
    attr_types = ["integer", "boolean", "string", "real", "time", "date", "datetime", 
                 "object", "length[m]", "weight[kg]", "speed[m/s]", "acceleration[m/s²]", "money[€]"]
    
    for attr_type in attr_types:
        column = ET.SubElement(attr_table, "Column", Type=attr_type)
        attr_columns[attr_type] = column
        # Add empty cell for Task row
        ET.SubElement(column, "Cell")
        
        # Add product-level attribute values in appropriate columns
        if product:
            standard_product_keys = {"Name", "MU", "Number", "tasks"}
            product_attrs = [(key, value) for key, value in product.items() if key not in standard_product_keys]
            for key, value in product_attrs:
                # Determine data type and add value to appropriate column
                cell = ET.SubElement(column, "Cell")
                if attr_type == "string" and isinstance(value, str):
                    cell.text = str(value)
                elif attr_type == "integer" and isinstance(value, int):
                    cell.text = str(value)
                elif attr_type == "real" and isinstance(value, (int, float)):
                    cell.text = str(float(value))
                elif attr_type == "boolean" and isinstance(value, bool):
                    cell.text = str(value).lower()
                # Add more type mappings as needed
        
        # Add final empty cell
        ET.SubElement(column, "Cell")


def collect_all_tasks(tasks: List[Dict]) -> List[Dict]:
    """Recursively collect all tasks from nested task structure."""
    all_tasks = []
    
    def collect_recursive(task_list):
        for task in task_list:
            # Add the task itself
            all_tasks.append(task)
            # Recursively collect from nested tasks
            if "tasks" in task and isinstance(task["tasks"], list):
                collect_recursive(task["tasks"])
    
    collect_recursive(tasks)
    return all_tasks


def create_task_table(task_table_column: ET.Element, tasks: List[Dict], config_mapper: ConfigMapper = None) -> None:
    """Create the Task table within the Attributes table based on actual task data."""
    if not tasks:
        ET.SubElement(task_table_column, "Cell")  # Empty cell if no tasks
        return
    
    # Analyze task data to determine all unique attributes and their types
    task_attributes = analyze_task_attributes(tasks, config_mapper)
    
    # Create task table with dynamic column count
    total_columns = len(task_attributes)
    task_table = ET.SubElement(task_table_column, "Table", Name="Task", XDim="-1", YDim="-1")
    
    # Task row index (task names)
    task_row_index = ET.SubElement(task_table, "RowIndex", Type="string")
    for task in tasks:
        cell = ET.SubElement(task_row_index, "Cell")
        cell.text = task.get("name", "")
    
    # Task column headers (dynamic based on data)
    task_column_index = ET.SubElement(task_table, "ColumnIndex", Type="string")
    for attr_name, _ in task_attributes:
        cell = ET.SubElement(task_column_index, "Cell")
        cell.text = attr_name
    
    # Create columns dynamically based on analyzed attributes
    for attr_name, attr_info in task_attributes:
        column = ET.SubElement(task_table, "Column", Type=attr_info["type"])
        
        # Populate column data for each task
        for task in tasks:
            cell = ET.SubElement(column, "Cell")
            
            # Check for predefined values first
            predefined_value = None
            if config_mapper:
                predefined_value = config_mapper.get_predefined_task_value(attr_name)
            
            # Use predefined value if available, otherwise get from task data
            if predefined_value is not None:
                value = predefined_value
            else:
                value = task.get(attr_info["source_key"], attr_info.get("default", ""))
            
            if attr_info["type"] == "list":
                # Always create a table for list columns (even if empty)
                list_table = ET.SubElement(cell, "Table", Name=task.get("name", ""), XDim="1", YDim="-1")
                if isinstance(value, list) and value:
                    # Populate the table if there are values
                    list_col = ET.SubElement(list_table, "Column", Type="string")
                    for item in value:
                        item_cell = ET.SubElement(list_col, "Cell")
                        item_cell.text = str(item)
                # Empty tables are left without columns (as in the reference format)
            elif attr_info["type"] == "boolean":
                cell.text = format_boolean_value(value)
            elif attr_info["type"] in ["real", "integer"]:
                cell.text = str(value) if value is not None else ("0" if attr_info["type"] == "integer" else "0.0")
            elif attr_info["type"] in ["time", "date", "datetime"]:
                cell.text = str(value) if value is not None else ""
            elif attr_info["type"] == "object":
                if isinstance(value, dict):
                    # For objects, could serialize as JSON or create nested structure
                    cell.text = str(value) if value is not None else ""
                else:
                    cell.text = str(value) if value is not None else ""
            else:  # string
                cell.text = str(value) if value is not None else ""
        
        # Add empty cell at the end
        ET.SubElement(column, "Cell")
    
    ET.SubElement(task_table_column, "Cell")  # Empty cell after task table


def analyze_task_attributes(tasks: List[Dict], config_mapper: ConfigMapper = None) -> List[tuple]:
    """
    Analyze tasks to determine all attributes, their types, and source keys.
    Returns list of (display_name, attribute_info) tuples in logical order.
    """
    if not tasks:
        return []
    
    # Standard attribute mappings (display_name -> source_key and type info)
    standard_mappings = [
        ("", {"source_key": "_empty", "type": "string", "default": ""}),  # First empty column
        ("procTime", {"source_key": "procTime", "type": "real", "default": 0.0, "alt_key": "processingTime"}),
        ("precedence", {"source_key": "precedence", "type": "list", "default": []}),
        ("materials", {"source_key": "materials", "type": "list", "default": []}),
        ("hr", {"source_key": "hr", "type": "list", "default": [], "alt_key": "personnel"}),
        ("Started", {"source_key": "Started", "type": "boolean", "default": False}),
        ("Completed", {"source_key": "Completed", "type": "boolean", "default": False})
    ]
    
    # Start with standard attributes in order
    result = []
    
    # Collect all unique keys from all tasks
    all_keys = set()
    for task in tasks:
        all_keys.update(task.keys())
    
    # Add standard attributes first (only if they exist in the data or are expected)
    for display_name, info in standard_mappings:
        source_key = info["source_key"]
        alt_key = info.get("alt_key")
        
        # Always include the first empty column and core attributes
        if source_key == "_empty":
            result.append((display_name, info))
        elif source_key in all_keys or (alt_key and alt_key in all_keys):
            # Update source_key to the one that actually exists in data
            if source_key not in all_keys and alt_key and alt_key in all_keys:
                info = info.copy()
                info["source_key"] = alt_key
            result.append((display_name, info))
    
    # Add non-standard attributes (attributes not covered by standard mappings)
    standard_source_keys = {info["source_key"] for _, info in standard_mappings}
    standard_source_keys.update({info.get("alt_key") for _, info in standard_mappings if info.get("alt_key")})
    standard_source_keys.add("name")  # name is handled separately in row index
    standard_source_keys.add("id")    # id is typically not displayed
    standard_source_keys.add("_empty")  # our placeholder
    
    non_standard_keys = sorted([key for key in all_keys if key not in standard_source_keys])
    
    for key in non_standard_keys:
        # Determine type by sampling values
        attr_type = determine_attribute_type(tasks, key)
        result.append((key, {"source_key": key, "type": attr_type, "default": get_default_value(attr_type)}))
    
    # Add predefined columns that don't exist in data
    if config_mapper:
        predefined_task_columns = config_mapper.predefined_data.get('task_columns', {})
        for column_name, default_value in predefined_task_columns.items():
            # Check if this column is already included
            if not any(display_name == column_name for display_name, _ in result):
                # Determine type from the predefined value
                if isinstance(default_value, bool):
                    column_type = "boolean"
                elif isinstance(default_value, int):
                    column_type = "integer"
                elif isinstance(default_value, float):
                    column_type = "real"
                elif isinstance(default_value, list):
                    column_type = "list"
                else:
                    column_type = "string"
                
                result.append((column_name, {
                    "source_key": column_name, 
                    "type": column_type, 
                    "default": default_value
                }))
    
    return result


def determine_attribute_type(tasks: List[Dict], attr_name: str) -> str:
    """
    Determine the appropriate column type for an attribute based on its values.
    Uses comprehensive type analysis across all tasks.
    """
    import re
    from datetime import datetime
    
    type_counts = {}
    sample_values = []
    
    # Collect all non-null values for this attribute
    for task in tasks:
        if attr_name in task and task[attr_name] is not None:
            value = task[attr_name]
            sample_values.append(value)
            
            # Count type occurrences
            if isinstance(value, bool):
                type_counts["boolean"] = type_counts.get("boolean", 0) + 1
            elif isinstance(value, int):
                type_counts["integer"] = type_counts.get("integer", 0) + 1
            elif isinstance(value, float):
                type_counts["real"] = type_counts.get("real", 0) + 1
            elif isinstance(value, list):
                type_counts["list"] = type_counts.get("list", 0) + 1
            elif isinstance(value, dict):
                type_counts["object"] = type_counts.get("object", 0) + 1
            elif isinstance(value, str):
                # Analyze string content for specialized types
                string_type = analyze_string_type(value)
                type_counts[string_type] = type_counts.get(string_type, 0) + 1
            else:
                type_counts["string"] = type_counts.get("string", 0) + 1
    
    if not type_counts:
        return "string"  # default for no data
    
    # Return the most common type, with priority for specialized types
    type_priority = ["time", "date", "datetime", "boolean", "integer", "real", "list", "object", "string"]
    
    for preferred_type in type_priority:
        if preferred_type in type_counts and type_counts[preferred_type] > 0:
            return preferred_type
    
    return "string"


def analyze_string_type(value: str) -> str:
    """Analyze a string value to determine if it represents a specialized type."""
    import re
    from datetime import datetime
    
    if not value or not isinstance(value, str):
        return "string"
    
    value = value.strip()
    
    # Check for time patterns (HH:MM:SS, HH:MM)
    time_patterns = [
        r'^\d{1,2}:\d{2}:\d{2}$',  # HH:MM:SS
        r'^\d{1,2}:\d{2}$',        # HH:MM
        r'^\d+\s*(h|hr|hours?|m|min|minutes?|s|sec|seconds?)$'  # 10h, 30min, etc.
    ]
    
    for pattern in time_patterns:
        if re.match(pattern, value, re.IGNORECASE):
            return "time"
    
    # Check for date patterns
    date_patterns = [
        r'^\d{4}-\d{2}-\d{2}$',    # YYYY-MM-DD
        r'^\d{2}/\d{2}/\d{4}$',    # MM/DD/YYYY
        r'^\d{2}-\d{2}-\d{4}$',    # MM-DD-YYYY
    ]
    
    for pattern in date_patterns:
        if re.match(pattern, value):
            return "date"
    
    # Check for datetime patterns
    datetime_patterns = [
        r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}',  # ISO datetime
        r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}',   # YYYY-MM-DD HH:MM:SS
    ]
    
    for pattern in datetime_patterns:
        if re.match(pattern, value):
            return "datetime"
    
    # Check for numeric strings that might be better as numbers
    try:
        float(value)
        return "real" if '.' in value else "integer"
    except ValueError:
        pass
    
    # Check for boolean strings
    if value.lower() in ['true', 'false', 'yes', 'no', '1', '0']:
        return "boolean"
    
    return "string"


def format_boolean_value(value) -> str:
    """Format a value as a boolean string."""
    if value is None:
        return "false"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str):
        return "true" if value.lower() in ['true', 'yes', '1'] else "false"
    if isinstance(value, (int, float)):
        return "true" if value != 0 else "false"
    return "false"


def get_default_value(attr_type: str):
    """Get default value for an attribute type."""
    defaults = {
        "boolean": False,
        "integer": 0,
        "real": 0.0,
        "list": [],
        "string": "",
        "time": "",
        "date": "",
        "datetime": "",
        "object": ""
    }
    return defaults.get(attr_type, "")


def json_to_plant_simulation_table(data: Dict, config_mapper: ConfigMapper, output_file_path: str = None, is_orders: bool = True) -> str:
    """Convert JSON to PlantSimulationTable XML structure (unified for orders and warehouse)."""
    
    # Apply mappings to the data
    data = apply_mappings(data, config_mapper)
    
    # Create root element
    root = ET.Element("PlantSimulationTable")
    
    # Create main table
    main_table = ET.SubElement(root, "Table", XDim="4", YDim="-1")
    
    # Column headers
    column_index = ET.SubElement(main_table, "ColumnIndex", Type="string")
    headers = ["MU", "Number", "Name", "Attributes"]
    for header in headers:
        cell = ET.SubElement(column_index, "Cell")
        cell.text = header
    
    # Get products from data
    if is_orders:
        products = data.get("products", [])
    else:
        # For warehouse data, extract from PlantSimulationTable structure
        table_data = data.get("PlantSimulationTable", {}).get("Table", {})
        columns = table_data.get("Column", [])
        if not isinstance(columns, list):
            columns = [columns]
        
        # Extract products from column structure
        products = []
        if len(columns) >= 3:
            mu_cells = columns[0].get("Cell", []) if columns[0].get("Type") == "object" else []
            num_cells = columns[1].get("Cell", []) if columns[1].get("Type") == "integer" else []
            name_cells = columns[2].get("Cell", []) if columns[2].get("Type") == "string" else []
            
            # Create products list from cells
            for i in range(min(len(mu_cells), len(num_cells), len(name_cells))):
                if mu_cells[i] and name_cells[i]:  # Skip empty cells
                    products.append({
                        "MU": mu_cells[i],
                        "Number": num_cells[i],
                        "Name": name_cells[i],
                        "tasks": []  # Warehouse doesn't have tasks
                    })
    
    # MU Column (products without an explicit MU get <prefix><name>, prefix from config)
    mu_column = ET.SubElement(main_table, "Column", Type="object")
    for product in products:
        cell = ET.SubElement(mu_column, "Cell")
        cell.text = product.get("MU") or config_mapper.product_mu(product.get("Name", ""))
    ET.SubElement(mu_column, "Cell")  # Empty cell
    
    # Number Column
    number_column = ET.SubElement(main_table, "Column", Type="integer")
    for product in products:
        cell = ET.SubElement(number_column, "Cell")
        cell.text = str(product.get("Number", ""))
    ET.SubElement(number_column, "Cell")  # Empty cell
    
    # Name Column
    name_column = ET.SubElement(main_table, "Column", Type="string")
    for product in products:
        cell = ET.SubElement(name_column, "Cell")
        cell.text = product.get("Name", "")
    ET.SubElement(name_column, "Cell")  # Empty cell
    
    # Attributes Column (contains task tables)
    attributes_column = ET.SubElement(main_table, "Column", Type="table")
    
    for product in products:
        # Create Attributes table for each product
        attr_table = ET.SubElement(attributes_column, "Table", Name="Attributes", XDim="18", YDim="-1")
        
        # Create standard attributes table structure
        create_attributes_table_structure(attr_table, product)
        
        # Task table column (14th column - index 13)
        task_table_column = ET.SubElement(attr_table, "Column", Type="table")
        
        # Create task table (only for orders data)
        if is_orders:
            tasks = collect_all_tasks(product.get("tasks", []))
            create_task_table(task_table_column, tasks, config_mapper)
        # For warehouse, just add empty cell
        else:
            ET.SubElement(task_table_column, "Cell")
        
        # Empty columns for remaining attribute types (list, stack, queue)
        ET.SubElement(attr_table, "Column", Type="list")
        ET.SubElement(attr_table, "Column", Type="stack")
        ET.SubElement(attr_table, "Column", Type="queue")
    
    # Add final empty cell to attributes column
    ET.SubElement(attributes_column, "Cell")
    
    # Convert to string with proper formatting
    xml_str = ET.tostring(root, encoding='unicode')
    
    # Pretty print
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="\t", encoding=None)
    
    # Remove empty lines and fix encoding declaration
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    if lines[0].startswith('<?xml'):
        lines[0] = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    pretty_xml = '\n'.join(lines)
    
    # Save to file if path provided
    if output_file_path:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
    
    return pretty_xml




def json_to_warehouse_xml_with_config(data: Dict, config_mapper: ConfigMapper, output_file_path: str = None) -> str:
    """Convert warehouse JSON to XML structure with config mappings."""
    
    # Apply mappings to the data
    data = apply_mappings(data, config_mapper)
    
    # Convert to XML
    if isinstance(data, dict) and len(data) == 1:
        # Single root element
        root_tag = list(data.keys())[0]
        root = dict_to_xml_element(data[root_tag], root_tag)
    else:
        # Multiple root elements or other structure
        root = dict_to_xml_element(data, "root")
    
    # Convert to string with proper formatting
    xml_str = ET.tostring(root, encoding='unicode')
    
    # Pretty print
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="\t", encoding=None)
    
    # Remove empty lines and fix encoding declaration
    lines = [line for line in pretty_xml.split('\n') if line.strip()]
    if lines[0].startswith('<?xml'):
        lines[0] = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    pretty_xml = '\n'.join(lines)
    
    # Save to file if path provided
    if output_file_path:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
    
    return pretty_xml


def plant_sim_name(value: str) -> str:
    """Plant Simulation object names cannot start with a digit: prefix such names with '_'."""
    value = str(value).strip()
    return "_" + value if value[:1].isdigit() else value


def _xml_type(values: List[Any]) -> str:
    """Integer column if every non-empty value is an integer, otherwise string."""
    non_empty = [v for v in values if v not in (None, "")]
    if non_empty and all(re.fullmatch(r"-?\d+", str(v).strip()) for v in non_empty):
        return "integer"
    return "string"


def warehouse_records_to_plant_simulation_table(records: List[Dict], config_mapper: ConfigMapper,
                                                output_file_path: str = None) -> str:
    """
    Convert warehouse stock records into a PlantSimulationTable.

    One row per record: MU (material object), Number (on-hand quantity), Name (material code) and an
    Attributes table holding the storage coordinates (by default Area, Shelf Unit, Shelf Level).
    Field names are read from the 'warehouse' section of to_xml_config.yaml.
    """
    ws = config_mapper.warehouse_settings()
    code_f, qty_f, attrs = ws['code_field'], ws['quantity_field'], list(ws['attributes'])

    root = ET.Element("PlantSimulationTable")
    main_table = ET.SubElement(root, "Table", XDim="4", YDim="-1")
    column_index = ET.SubElement(main_table, "ColumnIndex", Type="string")
    for header in ["MU", "Number", "Name", "Attributes"]:
        ET.SubElement(column_index, "Cell").text = header

    rows = [r for r in records if str(r.get(code_f, "")).strip()]
    names = [plant_sim_name(r[code_f]) for r in rows]

    mu_col = ET.SubElement(main_table, "Column", Type="object")
    num_col = ET.SubElement(main_table, "Column", Type="integer")
    name_col = ET.SubElement(main_table, "Column", Type="string")
    for r, name in zip(rows, names):
        mapped = config_mapper.map_value(str(r[code_f]).strip())
        ET.SubElement(mu_col, "Cell").text = mapped if mapped.startswith(".") else ws['mu_prefix'] + name
        qty = str(r.get(qty_f, "")).strip()
        ET.SubElement(num_col, "Cell").text = qty if re.fullmatch(r"-?\d+", qty) else "1"
        ET.SubElement(name_col, "Cell").text = name
    for col in (mu_col, num_col, name_col):
        ET.SubElement(col, "Cell")

    attr_col = ET.SubElement(main_table, "Column", Type="table")
    for r, name in zip(rows, names):
        t = ET.SubElement(attr_col, "Table", Name="Attributes", XDim="18", YDim="-1")
        ci = ET.SubElement(t, "ColumnIndex", Type="string")
        for h in ["Name of Attribute"] + attrs:
            ET.SubElement(ci, "Cell").text = h
        first = ET.SubElement(t, "Column", Type="string")
        ET.SubElement(first, "Cell").text = name
        for a in attrs:
            v = r.get(a, "")
            c = ET.SubElement(t, "Column", Type=_xml_type([v]))
            ET.SubElement(c, "Cell").text = "" if v is None else str(v).strip()
    ET.SubElement(attr_col, "Cell")

    dom = minidom.parseString(ET.tostring(root, encoding='unicode'))
    lines = [line for line in dom.toprettyxml(indent="\t").split('\n') if line.strip()]
    if lines and lines[0].startswith('<?xml'):
        lines[0] = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    pretty_xml = '\n'.join(lines)
    if output_file_path:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
    return pretty_xml


def apply_mappings(data: Dict, config_mapper: ConfigMapper) -> Dict:
    """
    Apply key and value mappings to JSON data structure.
    
    Args:
        data: JSON data dictionary
        config_mapper: Configured mapper instance
        
    Returns:
        Modified data with updated keys and values
    """
    # Deep copy to avoid modifying original
    import copy
    data = copy.deepcopy(data)
    
    # Apply key and value mappings recursively
    data = apply_recursive_mappings(data, config_mapper)
    
    # Apply specific value mappings for warehouse MU structure
    if 'PlantSimulationTable' in data and 'Table' in data['PlantSimulationTable']:
        table = data['PlantSimulationTable']['Table']
        
        # Find name and MU columns
        columns = table.get('Column', [])
        if not isinstance(columns, list):
            columns = [columns]
        
        name_column = None
        mu_column = None
        
        for i, col in enumerate(columns):
            if col.get('Type') == 'string':
                name_column = col
            elif col.get('Type') == 'object':
                mu_column = col
        
        # Apply value mapping to MU cells based on name cells
        if name_column and mu_column and 'Cell' in name_column and 'Cell' in mu_column:
            name_cells = name_column['Cell']
            mu_cells = mu_column['Cell']
            
            if isinstance(name_cells, list) and isinstance(mu_cells, list):
                for i, name in enumerate(name_cells):
                    if name and i < len(mu_cells):
                        new_mu = config_mapper.map_value(str(name))
                        mu_cells[i] = new_mu
    
    return data


def apply_recursive_mappings(data: Union[Dict, List, Any], config_mapper: ConfigMapper) -> Union[Dict, List, Any]:
    """
    Recursively apply key mappings to data structure.
    Value mappings are applied selectively, not globally.
    
    Args:
        data: Data structure to process
        config_mapper: Configured mapper instance
        
    Returns:
        Modified data with mapped keys
    """
    if isinstance(data, dict):
        new_dict = {}
        for key, value in data.items():
            # Map the key name
            new_key = config_mapper.map_key(key)
            # Recursively process the value (keys only)
            processed_value = apply_recursive_mappings(value, config_mapper)
            new_dict[new_key] = processed_value
        return new_dict
    elif isinstance(data, list):
        return [apply_recursive_mappings(item, config_mapper) for item in data]
    else:
        return data


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Convert pipeline JSON (production or warehouse) to Plant Simulation XML.")
    ap.add_argument("json_file"); ap.add_argument("xml_file")
    ap.add_argument("--config", default="to_xml_config.yaml")
    a = ap.parse_args()
    json_to_xml_with_config(a.json_file, a.xml_file, a.config)
    print(f"Written {a.xml_file}")
