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
    project_description = main_window.project_description_text_edit.toPlainText().strip()

    has_any_context = bool(selected_content or log_content or project_description)
    if not has_any_context:
        return ""

    with StringIO() as context_f:
        if project_description:
            context_f.write(f"## 📝 Project Description\n\n{project_description}\n\n---\n\n")

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
        main_window.settings_manager.save_settings()
        QMessageBox.information(
            main_window,
            "Settings Saved",
            "Your settings have been saved. Some changes may require a project refresh to take effect."
        )
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

import re

def clean_logs_timestamps_action(text_edit):
    """Removes various timestamp formats from the start of log lines."""
    text = text_edit.toPlainText()
    
    # Comprehensive regex for various timestamp formats
    timestamp_pattern = re.compile(
        r'^[\[\(]?\s*'  # Optional opening bracket/paren with whitespace
        r'('
        # Standard date-time formats
        r'\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?|'  # ISO 8601 with timezone
        r'\d{2}/\d{2}/\d{2,4}\s+\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?|'  # MM/DD/YY(YY) HH:MM:SS
        r'\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?|'  # M/D/YY(YY) H:MM:SS
        r'\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|'  # YYYY/MM/DD HH:MM:SS
        
        # Named month formats
        r'(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?\s+\d{4}|'  # Day Month DD HH:MM:SS YYYY
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?|'  # Month DD HH:MM:SS
        r'\d{1,2}/(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)/\d{4}:\d{2}:\d{2}:\d{2}|'  # DD/Mon/YYYY:HH:MM:SS
        
        # Time-only formats (often found in logs)
        r'\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?(?:\s*[AP]M)?|'  # HH:MM:SS(.fff) (AM/PM)
        
        # Python logging format timestamps like [08/15/25 12:15:11]
        r'\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?|'  # MM/DD/YY HH:MM:SS
        
        # Epoch/Unix timestamps
        r'\d{10,13}(?:[.,]\d+)?|'  # Unix timestamp (10-13 digits)
        
        # Custom format like "2025-08-15 04:47:55,737"
        r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d{3,6})?'  # YYYY-MM-DD HH:MM:SS.fff
        r')'
        r'\s*[\]\)]?'  # Optional closing bracket/paren
        r'[\s\-:]*'    # Optional separators and whitespace
        , re.MULTILINE
    )
    
    cleaned_lines = []
    for line in text.splitlines():
        # Remove timestamp from beginning of line
        cleaned_line = timestamp_pattern.sub('', line).strip()
        # Only add non-empty lines
        if cleaned_line:
            cleaned_lines.append(cleaned_line)
    
    text_edit.setPlainText("\n".join(cleaned_lines))

def clean_logs_ansi_action(text_edit):
    """Removes ANSI codes, decorators, dividers, and excess whitespace."""
    text = text_edit.toPlainText()
    
    # 1. Remove ANSI escape codes (comprehensive pattern)
    ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\))')
    text = ansi_escape.sub('', text)
    
    # 2. Remove progress bars and percentage indicators (be more specific)
    # Only match actual progress bars, not random numbers at start of lines
    progress_pattern = re.compile(r'^\s*\d+%\s*\|[█▓▒░\|\s]*\|\s*\d+/\d+|^\s*\d+%\s*\|[█▓▒░\s]*$')
    
    # 3. Pattern for decorator lines (dividers, box drawing, repeated characters)
    decorator_patterns = [
        re.compile(r'^[\s\-=_+~#*]{4,}$'),  # Lines of repeated chars like ---, ===, +++
        re.compile(r'^[\u2500-\u257F\u2580-\u259F\s]+$'),  # Box drawing characters
        re.compile(r'^\s*[|┌┐└┘├┤┬┴┼╔╗╚╝╠╣╦╩╬╭╮╰╯│─═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬]+\s*$'),  # Extended box drawing
        re.compile(r'^\s*[▀▄▌▐█▓▒░]+\s*$'),  # Block characters
        re.compile(r'^[\s─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋╌╍╎╏═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬╭╮╯╰╱╲╳╴╵╶╷╸╹╺╻╼╽╾╿]+$'),  # Comprehensive box drawing
        #re.compile(r'^\s*[❱❯►▶]+.*$'),  # Arrow indicators (like error pointers)
        re.compile(r'^.*─+.*Traceback.*─+.*$'),  # Traceback header/footer lines
    ]
    
    # 4. Pattern for loading/progress bars (updated to match actual format)
    loading_patterns = [
        re.compile(r'Loading.*?:\s*\d+%\s*\|[█▓▒░\s]*\|\s*\d+/\d+.*?\[\d+:\d+<.*?\]'),  # Original pattern
        re.compile(r'^Loading.*?from.*?:\s*\d+%\|[█▓▒░\s]*\|\s*\d+/\d+\s*\[\d+:\d+<.*?\]'),  # Loading from Parquet
        re.compile(r'^Combining.*?:\s*\d+%\|[█▓▒░\s]*\|\s*\d+/\d+\s*\[\d+:\d+<.*?\]'),  # Combining DataFrames
        re.compile(r'^.*?:\s*\d+%\|[█▓▒░]+\|\s*\d+/\d+\s*\[.*?\]'),  # Generic progress bar with description
    ]
    
    cleaned_lines = []
    for line in text.splitlines():
        original_line = line
        stripped_line = line.strip()
        
        # Skip empty lines
        if not stripped_line:
            continue
            
        # Remove progress bars from the beginning of lines
        line = progress_pattern.sub('', line).strip()
        
        # Skip lines that are just decorators
        is_decorator = any(pattern.match(stripped_line) for pattern in decorator_patterns)
        if is_decorator:
            continue
            
        # Skip loading bars (check against all loading patterns)
        is_loading_bar = any(pattern.match(stripped_line) for pattern in loading_patterns)
        if is_loading_bar:
            continue
            
        # Skip lines that are just repeated characters (like ===== or -----)
        if len(set(stripped_line.replace(' ', ''))) <= 2 and len(stripped_line) > 4:
            continue
            
        # Remove arrow indicators and pipe symbols from the beginning of content lines
        # but preserve the actual content
        content_line = re.sub(r'^\s*[│├└❱❯►▶]+\s*', '', line)
        
        # Normalize internal whitespace to single spaces
        if content_line:  # Only process non-empty lines
            normalized_line = ' '.join(content_line.split())
            if normalized_line:  # Only add if something remains
                cleaned_lines.append(normalized_line)
    
    text_edit.setPlainText("\n".join(cleaned_lines))


def collapse_duplicates_action(text_edit):
    """Collapses consecutively repeated lines, showing a count."""
    lines = text_edit.toPlainText().splitlines()
    if not lines:
        return

    new_lines = []
    count = 1
    for i in range(1, len(lines)):
        # Compare current line with the previous one
        if lines[i].strip() == lines[i-1].strip() and lines[i].strip() != "":
            count += 1
        else:
            # Append the previous line, with a count if it was duplicated
            line_to_add = lines[i-1]
            if count > 1:
                line_to_add += f" (x{count})"
            new_lines.append(line_to_add)
            count = 1 # Reset counter
            
    # Always process the very last line
    last_line = lines[-1]
    if count > 1:
        last_line += f" (x{count})"
    new_lines.append(last_line)
    
    text_edit.setPlainText("\n".join(new_lines))

def clean_logs_combined_action(text_edit):
    """Applies both timestamp and ANSI cleaning in optimal order."""
    # First remove ANSI codes and decorators, then timestamps
    clean_logs_ansi_action(text_edit)
    clean_logs_timestamps_action(text_edit)
    collapse_duplicates_action(text_edit)