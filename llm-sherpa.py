import os
import sys
import re
import ast
import json
from functools import partial
import string

# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QFileDialog, QMessageBox,
    QDialog, QLabel, QStatusBar, QTextBrowser, QToolBar, QStyle,
    QHeaderView, QSizePolicy, QSplitter, QTabWidget, QComboBox, QProgressBar
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QKeySequence, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QTimer

# --- Local Module Imports ---
from sherpa_modules.config import SettingsManager, ConfigManager
from sherpa_modules.worker import FileSystemWorker, get_long_path_name
from sherpa_modules.ui import WelcomeDialog, SettingsWindow

# --- Live Code Preview Dependency Check ---
try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


class ProjectDocumenter(QMainWindow):
    def __init__(self):
        super().__init__()
        # --- GENERAL: Version Update ---
        self.setWindowTitle("LLM-Sherpa - Project Documenter v2.4")
        self.setGeometry(100, 100, 1200, 900)

        self.settings_manager = SettingsManager()
        self.config_manager = ConfigManager()
        self.project_path = ""
        self._is_updating_checks = False

        self.worker = None
        self.worker_thread = None

        # --- FIX: Pre-generate Pygments CSS for robust styling ---
        self.pygments_style = 'monokai'
        self.pygments_css = ""
        if PYGMENTS_AVAILABLE:
            # Generate the CSS definitions for the chosen style
            formatter = HtmlFormatter(style=self.pygments_style)
            # We target the .highlight class that Pygments wraps its output in
            self.pygments_css = formatter.get_style_defs('.highlight')

        self.init_ui()
        QTimer.singleShot(0, self.show_welcome_or_load_project)


    def init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.create_actions()
        self.create_menu_bar()
        self.create_tool_bar()

        main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(main_splitter)

        self.tab_widget = QTabWidget()
        main_splitter.addWidget(self.tab_widget)

        project_tab_widget = QWidget()
        project_layout = QVBoxLayout(project_tab_widget)
        self.tab_widget.addTab(project_tab_widget, "📂 Project")

        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        project_layout.addWidget(self.horizontal_splitter)

        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        self.tree_view = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        self.tree_view.setModel(self.tree_model)
        self.tree_view.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)
        tree_layout.addWidget(self.tree_view)
        self.horizontal_splitter.addWidget(tree_container)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)

        preview_label_text = "Code Preview ✨"
        if not PYGMENTS_AVAILABLE:
            preview_label_text += " (Syntax highlighting requires 'pip install Pygments')"
        preview_layout.addWidget(QLabel(preview_label_text))

        self.code_preview = QTextBrowser()
        self.code_preview.setReadOnly(True)
        font = QFont("Courier New", 11); self.code_preview.setFont(font)
        preview_layout.addWidget(self.code_preview)
        self.horizontal_splitter.addWidget(preview_container)
        self.horizontal_splitter.setSizes([450, 550])

        header = self.tree_view.header()
        header.setStretchLastSection(False)
        self.tree_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)

        log_tab_widget = QWidget()
        log_layout = QVBoxLayout(log_tab_widget)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("Paste logs or console output here. Use tools to clean and reduce token count."))
        log_toolbar.addStretch()

        btn_clean_timestamps = QPushButton("Rm Timestamps"); btn_clean_timestamps.setToolTip("Remove common timestamp formats."); btn_clean_timestamps.clicked.connect(self.clean_logs_timestamps); log_toolbar.addWidget(btn_clean_timestamps)
        btn_clean_ansi = QPushButton("Strip ANSI"); btn_clean_ansi.setToolTip("Remove ANSI color codes."); btn_clean_ansi.clicked.connect(self.clean_logs_ansi); log_toolbar.addWidget(btn_clean_ansi)
        btn_collapse_dups = QPushButton("Collapse Duplicates"); btn_collapse_dups.setToolTip("Collapse adjacent duplicate lines into a single line with a count."); btn_collapse_dups.clicked.connect(self.collapse_duplicates); log_toolbar.addWidget(btn_collapse_dups)

        log_layout.addLayout(log_toolbar)
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setPlaceholderText("Paste your error logs or console output here...")
        log_layout.addWidget(self.log_text_edit)
        self.tab_widget.addTab(log_tab_widget, "📋 Logs / Console")

        prompt_container = QWidget()
        prompt_v_layout = QVBoxLayout(prompt_container)
        prompt_label_layout = QHBoxLayout()
        prompt_label_layout.addWidget(QLabel("🎯 Objective / Prompt"))
        prompt_label_layout.addStretch()
        self.prompt_template_combo = QComboBox()
        self.prompt_template_combo.setToolTip("Select a prompt template")
        self.prompt_template_combo.addItem("Custom Prompt")
        self.prompt_template_combo.addItems(self.settings_manager.get("prompt_templates", {}).keys())
        self.prompt_template_combo.activated.connect(self.apply_prompt_template)
        prompt_label_layout.addWidget(self.prompt_template_combo)
        prompt_v_layout.addLayout(prompt_label_layout)
        self.prompt_text = QTextEdit(); prompt_v_layout.addWidget(self.prompt_text)
        main_splitter.addWidget(prompt_container)

        main_splitter.setSizes([700, 200])

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.loading_status_label = QLabel("")
        self.status_bar.addWidget(self.loading_status_label)

        self.token_budget_combo = QComboBox(); self.token_budget_combo.setToolTip("Select a token budget based on your target LLM"); self.token_budget_combo.addItem("No Budget"); self.token_budget_combo.addItems(self.settings_manager.get("llm_token_budgets", {}).keys()); self.token_budget_combo.currentTextChanged.connect(self.update_token_count); self.status_bar.addPermanentWidget(self.token_budget_combo)
        self.token_progress_bar = QProgressBar(); self.token_progress_bar.setMaximumWidth(200); self.token_progress_bar.setTextVisible(False); self.status_bar.addPermanentWidget(self.token_progress_bar)
        self.token_count_label = QLabel("Size: ~0 tokens"); self.status_bar.addPermanentWidget(self.token_count_label)

        self.tree_model.itemChanged.connect(self.on_item_changed)
        self.prompt_text.textChanged.connect(self.update_token_count)
        self.log_text_edit.textChanged.connect(self.update_token_count)

    def _apply_tree_column_widths(self):
        header = self.tree_view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive); header.resizeSection(0, 400)
        header.setSectionResizeMode(1, QHeaderView.Interactive); header.resizeSection(1, 120)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.tree_view.updateGeometry(); self.tree_view.viewport().update()

    def _set_children_check_state(self, item, state):
        self._is_updating_checks = True
        item.setCheckState(state)
        if item.hasChildren():
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                if child: self._set_children_check_state(child, state)
        self._is_updating_checks = False

    def _update_ancestor_check_state(self, item):
        self._is_updating_checks = True
        parent = item.parent()
        while parent:
            child_count = parent.rowCount(); checked_count = 0; partially_checked_count = 0
            for i in range(child_count):
                child = parent.child(i, 0); state = child.checkState()
                if state == Qt.CheckState.Checked: checked_count += 1
                elif state == Qt.CheckState.PartiallyChecked: partially_checked_count += 1
            if checked_count == child_count: parent.setCheckState(Qt.CheckState.Checked)
            elif checked_count > 0 or partially_checked_count > 0: parent.setCheckState(Qt.CheckState.PartiallyChecked)
            else: parent.setCheckState(Qt.CheckState.Unchecked)
            parent = parent.parent()
        self._is_updating_checks = False

    @Slot(QStandardItem)
    def on_item_changed(self, item):
        if self._is_updating_checks: return
        self._is_updating_checks = True

        item_data = item.data(Qt.UserRole)
        if item_data and item_data.get('type') != 'function':
            if item.hasChildren():
                self._set_children_check_state(item, item.checkState())

        self._update_ancestor_check_state(item)

        self._is_updating_checks = False
        self.update_token_count()

    @Slot()
    def show_welcome_or_load_project(self):
        path_to_load = None
        if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]): path_to_load = sys.argv[1]
        if path_to_load: self.load_project(path_to_load, is_initial_load=True)
        else:
            recent_paths = self.config_manager.get_recent_projects()
            dialog = WelcomeDialog(recent_paths, self)
            if dialog.exec():
                if dialog.selected_path == "OPEN_NEW": self.select_folder_dialog()
                elif dialog.selected_path: self.load_project(dialog.selected_path)

    @Slot()
    def refresh_project(self):
        if self.project_path: self.load_project(self.project_path, is_initial_load=False)

    @Slot()
    def select_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Root Folder")
        if folder: self.load_project(folder, is_initial_load=False)

    def load_project(self, path, is_initial_load=False):
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker: self.worker.stop()
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000): print("Warning: Worker thread did not terminate gracefully.")

        self.project_path = get_long_path_name(path)
        self.setWindowTitle(f"LLM-Sherpa - {os.path.basename(self.project_path)}")
        self.tree_model.clear()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        if not is_initial_load:
            self.log_text_edit.clear()
        self.config_manager.add_recent_project(self.project_path); self.config_manager.save_config(); self.update_recent_projects_menu()

        self.set_ui_enabled(False); self.loading_status_label.setText("Scanning project files...")
        QApplication.processEvents() # Ensure the UI updates to show the indicator

        self.worker_thread = QThread(self)
        self.worker = FileSystemWorker(self.project_path, self.settings_manager.settings)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.results_ready.connect(self.populate_tree_from_data)
        self.worker.error.connect(self.on_loading_error)
        self.worker.finished.connect(self.worker_thread.quit); self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater); self.worker_thread.finished.connect(self._clear_worker_refs)
        self.worker_thread.start()

    @Slot()
    def _clear_worker_refs(self):
        self.worker = None; self.worker_thread = None

    @Slot(list)
    def populate_tree_from_data(self, items_data):
        self.loading_status_label.setText("Building tree view...")
        path_to_item_map = {'.': self.tree_model.invisibleRootItem()}

        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon); file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        py_icon = QIcon.fromTheme("text-x-python", file_icon); class_icon = QIcon.fromTheme("x-office-document", file_icon); func_icon = QIcon.fromTheme("utilities-terminal", file_icon)

        for item_data in items_data:
            parent_item = path_to_item_map.get(item_data['parent_id'])
            if parent_item is None: continue
            name_item = QStandardItem(item_data['name']); name_item.setCheckable(True); name_item.setEditable(False)
            name_item.setData(item_data, Qt.UserRole)
            rel_path_item = QStandardItem(item_data['rel_path']); rel_path_item.setEditable(False)
            item_type = item_data['type']; type_item = QStandardItem(item_type); type_item.setEditable(False)

            if item_type == 'folder': name_item.setIcon(folder_icon); parent_item.appendRow([name_item, type_item, rel_path_item]); path_to_item_map[item_data['id']] = name_item
            elif item_type == 'file': ext = os.path.splitext(item_data['name'])[-1].lower(); name_item.setIcon(py_icon if ext == '.py' else file_icon); parent_item.appendRow([name_item, type_item, rel_path_item]); path_to_item_map[item_data['id']] = name_item
            elif item_type in ['class', 'function']: name_item.setIcon(class_icon if item_type == 'class' else func_icon); parent_item.appendRow([name_item, type_item, QStandardItem("")]); path_to_item_map[item_data['id']] = name_item

        self.on_loading_finished()
        QTimer.singleShot(0, self._apply_tree_column_widths)

    @Slot(str)
    def on_loading_error(self, error_message):
        QMessageBox.critical(self, "Loading Error", f"Failed to load project structure:\n{error_message}")
        self.on_loading_finished()

    def on_loading_finished(self):
        self.loading_status_label.setText(""); self.set_ui_enabled(True)
        if self.project_path and self.settings_manager.get("restore_tree_selection"): self.restore_tree_state()
        self.update_token_count()

    def set_ui_enabled(self, enabled):
        self.generate_action.setEnabled(enabled and bool(self.project_path)); self.open_action.setEnabled(enabled); self.refresh_action.setEnabled(enabled and bool(self.project_path)); self.toggle_all_action.setEnabled(enabled); self.tree_view.setEnabled(enabled)

    def create_actions(self):
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DirOpenIcon), "&Open Project Folder...", self);self.open_action.setShortcut(QKeySequence.Open);self.open_action.triggered.connect(self.select_folder_dialog)
        self.refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "&Refresh", self); self.refresh_action.setShortcut(QKeySequence.Refresh); self.refresh_action.triggered.connect(self.refresh_project); self.refresh_action.setEnabled(False)
        self.generate_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "&Generate Context", self);self.generate_action.setShortcut(QKeySequence.Save);self.generate_action.triggered.connect(self.generate_markdown);self.generate_action.setEnabled(False)
        self.exit_action = QAction("E&xit", self);self.exit_action.setShortcut(QKeySequence.Quit);self.exit_action.triggered.connect(self.close)
        self.toggle_all_action = QAction(self.style().standardIcon(QStyle.SP_FileDialogDetailedView), "&Toggle All Selections", self);self.toggle_all_action.setShortcut(QKeySequence("Ctrl+A"));self.toggle_all_action.triggered.connect(self.toggle_all_selections)
        self.settings_action = QAction(self.style().standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Settings...", self);self.settings_action.triggered.connect(self.open_settings)
        self.docs_action = QAction("&Documentation", self);self.docs_action.triggered.connect(self.show_docs_dialog)
        self.about_action = QAction("&About", self);self.about_action.triggered.connect(self.show_about_dialog)
        self.strip_comments_action = QAction("Strip Comments & Docstrings", self); self.strip_comments_action.setCheckable(True)
        self.minify_code_action = QAction("Minify Code (basic)", self); self.minify_code_action.setCheckable(True)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("&File"); self.file_menu.addAction(self.open_action)
        self.recent_projects_menu = self.file_menu.addMenu("Recent Projects"); self.update_recent_projects_menu()
        self.file_menu.addSeparator(); self.file_menu.addAction(self.generate_action); self.file_menu.addSeparator(); self.file_menu.addAction(self.exit_action)
        edit_menu = menu_bar.addMenu("&Edit"); edit_menu.addAction(self.refresh_action); edit_menu.addAction(self.toggle_all_action)
        optimize_menu = menu_bar.addMenu("&Optimize"); optimize_menu.addAction(self.strip_comments_action); optimize_menu.addAction(self.minify_code_action)
        settings_menu = menu_bar.addMenu("&Settings"); settings_menu.addAction(self.settings_action)
        help_menu = menu_bar.addMenu("&Help"); help_menu.addAction(self.docs_action); help_menu.addAction(self.about_action)

    def update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        # FIX: Ensure recent projects list contains unique paths
        recent_paths = list(dict.fromkeys(self.config_manager.get_recent_projects()))
        for path in recent_paths:
            if os.path.isdir(path):
                action = QAction(path, self); action.triggered.connect(partial(self.load_project, path)); self.recent_projects_menu.addAction(action)
        self.recent_projects_menu.setEnabled(len(recent_paths) > 0)

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar");tool_bar.setMovable(False)
        tool_bar.addAction(self.open_action); tool_bar.addAction(self.refresh_action); tool_bar.addAction(self.generate_action)
        tool_bar.addSeparator(); tool_bar.addAction(self.toggle_all_action); tool_bar.addAction(self.settings_action)

    @Slot()
    def toggle_all_selections(self):
        root = self.tree_model.invisibleRootItem()
        if root.rowCount() == 0: return

        all_checked = all(root.child(row, 0).checkState() == Qt.CheckState.Checked for row in range(root.rowCount()))
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked

        for row in range(root.rowCount()):
            item = root.child(row, 0)
            if item:
                item.setCheckState(new_state)

    def get_tree_state(self):
        checked_ids, expanded_ids = [], []; root = self.tree_model.invisibleRootItem()
        def recurse(parent_item):
            for row in range(parent_item.rowCount()):
                item = parent_item.child(row, 0)
                if not item: continue
                item_data = item.data(Qt.UserRole)
                if item_data:
                    item_id = item_data.get('id')
                    if item.checkState() in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked): checked_ids.append(item_id)
                    if item.hasChildren() and self.tree_view.isExpanded(item.index()): expanded_ids.append(item_id); recurse(item)
        recurse(root); return {"checked": checked_ids, "expanded": expanded_ids}

    def restore_tree_state(self):
        tree_states = self.config_manager.get("tree_states", {}); state = tree_states.get(self.project_path)
        if not state: return

        self._is_updating_checks = True

        checked_set = set(state.get("checked", []))
        expanded_set = set(state.get("expanded", []))

        q = [self.tree_model.invisibleRootItem()]
        while q:
            parent_item = q.pop(0)
            for row in range(parent_item.rowCount()):
                item = parent_item.child(row, 0)
                if not item: continue

                item_data = item.data(Qt.UserRole)
                if item_data:
                    item_id = item_data.get('id')
                    if item_id in checked_set:
                        item.setCheckState(Qt.CheckState.Checked)
                    if item_id in expanded_set:
                        self.tree_view.expand(item.index())

                if item.hasChildren():
                    q.append(item)

        self._is_updating_checks = False

        # Trigger itemChanged for top-level items to correctly propagate states
        for row in range(self.tree_model.rowCount()):
            self.on_item_changed(self.tree_model.item(row))

    def _get_code_from_item(self, item_data):
        file_path = item_data.get('full_path', '')
        item_type = item_data.get('type')
        if not file_path: return ""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: lines = f.readlines()
            if item_type == 'file': return "".join(lines)
            elif item_type in ('class', 'function'): start = item_data.get('start_line', 1) - 1; end = item_data.get('end_line', len(lines)); return "".join(lines[start:end])
        except (IOError, OSError): return ""
        return ""

    def _get_checked_content(self):
        content_map = {}
        root = self.tree_model.invisibleRootItem()
        # Initialize the queue with all top-level items
        q = [root.child(i, 0) for i in range(root.rowCount()) if root.child(i, 0)]

        while q:
            item = q.pop(0)
            item_data = item.data(Qt.UserRole)
            if not item_data:
                continue

            is_checked = item.checkState() == Qt.CheckState.Checked
            is_partially_checked = item.checkState() == Qt.CheckState.PartiallyChecked
            item_type = item_data.get('type')

            # --- FIX: Process content for checked files/functions ---
            # If the item is a file or a specific code element (class, function)
            # and it's fully checked, we add its content.
            if item_type in ('file', 'class', 'function') and is_checked:
                file_path = item_data.get('full_path')
                if not file_path:
                    continue
                
                # If this is the first time we're seeing this file path, create an entry for it
                if file_path not in content_map:
                    rel_path = os.path.relpath(file_path, self.project_path)
                    content_map[file_path] = {'rel_path': rel_path, 'snippets': []}
                
                # Add the specific code snippet to the list for this file path
                content_map[file_path]['snippets'].append(self._get_code_from_item(item_data))

            # --- FIX: Traverse into checked or partially checked containers ---
            # If the item has children (i.e., it's a folder or a file with functions)
            # and it is either fully or partially selected, we must check its children.
            if item.hasChildren() and (is_checked or is_partially_checked):
                for i in range(item.rowCount()):
                    child = item.child(i, 0)
                    if child:
                        q.append(child)

        # Consolidate the collected snippets into the final output structure
        final_content = []
        for path, data in content_map.items():
            final_content.append({
                'full_path': path,
                'rel_path': data['rel_path'],
                'content': "\n\n".join(data['snippets'])
            })
        return final_content

    def update_token_count(self):
        prompt_chars = len(self.prompt_text.toPlainText())
        log_chars = len(self.log_text_edit.toPlainText())
        code_chars = 0
        for item in self._get_checked_content(): code_chars += len(item['content'])

        total_chars = prompt_chars + log_chars + code_chars
        estimated_tokens = int(total_chars / 4)
        self.token_count_label.setText(f"Size: ~{estimated_tokens:,} tokens")

        budgets = self.settings_manager.get("llm_token_budgets", {}); selected_budget = self.token_budget_combo.currentText()
        if selected_budget in budgets:
            budget = budgets[selected_budget]; self.token_progress_bar.setMaximum(budget); self.token_progress_bar.setValue(min(estimated_tokens, budget)); self.token_progress_bar.setVisible(True)
            ratio = estimated_tokens / budget if budget > 0 else 0
            color = "green"
            if ratio > 1.0: # FIX: Alert the user when the budget is exceeded
                color = "red"
                self.token_count_label.setText(f"Size: ~{estimated_tokens:,} tokens (Budget Exceeded!)")
            elif ratio > 0.9: color = "red"
            elif ratio > 0.7: color = "orange"
            self.token_progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
        else: self.token_progress_bar.setVisible(False)

    @Slot()
    def open_settings(self):
        dialog = SettingsWindow(self.settings_manager, self)
        if dialog.exec():
            self.prompt_template_combo.clear(); self.prompt_template_combo.addItem("Custom Prompt"); self.prompt_template_combo.addItems(self.settings_manager.get("prompt_templates", {}).keys())
            self.token_budget_combo.clear(); self.token_budget_combo.addItem("No Budget"); self.token_budget_combo.addItems(self.settings_manager.get("llm_token_budgets", {}).keys())
            if self.project_path: self.load_project(self.project_path)

    def _generate_tree_structure(self, file_paths):
        tree = {}; lines = ["."]; P_C, P_S = "├── ", "│   "; E_C, E_S = "└── ", "    "
        for path in file_paths:
            parts = path.replace(os.sep, '/').split('/'); current_level = tree
            for part in parts:
                if part not in current_level: current_level[part] = {}
                current_level = current_level[part]
        def _build_lines(d, prefix=""):
            items = sorted(d.keys())
            for i, item in enumerate(items):
                is_last = i == len(items) - 1; connector = E_C if is_last else P_C; lines.append(f"{prefix}{connector}{item}{'/' if d[item] else ''}")
                if d[item]: _build_lines(d[item], prefix + (E_S if is_last else P_S))
        _build_lines(tree); return "\n".join(lines)

    def generate_markdown(self):
        prompt_text = self.prompt_text.toPlainText().strip()
        selected_content = self._get_checked_content()
        log_content = self.log_text_edit.toPlainText().strip()

        if not selected_content and not prompt_text and not log_content:
            QMessageBox.information(self, "Info", "Nothing to generate. Select some files/code or provide a prompt/log."); return

        output_file, _ = QFileDialog.getSaveFileName(self, "Save Context File", f"{os.path.basename(self.project_path)}_context.md", "Markdown Files (*.md);;All Files (*)")
        if not output_file: return

        def optimize_code(code):
            if self.strip_comments_action.isChecked():
                code = re.sub(r'#.*', '', code); code = re.sub(r'//.*', '', code); code = re.sub(r'/\*.*?\*/', '', code, flags=re.DOTALL)
            if self.minify_code_action.isChecked(): code = "\n".join(line for line in code.splitlines() if line.strip())
            return code

        has_objective = bool(prompt_text)
        has_logs = bool(log_content)
        all_rel_paths = [c['rel_path'] for c in selected_content]
        known_deps = self.settings_manager.get("known_dependency_files", [])
        dependency_files = [c for c in selected_content if os.path.basename(c['full_path']) in known_deps]
        main_code_files = [c for c in selected_content if c not in dependency_files]
        show_structure = self.settings_manager.get("show_project_structure") and selected_content
        has_dependencies = bool(dependency_files)
        has_main_files = bool(main_code_files)

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                if has_objective: f.write(f"# 🎯 Objective\n\n{prompt_text}\n\n---\n\n")
                project_name = os.path.basename(os.path.normpath(self.project_path))
                f.write(f"## 📚 Project Context: `{project_name}`\n\nThis document provides the necessary files, code structure, and console output for the task.\n\n")
                section_counter = 1
                if has_logs:
                    f.write(f"### {section_counter}. Console Log / Error Output\n\nThe following is the console output or error log related to the task.\n\n```\n{log_content}\n```\n\n")
                    section_counter += 1
                if show_structure:
                    f.write(f"### {section_counter}. Project Structure\n\n```\n{self._generate_tree_structure(all_rel_paths)}\n```\n\n")
                    section_counter += 1
                if has_dependencies:
                    f.write(f"### {section_counter}. Dependencies\n\n")
                    for dep in dependency_files:
                        filename, rel_path = os.path.basename(dep['full_path']), dep['rel_path'].replace(os.sep,'/')
                        f.write(f"#### `{filename}`\n*path: `{rel_path}`*\n\n```\n{dep['content']}\n```\n\n")
                    section_counter += 1
                if has_main_files:
                    f.write(f"### {section_counter}. File Contents\n\n")
                    ext_map = self.settings_manager.get("extension_map")
                    for code_file in main_code_files:
                        filename, rel_path = os.path.basename(code_file['full_path']), code_file['rel_path'].replace(os.sep, '/')
                        ext = os.path.splitext(filename)[1].lower(); lang = ext_map.get(ext, "")
                        optimized_content = optimize_code(code_file['content'])
                        f.write(f"#### 📄 `{filename}`\n\n*path: `{rel_path}`*\n\n```{lang}\n{optimized_content}\n```\n\n")
            QMessageBox.information(self, "Success", f"Context file generated at:\n{output_file}")
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to generate documentation:\n{e}")

    @Slot()
    def show_about_dialog(self):
        about_text = """<h2>LLM-Sherpa</h2><p>Version 2.4</p><p>A tool to package source code into a single, context-rich Markdown file for Large Language Models.</p><p><b>Developer:</b> VicRejkia</p><p><b>GitHub:</b> <a href='https://github.com/VicRejkia/LLM-Sherpa'>https://github.com/VicRejkia/LLM-Sherpa</a></p>"""
        QMessageBox.about(self, "About LLM-Sherpa", about_text)

    @Slot()
    def show_docs_dialog(self):
        readme_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"README.md")
        try:
            with open(readme_path,'r',encoding='utf-8') as f:readme_content=f.read()
        except FileNotFoundError:readme_content="<h2>Documentation Not Found</h2><p>Could not find README.md.</p>"
        dialog=QDialog(self);dialog.setWindowTitle("Documentation");dialog.setGeometry(150,150,700,500);layout=QVBoxLayout(dialog);text_browser=QTextBrowser();text_browser.setOpenExternalLinks(True);text_browser.setMarkdown(readme_content);layout.addWidget(text_browser);dialog.exec()

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker: self.worker.stop()
            self.worker_thread.quit(); self.worker_thread.wait()
        if self.project_path:
            if self.settings_manager.get("remember_project_path"):self.config_manager.set("last_project_path",self.project_path)
            if self.settings_manager.get("restore_tree_selection"): current_tree_state=self.get_tree_state();all_tree_states=self.config_manager.get("tree_states",{});all_tree_states[self.project_path]=current_tree_state;self.config_manager.set("tree_states",all_tree_states)
        self.config_manager.save_config();event.accept()

    # --- FIX: Reworked HTML/CSS generation for robust highlighting and spacing ---
    @Slot()
    def on_tree_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes: self.code_preview.clear(); return

        item = self.tree_model.itemFromIndex(indexes[0])
        item_data = item.data(Qt.UserRole)
        if not item_data or item_data.get('type') == 'folder': self.code_preview.clear(); return

        code = self._get_code_from_item(item_data)

        if PYGMENTS_AVAILABLE:
            lexer = None
            try:
                file_ext = os.path.splitext(item_data['full_path'])[1].lower()
                lang_id = self.settings_manager.get("extension_map").get(file_ext, 'text')
                lexer = get_lexer_by_name(lang_id)
            except Exception:
                lexer = guess_lexer(code)

            formatter = HtmlFormatter(style=self.pygments_style, linenos='table', noclasses=False)
            html_fragment = highlight(code, lexer, formatter)

            # Manually construct the full HTML to ensure styles are applied correctly
            full_html = f"""
            <html>
            <head>
            <style>
            {self.pygments_css}
            /* Custom styles to force spacing and theming */
            body {{ background-color: #272822; color: #f8f8f2; }}
            table {{ border-spacing: 0; }}
            td {{ padding: 0; white-space: pre-wrap; }}
            .linenos {{
                color: #8F908A;
                padding: .4em .8em .4em .8em;
                border-right: 1px solid #49483e;
                user-select: none; /* Make line numbers unselectable */
            }}
            .code {{
                padding: .4em !important;
            }}
            </style>
            </head>
            <body>
            {html_fragment}
            </body>
            </html>
            """
            self.code_preview.setHtml(full_html)
        else:
            self.code_preview.setText(code)

    @Slot()
    def apply_prompt_template(self):
        template_name = self.prompt_template_combo.currentText()
        if template_name != "Custom Prompt": self.prompt_text.setPlainText(self.settings_manager.get("prompt_templates", {}).get(template_name, ""))

    @Slot()
    def clean_logs_timestamps(self):
        text = self.log_text_edit.toPlainText()

        # 1️⃣ Remove common timestamp formats
        timestamp_pattern = re.compile(
            r"""
            ^\s*
            (?:
                \[[A-Z]?\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\] |
                \d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z? |
                \[\d{1,2}/\d{1,2}/\d{2,4}\s+\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\] |
                \d{2}:\d{2}:\d{2}(?:[.,]\d+)? |
                \d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[.,]\d+\:?
            )
            \s*-?\s*
            """,
            re.VERBOSE | re.MULTILINE
        )
        text = timestamp_pattern.sub('', text)

        # 2️⃣ Remove any leading non-alphanumeric junk from each line
        # (anything that isn't a-z, A-Z, or 0-9 at the start)
        text = re.sub(r'^[^a-zA-Z0-9]+', '', text, flags=re.MULTILINE)

        # 3️⃣ Remove lines that become empty after cleanup
        text = "\n".join(line for line in text.splitlines() if line.strip())

        self.log_text_edit.setPlainText(text.strip())

    @Slot()
    def clean_logs_ansi(self):
        text = self.log_text_edit.toPlainText()

        # 1. Remove ANSI escape sequences
        ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)

        # 2. Remove emojis & other non-ASCII
        text = ''.join(ch for ch in text if ch in string.printable or ch in '\n\t')

        # 3. Remove decorative lines (====, ****, ----, etc.)
        decorative_line = re.compile(r'^[=\-\*#\s]{3,}$', re.MULTILINE)
        text = decorative_line.sub('', text)

        # 4. Collapse multiple blank lines
        text = re.sub(r'\n\s*\n+', '\n', text)

        # 5. Optionally trim overly long spaces inside lines
        text = re.sub(r' {2,}', ' ', text)

        # 6. Strip leading/trailing whitespace
        text = text.strip()

        self.log_text_edit.setPlainText(text)

    @Slot()
    def collapse_duplicates(self):
        """Collapse duplicate lines into one with a count (global, not just consecutive)."""
        text = self.log_text_edit.toPlainText()

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        seen = {}
        order = []
        for line in lines:
            if line not in seen:
                seen[line] = 1
                order.append(line)
            else:
                seen[line] += 1
        new_lines = [f"{line} (x{seen[line]})" if seen[line] > 1 else line for line in order]
        text = "\n".join(new_lines)
        
        # Strip leading/trailing whitespace
        text = text.strip()

        self.log_text_edit.setPlainText(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())