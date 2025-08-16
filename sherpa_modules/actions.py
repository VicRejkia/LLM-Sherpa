import os
import re
from PySide6.QtWidgets import QFileDialog, QMessageBox
from .content_utils import get_checked_content, generate_tree_structure, generate_preamble
from .ui import SettingsWindow

def generate_markdown_action(main_window):
    """Handles the entire process of generating the final context.md file."""
    prompt_text = main_window._assemble_prompt()
    selected_content = get_checked_content(main_window)
    log_content = main_window.log_text_edit.toPlainText().strip()

    # Check if there's absolutely nothing to include
    if not selected_content and not prompt_text and not log_content:
        QMessageBox.information(main_window, "Info", "Nothing to generate.")
        return

    component_roles = main_window._get_component_roles()

    # Prompt user for save location
    project_name = os.path.basename(main_window.project_path)
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
            # Write Objective if present
            if prompt_text:
                f.write(f"# 🎯 Objective\n\n{prompt_text}\n\n---\n\n")
            else:
                f.write("# 🎯 Objective\n\n*No objective provided.*\n\n---\n\n")

            # Project Context Header
            f.write(f"## 📚 Project Context: `{project_name}`\n\n")

            # Add preamble if enabled and content exists
            if main_window.preamble_checkbox.isChecked() and selected_content:
                preamble = generate_preamble(selected_content)
                f.write(preamble + "\n\n")

            section_counter = 1

            # Console Log / Error Output
            if log_content:
                f.write(f"### {section_counter}. Console Log / Error Output\n\n```\n{log_content}\n```\n\n")
            else:
                f.write(f"### {section_counter}. Console Log / Error Output\n\n*No log output provided.*\n\n")
            section_counter += 1

            # Project Structure
            if main_window.settings_manager.get("show_project_structure") and selected_content:
                paths = [c['rel_path'] for c in selected_content]
                tree = generate_tree_structure(paths)
                f.write(f"### {section_counter}. Project Structure\n\n```\n{tree}\n```\n\n")
            else:
                f.write(f"### {section_counter}. Project Structure\n\n*Structure not included or no files selected.*\n\n")
            section_counter += 1

            # File Contents
            f.write(f"### {section_counter}. File Contents\n\n")
            if not selected_content:
                f.write("*No files were selected for inclusion.*\n\n")
            else:
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
        is_all_checked = all(root.child(i, 0).checkState() == Qt.CheckState.Checked for i in range(root.rowCount()))
        new_state = Qt.CheckState.Unchecked if is_all_checked else Qt.CheckState.Checked
        for i in range(root.rowCount()):
            item = root.child(i, 0)
            if item:
                # Use the tree_handler function to ensure hierarchical checking
                from . import tree_handler
                tree_handler.set_children_check_state(item, new_state)


def clean_logs_timestamps_action(text_edit):
    """Removes timestamps from the log text."""
    text = text_edit.toPlainText()
    pattern = re.compile(r"^\s*(?:\[.*?\])?\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?\s*-?\s*", re.MULTILINE)
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
