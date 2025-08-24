from PySide6.QtCore import Qt

def get_tree_state(main_window):
    """Captures the checked and expanded states of the tree view."""
    checked_ids, expanded_ids = [], []
    
    # --- FIXED ---
    tree_model = main_window.project_view.model()
    tree_view = main_window.project_view.view()
    root = tree_model.invisibleRootItem()
    
    def recurse(parent_item):
        for row in range(parent_item.rowCount()):
            item = parent_item.child(row, 0)
            if not item: continue
            item_data = item.data(Qt.UserRole)
            if item_data:
                item_id = item_data.get('id')
                if item.checkState() in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked):
                    checked_ids.append(item_id)
                if item.hasChildren() and tree_view.isExpanded(item.index()):
                    expanded_ids.append(item_id)
            
            if item.hasChildren():
                recurse(item)
    
    recurse(root)
    return {"checked": checked_ids, "expanded": expanded_ids}

def restore_tree_state(main_window, state=None):
    """Restores the checked and expanded states from a state dictionary or the config."""
    if state is None:
        state = main_window.config_manager.get("tree_states", {}).get(main_window.project_path)
    
    if not state: return
    
    # --- FIXED ---
    tree_model = main_window.project_view.model()
    tree_view = main_window.project_view.view()
    
    main_window._is_updating_checks = True
    checked_set = set(state.get("checked", []))
    expanded_set = set(state.get("expanded", []))
    
    q = [tree_model.invisibleRootItem()]
    while q:
        parent_item = q.pop(0)
        for row in range(parent_item.rowCount()):
            item = parent_item.child(row, 0)
            if not item: continue
            item.setCheckState(Qt.CheckState.Unchecked)
            item_data = item.data(Qt.UserRole)
            if item_data:
                item_id = item_data.get('id')
                if item_id in checked_set:
                    item.setCheckState(Qt.CheckState.Checked)
                if tree_view.isExpanded(item.index()):
                    tree_view.collapse(item.index())
                if item_id in expanded_set:
                    tree_view.expand(item.index())

            if item.hasChildren():
                q.append(item)
    
    main_window._is_updating_checks = False
    
    root = tree_model.invisibleRootItem()
    for row in range(root.rowCount()):
        child_item = root.child(row, 0)
        if child_item:
            update_ancestor_check_state(child_item)

def set_children_check_state(item, state):
    """Recursively sets the check state for an item and all its children."""
    item.setCheckState(state)
    if item.hasChildren():
        for i in range(item.rowCount()):
            child = item.child(i, 0)
            if child:
                set_children_check_state(child, state)

def update_ancestor_check_state(item):
    """Updates the check state of parent items based on their children's states."""
    parent = item.parent()
    while parent:
        child_count = parent.rowCount()
        checked_count = 0
        partially_checked_count = 0
        for i in range(child_count):
            child = parent.child(i, 0)
            state = child.checkState()
            if state == Qt.CheckState.Checked:
                checked_count += 1
            elif state == Qt.CheckState.PartiallyChecked:
                partially_checked_count += 1
        
        if checked_count == child_count:
            parent.setCheckState(Qt.CheckState.Checked)
        elif checked_count > 0 or partially_checked_count > 0:
            parent.setCheckState(Qt.CheckState.PartiallyChecked)
        else:
            parent.setCheckState(Qt.CheckState.Unchecked)
        
        parent = parent.parent()

def on_item_changed(main_window, item):
    """Handles the logic when a tree item's check state changes."""
    if main_window._is_updating_checks:
        return
    
    main_window._is_updating_checks = True
    
    set_children_check_state(item, item.checkState())
    update_ancestor_check_state(item)
    
    main_window._is_updating_checks = False
    
    # --- MODIFIED: Call the new debounced update slot ---
    main_window.request_update()