import json
from typing import Dict, List, Any, Set
from copy import deepcopy


def flatten_to_leaf_tasks(data: Dict) -> Dict:
    """
    Flatten hierarchical task structure to only leaf tasks (tasks with no children).
    Inherit resources from parent tasks to children.
    
    Args:
        data: JSON data with hierarchical task structure
        
    Returns:
        Modified data with only leaf tasks, inheriting parent resources
    """
    
    if not data.get('products'):
        return data
    
    flattened_products = []
    
    for product in data['products']:
        flattened_product = flatten_product_tasks(product)
        if flattened_product:
            flattened_products.append(flattened_product)
    
    return {
        "products": flattened_products
    }


def flatten_product_tasks(product: Dict) -> Dict:
    """Flatten tasks within a single product."""
    
    if not product.get('tasks'):
        return product
    
    # Create new product structure, preserving all product-level attributes
    flattened_product = deepcopy(product)
    
    # Reset tasks to empty list (will be populated with leaf tasks)
    flattened_product['tasks'] = []
    
    # Ensure standard fields exist
    if "MU" not in flattened_product:
        flattened_product["MU"] = ""
    if "Number" not in flattened_product:
        flattened_product["Number"] = 1
    if "Name" not in flattened_product:
        flattened_product["Name"] = ""
    
    # Collect all leaf tasks with inherited resources
    leaf_tasks = []
    collect_leaf_tasks(product.get('tasks', []), [], leaf_tasks)
    resolve_parent_predecessors(product.get('tasks', []), leaf_tasks)
    
    flattened_product['tasks'] = leaf_tasks
    
    return flattened_product


def collect_leaf_tasks(tasks: List[Dict], parent_resources: List[Dict], leaf_tasks: List[Dict]) -> None:
    """
    Recursively collect leaf tasks and inherit resources from parents.
    
    Args:
        tasks: List of tasks to process
        parent_resources: Accumulated resources from parent tasks
        leaf_tasks: Output list to collect leaf tasks
    """
    
    for task in tasks:
        # Create current resource context (parent + current task)
        current_resources = deepcopy(parent_resources)
        current_resources.append({
            'personnel': task.get('personnel', []),
            'materials': task.get('materials', []),
            'precedence': task.get('precedence', []),
            'processingTime': task.get('processingTime', 0.0),
            'id': task.get('id'),
            'name': task.get('name', '')
        })
        
        if task.get('tasks'):
            # Has children - recurse deeper
            collect_leaf_tasks(task['tasks'], current_resources, leaf_tasks)
        else:
            # Leaf task - inherit resources from all parents
            leaf_task = create_leaf_task_with_inheritance(task, current_resources)
            leaf_tasks.append(leaf_task)


def leaves_under(task: Dict) -> List[str]:
    """Names of the leaf tasks below a task (the task itself if it is a leaf)."""
    if not task.get('tasks'):
        return [task.get('name', '')]
    names = []
    for child in task['tasks']:
        names.extend(leaves_under(child))
    return names


def resolve_parent_predecessors(tasks: List[Dict], leaf_tasks: List[Dict]) -> None:
    """
    Parent tasks disappear when the hierarchy is flattened, so a predecessor that
    names a parent task is replaced by all the leaf tasks below that parent.
    A reference to one of the task's own ancestors is dropped, since it would
    make the task wait for itself.
    """
    parent_leaves = {}
    leaf_ancestors = {}

    def index(ts, chain):
        for t in ts:
            name = t.get('name', '')
            if t.get('tasks'):
                parent_leaves[name] = leaves_under(t)
                index(t['tasks'], chain + [name])
            else:
                leaf_ancestors[name] = set(chain)
    index(tasks, [])

    for leaf in leaf_tasks:
        ancestors = leaf_ancestors.get(leaf.get('name', ''), set())
        resolved = []
        for pred in leaf.get('precedence', []):
            if pred in ancestors:
                continue
            for name in parent_leaves.get(pred, [pred]):
                if name != leaf.get('name') and name not in resolved:
                    resolved.append(name)
        leaf['precedence'] = resolved


def create_leaf_task_with_inheritance(task: Dict, parent_resources: List[Dict]) -> Dict:
    """
    Create a leaf task with inherited resources from all parent levels.
    """
    
    # Start with the original task
    leaf_task = deepcopy(task)
    
    # Collect inherited resources
    inherited_personnel = set()
    inherited_materials = set()
    inherited_precedence = []
    inherited_processing_time = 0.0
    
    # Inherit from all parent levels
    for parent in parent_resources[:-1]:  # Exclude the task itself (last item)
        # Inherit personnel
        for person in parent.get('personnel', []):
            if person.strip():
                inherited_personnel.add(person.strip())
        
        # Inherit materials
        for material in parent.get('materials', []):
            if material.strip():
                inherited_materials.add(material.strip())
        
        # Inherit precedence: a parent's predecessors must be complete before
        # any of its leaf tasks can start
        for pred in parent.get('precedence', []):
            pred = pred.strip()
            if pred and pred not in inherited_precedence:
                inherited_precedence.append(pred)
        
        # Accumulate processing time from parents (if they don't have children)
        parent_time = parent.get('processingTime', 0.0)
        if parent_time > 0:
            inherited_processing_time += parent_time
    
    # Merge inherited resources with task's own resources
    task_personnel = set(p.strip() for p in task.get('personnel', []) if p.strip())
    task_materials = set(m.strip() for m in task.get('materials', []) if m.strip())
    
    # Combine inherited and task-specific resources
    all_personnel = list(inherited_personnel | task_personnel)
    all_materials = list(inherited_materials | task_materials)
    own_precedence = [p.strip() for p in task.get('precedence', []) if p.strip()]
    all_precedence = own_precedence + [p for p in inherited_precedence if p not in own_precedence]
    
    # Update leaf task with combined resources
    leaf_task['personnel'] = sorted(all_personnel)
    leaf_task['materials'] = sorted(all_materials)
    leaf_task['precedence'] = all_precedence
    
    # Use task's own processing time, or inherited time if task has none
    if task.get('processingTime', 0.0) == 0.0 and inherited_processing_time > 0:
        leaf_task['processingTime'] = inherited_processing_time
    
    # Remove hierarchical fields
    leaf_task.pop('tasks', None)
    leaf_task.pop('outline_level', None)
    
    # Add inheritance info for debugging (optional)
    if inherited_personnel or inherited_materials or inherited_precedence:
        leaf_task['_inheritance_info'] = {
            'inherited_personnel': sorted(inherited_personnel),
            'inherited_materials': sorted(inherited_materials),
            'inherited_precedence': inherited_precedence,
            'parent_chain': [p.get('name', f"ID-{p.get('id', 'unknown')}") for p in parent_resources[:-1]]
        }
    
    return leaf_task


def flatten_json_file(input_file: str, output_file: str = None) -> str:
    """
    Flatten a JSON file to contain only leaf tasks.
    
    Args:
        input_file: Path to input JSON file
        output_file: Path to output JSON file (auto-generated if not provided)
        
    Returns:
        JSON string of flattened data
    """
    
    # Load input data
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # Flatten the data
    flattened_data = flatten_to_leaf_tasks(data)
    
    # Generate output file path if not provided
    if not output_file:
        input_path = input_file.rsplit('.', 1)
        output_file = f"{input_path[0]}_flattened.{input_path[1] if len(input_path) > 1 else 'json'}"
    
    # Save flattened data
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(flattened_data, f, indent=2, ensure_ascii=False)
    
    # Generate statistics
    original_tasks = count_all_tasks(data)
    flattened_tasks = count_all_tasks(flattened_data)
    
    print(f"Flattening completed!")
    print(f"Input: {input_file} ({original_tasks} total tasks)")
    print(f"Output: {output_file} ({flattened_tasks} leaf tasks)")
    print(f"Reduction: {original_tasks - flattened_tasks} parent tasks removed")
    
    return json.dumps(flattened_data, indent=2, ensure_ascii=False)


def count_all_tasks(data: Dict) -> int:
    """Count total number of tasks in the data structure."""
    count = 0
    for product in data.get('products', []):
        count += count_tasks_recursive(product.get('tasks', []))
    return count


def count_tasks_recursive(tasks: List[Dict]) -> int:
    """Recursively count tasks."""
    count = len(tasks)
    for task in tasks:
        count += count_tasks_recursive(task.get('tasks', []))
    return count


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Flatten the hierarchical task JSON to leaf tasks.")
    ap.add_argument("json_file"); ap.add_argument("flattened_file")
    a = ap.parse_args()
    flatten_json_file(a.json_file, a.flattened_file)
