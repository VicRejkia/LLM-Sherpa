import os
import re
from io import StringIO
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt
from .content_utils import get_checked_content, generate_tree_structure, generate_preamble
from .ui import SettingsWindow

def assemble_full_markdown(main_window):
    """Assembles the complete markdown content as a string for preview or saving."""
    prompt_text = main_window._assemble_prompt()
    selected_content = get_checked_content(main_window)
    log_content = main_window.log_text_edit.toPlainText().strip()
    component_roles = main_window._get_component_roles()
    project_name = os.path.basename(main_window.project_path) if main_window.project_path else "Project"

    has_any_context = bool(selected_content or log_content)

    with StringIO() as f:
        # 1. Objective (only if it exists)
        if prompt_text:
            f.write(f"# 🎯 Objective\n\n{prompt_text}\n\n")
            if has_any_context:
                f.write("---\n\n")

        # Stop here if there's nothing else to add
        if not has_any_context:
            return f.getvalue()

        # 2. Project Context section
        f.write(f"## 📚 Project Context: `{project_name}`\n\n")

        # Preamble
        if main_window.preamble_checkbox.isChecked() and selected_content:
            preamble = generate_preamble(selected_content)
            f.write(preamble + "\n\n")

        section_counter = 1

        # Console Log / Error Output (only if it exists)
        if log_content:
            f.write(f"### {section_counter}. Console Log / Error Output\n\n```\n{log_content}\n```\n\n")
            section_counter += 1

        # Project Structure (only if enabled and files are selected)
        if main_window.settings_manager.get("show_project_structure") and selected_content:
            paths = [c['rel_path'] for c in selected_content]
            tree = generate_tree_structure(paths)
            f.write(f"### {section_counter}. Project Structure\n\n```\n{tree}\n```\n\n")
            section_counter += 1

        # File Contents (only if files are selected)
        if selected_content:
            f.write(f"### {section_counter}. File Contents\n\n")
            ext_map = main_window.settings_manager.get("extension_map")
            for code_file in sorted(selected_content, key=lambda x: x['rel_path']):
                filename = os.path.basename(code_file['full_path'])
                rel_path = code_file['rel_path'].replace(os.sep, '/')
                lang = ext_map.get(os.path.splitext(filename)[1].lower(), "")

                f.write(f"#### 📄 `{filename}`\n")
                if rel_path in component_roles:
                    f.write(f"**Role:** {component_roles[rel_path]}\n\n")
                f.write(f"*path: `{rel_path}`*\n\n")

                content = code_file['content'].strip()
                if content == "":
                    f.write("_This file is empty._\n\n")
                else:
                    f.write(f"```{lang}\n{content}\n```\n\n")
        
        return f.getvalue()

def generate_markdown_action(main_window):
    """Handles generating and saving the final context.md file."""
    markdown_content = assemble_full_markdown(main_window).strip()
    
    if not markdown_content:
        QMessageBox.information(main_window, "Info", "Nothing to generate.")
        return

    # Prompt user for save location
    project_name = os.path.basename(main_window.project_path) if main_window.project_path else "Project"
    default_filename = f"{project_name}_context.md"
    output_file, _ = QFileDialog.getSaveFileName(
        main_window,
        "Save Context File",
        default_filename,
        "Markdown Files (*.md)"
    )
    if not output_file:
        return  # User canceled

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        QMessageBox.information(main_window, "Success", f"Context file generated at:\n{output_file}")
    except Exception as e:
        QMessageBox.critical(main_window, "Error", f"Failed to generate documentation:\n{str(e)}")

def open_settings_action(main_window):
    """Opens the settings dialog and refreshes the UI if settings are changed."""
    dialog = SettingsWindow(main_window.settings_manager, main_window)
    if dialog.exec():
        main_window.prompt_template_combo.clear()
        main_window.prompt_template_combo.addItems(["Custom Prompt"] + list(main_window.settings_manager.get("prompt_templates", {}).keys()))
        main_window.token_budget_combo.clear()
        main_window.token_budget_combo.addItems(["No Budget"] + list(main_window.settings_manager.get("llm_token_budgets", {}).keys()))
        main_window.task_selector_combo.clear()
        main_window.task_selector_combo.addItems(main_window.settings_manager.get("prompt_modules", {}).keys())
        if main_window.project_path:
            main_window.refresh_project()

def toggle_all_selections_action(main_window):
    """Checks or unchecks all top-level items in the project tree."""
    root = main_window.tree_model.invisibleRootItem()
    if root.rowCount() > 0:
        # Determine the target state based on whether at least one item is unchecked.
        # If all are fully checked, the new state is Unchecked. Otherwise, it's Checked.
        is_any_not_fully_checked = any(root.child(i, 0).checkState() != Qt.CheckState.Checked for i in range(root.rowCount()))
        new_state = Qt.CheckState.Checked if is_any_not_fully_checked else Qt.CheckState.Unchecked
        
        main_window._is_updating_checks = True
        for i in range(root.rowCount()):
            item = root.child(i, 0)
            if item:
                from . import tree_handler # Local import to avoid circular dependency at module level
                tree_handler.set_children_check_state(item, new_state)
        main_window._is_updating_checks = False
        
        # Manually trigger the update after batch changes
        main_window._on_content_changed()

def clean_logs_timestamps_action(text_edit):
    """Removes timestamps from the log text."""
    text = text_edit.toPlainText()
    pattern = re.compile(r"^\s*(?:\[.*?\])?\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?\s*-?\s*", re.MULTLINE)
    text = pattern.sub('', text)
    text = "\n".join(line for line in text.splitlines() if line.strip())
    text_edit.setPlainText(text.strip())

def clean_logs_ansi_action(text_edit):
    """Removes ANSI escape codes from the log text."""
    text = text_edit.toPlainText()
    ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    text = re.sub(r'\n\s*\n+', '\n', text)
    text_edit.setPlainText(text.strip())

def collapse_duplicates_action(text_edit):
    """Collapses duplicate lines in the log text, showing a count."""
    lines = [line.strip() for line in text_edit.toPlainText().splitlines() if line.strip()]
    seen, order = {}, []
    for line in lines:
        if line not in seen:
            seen[line] = 1
            order.append(line)
        else:
            seen[line] += 1
    new_lines = [f"{line} (x{seen[line]})" if seen[line] > 1 else line for line in order]
    text_edit.setPlainText("\n".join(new_lines))