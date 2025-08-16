import os
from PySide6.QtCore import Qt

def get_code_from_item(item_data):
    """Extracts the source code for a given tree item from its file."""
    file_path = item_data.get('full_path', '')
    if not file_path: return ""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        if item_data.get('type') == 'file':
            return "".join(lines)
        elif item_data.get('type') in ('class', 'function'):
            start = item_data.get('start_line', 1) - 1
            end = item_data.get('end_line', len(lines))
            return "".join(lines[start:end])
    except (IOError, OSError):
        return ""
    return ""

def get_checked_content(main_window):
    """
    Gathers all code content from checked items in the tree, preventing duplicates.
    """
    content_map = {}
    processed_item_ids = set()

    def get_all_descendant_ids(item):
        descendant_ids = set()
        q = [item.child(i, 0) for i in range(item.rowCount())]
        while q:
            child = q.pop(0)
            if not child: continue
            child_data = child.data(Qt.UserRole)
            if child_data:
                descendant_ids.add(child_data.get('id'))
            if child.hasChildren():
                q.extend(child.child(i, 0) for i in range(child.rowCount()))
        return descendant_ids

    q = [main_window.tree_model.invisibleRootItem().child(i, 0) for i in range(main_window.tree_model.rowCount())]
    
    while q:
        item = q.pop(0)
        if not item: continue
        item_data = item.data(Qt.UserRole)
        if not item_data: continue
        
        item_id = item_data.get('id')
        if item_id in processed_item_ids: continue

        is_checked = item.checkState() == Qt.CheckState.Checked
        is_partially_checked = item.checkState() == Qt.CheckState.PartiallyChecked
        item_type = item_data.get('type')

        if is_checked and item_type in ('file', 'class', 'function'):
            file_path = item_data.get('full_path')
            if file_path:
                if file_path not in content_map:
                    content_map[file_path] = {'rel_path': os.path.relpath(file_path, main_window.project_path).replace(os.sep, '/'), 'snippets': []}
                
                content_map[file_path]['snippets'].append({
                    'content': get_code_from_item(item_data),
                    'name': item_data.get('name'),
                    'type': item_type
                })
            
            processed_item_ids.add(item_id)
            processed_item_ids.update(get_all_descendant_ids(item))

        elif item.hasChildren() and (is_checked or is_partially_checked):
            q.extend(item.child(i, 0) for i in range(item.rowCount()))

    final_content = []
    for path, data in content_map.items():
        is_full_file = any(snippet['type'] == 'file' for snippet in data['snippets'])
        if is_full_file:
            file_snippet = next(s for s in data['snippets'] if s['type'] == 'file')
            content = file_snippet['content']
        else:
            content = "\n\n# ... (snippet from file)\n\n".join(s['content'] for s in data['snippets'])

        final_content.append({
            'full_path': path,
            'rel_path': data['rel_path'],
            'content': content
        })
    return final_content

def generate_tree_structure(file_paths):
    """Generates an ASCII tree string from a list of file paths."""
    tree = {}
    lines = ["."]
    for path in file_paths:
        parts = path.replace(os.sep, '/').split('/')
        current_level = tree
        for part in parts:
            current_level = current_level.setdefault(part, {})
            
    def build_lines(d, prefix=""):
        items = sorted(d.keys())
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{item}{'/' if d[item] else ''}")
            if d[item]:
                build_lines(d[item], prefix + ("    " if is_last else "│   "))
    
    build_lines(tree)
    return "\n".join(lines)

def generate_preamble(selected_content):
    """Generates a 'Table of Contents' style preamble."""
    preamble = "This project briefing contains the following key files:\n"
    paths = sorted([c['rel_path'] for c in selected_content])
    for rel_path in paths:
        preamble += f"- `{rel_path}`\n"
    return preamble + "\n"
