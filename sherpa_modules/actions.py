import os
import re
from io import StringIO
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt
from .content_utils import get_checked_content, generate_tree_structure, generate_preamble
from .ui import SettingsWindow

def assemble_codebase_markdown(main_window):
    """Assembles the markdown content for the project codebase context."""
    selected_content = get_checked_content(main_window)
    log_content = main_window.log_text_edit.toPlainText().strip()
    component_roles = main_window._get_component_roles()
    project_name = os.path.basename(main_window.project_path) if main_window.project_path else "Project"

    has_any_context = bool(selected_content or log_content)
    if not has_any_context:
        return ""

    with StringIO() as context_f:
        context_f.write(f"## 📚 Project Context: `{project_name}`\n\n")

        if main_window.preamble_checkbox.isChecked() and selected_content:
            preamble = generate_preamble(selected_content)
            context_f.write(preamble + "\n\n")

        section_counter = 1
        if log_content:
            context_f.write(f"### {section_counter}. Console Log / Error Output\n\n```\n{log_content}\n```\n\n")
            section_counter += 1

        if main_window.settings_manager.get("show_project_structure") and selected_content:
            paths = [c['rel_path'] for c in selected_content]
            tree = generate_tree_structure(paths)
            context_f.write(f"### {section_counter}. Project Structure\n\n```\n{tree}\n```\n\n")
            section_counter += 1

        if selected_content:
            context_f.write(f"### {section_counter}. File Contents\n\n")
            ext_map = main_window.settings_manager.get("extension_map")
            for code_file in sorted(selected_content, key=lambda x: x['rel_path']):
                filename = os.path.basename(code_file['full_path'])
                rel_path = code_file['rel_path'].replace(os.sep, '/')
                lang = ext_map.get(os.path.splitext(filename)[1].lower(), "")
                context_f.write(f"#### 📄 `{filename}`\n")
                if rel_path in component_roles:
                    context_f.write(f"**Role:** {component_roles[rel_path]}\n\n")
                context_f.write(f"*path: `{rel_path}`*\n\n")
                content = code_file['content'].strip()
                if not content:
                    context_f.write("_This file is empty._\n\n")
                else:
                    context_f.write(f"```{lang}\n{content}\n```\n\n")
        
        return context_f.getvalue().strip()

def assemble_final_prompt(main_window):
    """
    Assembles the final prompt from the UI components, excluding the codebase.
    The codebase markdown is generated and saved separately. This function
    now just assembles the instructional part of the prompt.
    """
    prompt_text = main_window._assemble_prompt()
    return prompt_text.strip()

def save_codebase_markdown_action(main_window):
    """Handles generating and saving the codebase_context.md file."""
    markdown_content = assemble_codebase_markdown(main_window)
    
    if not markdown_content:
        QMessageBox.information(main_window, "Info", "Nothing to generate. Select some files first.")
        return

    project_name = os.path.basename(main_window.project_path) if main_window.project_path else "Project"
    default_filename = f"{project_name}_codebase_context.md"
    output_file, _ = QFileDialog.getSaveFileName(
        main_window,
        "Save Codebase Context File",
        default_filename,
        "Markdown Files (*.md)"
    )
    if not output_file:
        return

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        QMessageBox.information(main_window, "Success", f"Codebase context file saved at:\n{output_file}")
    except Exception as e:
        QMessageBox.critical(main_window, "Error", f"Failed to save file:\n{str(e)}")

def open_settings_action(main_window):
    """Opens the settings dialog and refreshes the UI if settings are changed."""
    dialog = SettingsWindow(main_window.settings_manager, main_window)
    if dialog.exec():
        main_window.token_budget_combo.clear()
        main_window.token_budget_combo.addItems(["No Budget"] + list(main_window.settings_manager.get("llm_token_budgets", {}).keys()))
        if main_window.project_path:
            main_window.refresh_project()

def toggle_all_selections_action(main_window):
    """Checks or unchecks all top-level items in the project tree."""
    root = main_window.tree_model.invisibleRootItem()
    if root.rowCount() > 0:
        is_any_not_fully_checked = any(root.child(i, 0).checkState() != Qt.CheckState.Checked for i in range(root.rowCount()))
        new_state = Qt.CheckState.Checked if is_any_not_fully_checked else Qt.CheckState.Unchecked
        
        main_window._is_updating_checks = True
        for i in range(root.rowCount()):
            item = root.child(i, 0)
            if item:
                from . import tree_handler
                tree_handler.set_children_check_state(item, new_state)
        main_window._is_updating_checks = False
        
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