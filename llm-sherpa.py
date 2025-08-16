import os
import sys
import json
from functools import partial

# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QTextBrowser, QToolBar, QStyle,
    QHeaderView, QSplitter, QTabWidget, QComboBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QCheckBox
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QTimer

# --- Local Module Imports ---
from sherpa_modules.config import SettingsManager, ConfigManager
from sherpa_modules.worker import FileSystemWorker, get_long_path_name
from sherpa_modules.ui import WelcomeDialog, IterativeRefinementDialog, TDDWizard
from sherpa_modules import actions, tree_handler, content_utils

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
        self.setWindowTitle("LLM-Sherpa - Project Documenter v3.4")
        self.setGeometry(100, 100, 1400, 950)

        self.settings_manager = SettingsManager()
        self.config_manager = ConfigManager()
        self.project_path = ""
        self._is_updating_checks = False
        self._is_loading_project = False # Flag to prevent saving during load

        self.worker = None
        self.worker_thread = None

        self.pygments_css = ""
        if PYGMENTS_AVAILABLE:
            formatter = HtmlFormatter(style='monokai')
            self.pygments_css = formatter.get_style_defs('.highlight')

        self.init_ui()
        self._connect_signals()
        QTimer.singleShot(0, self.show_welcome_or_load_project)

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.create_actions()
        self.create_menu_bar()
        self.create_tool_bar()

        main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(main_splitter)

        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.main_tabs = QTabWidget()
        top_layout.addWidget(self.main_tabs)
        main_splitter.addWidget(top_container)

        project_tab_widget = QWidget()
        project_layout = QVBoxLayout(project_tab_widget)
        self.main_tabs.addTab(project_tab_widget, "📂 Project")

        self.horizontal_splitter = QSplitter(Qt.Horizontal)
        project_layout.addWidget(self.horizontal_splitter)

        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        self.tree_view = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        self.tree_view.setModel(self.tree_model)
        tree_layout.addWidget(self.tree_view)
        self.horizontal_splitter.addWidget(tree_container)

        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_label_text = "Code Preview ✨" + ("" if PYGMENTS_AVAILABLE else " (Syntax highlighting requires 'pip install Pygments')")
        preview_layout.addWidget(QLabel(preview_label_text))
        self.code_preview = QTextBrowser()
        self.code_preview.setReadOnly(True)
        self.code_preview.setFont(QFont("Courier New", 11))
        preview_layout.addWidget(self.code_preview)
        self.horizontal_splitter.addWidget(preview_container)
        self.horizontal_splitter.setSizes([500, 600])

        log_tab_widget = QWidget()
        log_layout = QVBoxLayout(log_tab_widget)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("Paste logs or console output here."))
        log_toolbar.addStretch()
        btn_clean_timestamps = QPushButton("Rm Timestamps"); btn_clean_timestamps.clicked.connect(self.clean_logs_timestamps); log_toolbar.addWidget(btn_clean_timestamps)
        btn_clean_ansi = QPushButton("Strip ANSI"); btn_clean_ansi.clicked.connect(self.clean_logs_ansi); log_toolbar.addWidget(btn_clean_ansi)
        btn_collapse_dups = QPushButton("Collapse Duplicates"); btn_collapse_dups.clicked.connect(self.collapse_duplicates); log_toolbar.addWidget(btn_collapse_dups)
        log_layout.addLayout(log_toolbar)
        self.log_text_edit = QTextEdit()
        log_layout.addWidget(self.log_text_edit)
        self.main_tabs.addTab(log_tab_widget, "📋 Logs / Console")

        prompt_studio_container = QWidget()
        prompt_studio_layout = QVBoxLayout(prompt_studio_container)
        
        task_selector_layout = QHBoxLayout()
        task_selector_layout.addWidget(QLabel("<b>Select a Task:</b>"))
        self.task_selector_combo = QComboBox()
        prompt_modules = self.settings_manager.get("prompt_modules", {})
        if prompt_modules:
            self.task_selector_combo.addItems(prompt_modules.keys())
        task_selector_layout.addWidget(self.task_selector_combo, 1)
        prompt_studio_layout.addLayout(task_selector_layout)

        self.prompt_tabs = QTabWidget()
        prompt_studio_layout.addWidget(self.prompt_tabs)
        main_splitter.addWidget(prompt_studio_container)
        
        objective_tab = QWidget()
        objective_layout = QVBoxLayout(objective_tab)
        self.prompt_template_combo = QComboBox()
        self.prompt_template_combo.addItem("Custom Prompt")
        self.prompt_template_combo.addItems(self.settings_manager.get("prompt_templates", {}).keys())
        self.objective_text_edit = QTextEdit()
        objective_layout.addWidget(self.prompt_template_combo)
        objective_layout.addWidget(self.objective_text_edit)
        self.prompt_tabs.addTab(objective_tab, "🎯 Objective")

        components_tab = QWidget()
        components_layout = QVBoxLayout(components_tab)
        self.preamble_checkbox = QCheckBox("Generate 'Table of Contents' Preamble")
        self.preamble_checkbox.setChecked(True)
        components_layout.addWidget(self.preamble_checkbox)
        components_layout.addWidget(QLabel("<b>Key Files & Roles (Optional):</b>"))
        self.key_files_table = QTableWidget(0, 2)
        self.key_files_table.setHorizontalHeaderLabels(["File", "Role/Description"])
        self.key_files_table.horizontalHeader().setStretchLastSection(True)
        components_layout.addWidget(self.key_files_table, 1)
        
        key_files_button_layout = QHBoxLayout()
        btn_add_files_to_table = QPushButton("Add Selected Files from Tree")
        btn_add_files_to_table.clicked.connect(self._populate_key_files_table)
        key_files_button_layout.addWidget(btn_add_files_to_table)
        
        btn_remove_files_from_table = QPushButton("Remove Selected File(s)")
        btn_remove_files_from_table.clicked.connect(self._remove_selected_key_files)
        key_files_button_layout.addWidget(btn_remove_files_from_table)
        key_files_button_layout.addStretch()

        components_layout.addLayout(key_files_button_layout)
        self.prompt_tabs.addTab(components_tab, "🧩 Components")

        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        self.prompt_preview_browser = QTextBrowser()
        self.prompt_preview_browser.setReadOnly(True)
        preview_layout.addWidget(QLabel("<b>Assembled Prompt Preview:</b>"))
        preview_layout.addWidget(self.prompt_preview_browser)
        self.prompt_tabs.addTab(preview_tab, "🔍 Preview")

        main_splitter.setSizes([650, 300])

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.loading_status_label = QLabel("")
        self.status_bar.addWidget(self.loading_status_label)
        self.token_budget_combo = QComboBox(); self.token_budget_combo.addItems(["No Budget"] + list(self.settings_manager.get("llm_token_budgets", {}).keys())); self.status_bar.addPermanentWidget(self.token_budget_combo)
        self.token_progress_bar = QProgressBar(); self.token_progress_bar.setMaximumWidth(200); self.token_progress_bar.setTextVisible(False); self.status_bar.addPermanentWidget(self.token_progress_bar)
        self.token_count_label = QLabel("Size: ~0 tokens"); self.status_bar.addPermanentWidget(self.token_count_label)
    
    def _connect_signals(self):
        self.tree_view.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)
        self.tree_model.itemChanged.connect(self.on_item_changed)
        self.log_text_edit.textChanged.connect(self._update_prompt_preview_and_tokens)
        self.objective_text_edit.textChanged.connect(self._update_prompt_preview_and_tokens)
        self.key_files_table.itemChanged.connect(self._update_prompt_preview_and_tokens)
        self.task_selector_combo.currentTextChanged.connect(self._on_task_selected)
        self.prompt_template_combo.activated.connect(self.apply_prompt_template)
        self.token_budget_combo.currentTextChanged.connect(self.update_token_count)
    
    # --- Action Slots (Delegating to modules) ---
    @Slot()
    def generate_markdown(self):
        actions.generate_markdown_action(self)

    @Slot()
    def open_settings(self):
        actions.open_settings_action(self)

    @Slot()
    def toggle_all_selections(self):
        actions.toggle_all_selections_action(self)

    @Slot()
    def clean_logs_timestamps(self):
        actions.clean_logs_timestamps_action(self.log_text_edit)

    @Slot()
    def clean_logs_ansi(self):
        actions.clean_logs_ansi_action(self.log_text_edit)

    @Slot()
    def collapse_duplicates(self):
        actions.collapse_duplicates_action(self.log_text_edit)
    
    @Slot(QStandardItem)
    def on_item_changed(self, item):
        tree_handler.on_item_changed(self, item)

    # --- UI Update and Helper Methods ---
    @Slot()
    def _update_prompt_preview_and_tokens(self):
        self._update_prompt_preview()
        self.update_token_count()
        if not self._is_loading_project:
            self._save_project_state()

    def _assemble_prompt(self):
        objective = self.objective_text_edit.toPlainText().strip()
        components_text = ""
        
        # key_files = []
        # for row in range(self.key_files_table.rowCount()):
        #     file_item = self.key_files_table.item(row, 0)
        #     role_item = self.key_files_table.item(row, 1)
        #     if file_item and role_item and file_item.text() and role_item.text():
        #         key_files.append(f"- **{file_item.text().strip()}**: {role_item.text().strip()}")
        
        # if key_files:
        #     components_text = "### Key Files Overview\n" + "\n".join(key_files) + "\n\n"
        
        master_template = self.settings_manager.get("master_prompt_template", "{objective}\n\n{components}")
        return master_template.format(objective=objective, components=components_text).strip()

    @Slot()
    def _update_prompt_preview(self):
        self.prompt_preview_browser.setPlainText(self._assemble_prompt())

    @Slot(str)
    def _on_task_selected(self, task_name):
        task_data = self.settings_manager.get("prompt_modules", {}).get(task_name, {})
        self.objective_text_edit.setPlainText(task_data.get("objective", ""))
        self.main_tabs.setCurrentIndex(1 if task_data.get("focus_tab") == "Logs / Console" else 0)
        self._update_prompt_preview()

    @Slot()
    def _populate_key_files_table(self):
        selected_indexes = self.tree_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.information(self, "Info", "Select files in the tree view first.")
            return

        files_to_add = {
            item.data(Qt.UserRole).get('rel_path')
            for index in selected_indexes if index.column() == 0
            for item in [self.tree_model.itemFromIndex(index)]
            if item.data(Qt.UserRole) and item.data(Qt.UserRole).get('type') == 'file'
        }
        
        for file_path in sorted(list(files_to_add)):
            row_count = self.key_files_table.rowCount()
            self.key_files_table.insertRow(row_count)
            self.key_files_table.setItem(row_count, 0, QTableWidgetItem(file_path))
            self.key_files_table.setItem(row_count, 1, QTableWidgetItem(""))
        self.key_files_table.resizeColumnsToContents()
        self._save_project_state()

    @Slot()
    def _remove_selected_key_files(self):
        """Removes the selected rows from the key_files_table."""
        selected_rows = sorted(list(set(index.row() for index in self.key_files_table.selectedIndexes())), reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "Info", "Select a file in the table to remove.")
            return
        
        for row in selected_rows:
            self.key_files_table.removeRow(row)
        
        self._save_project_state()

    def update_token_count(self):
        prompt_chars = len(self._assemble_prompt())
        log_chars = len(self.log_text_edit.toPlainText())
        code_chars = sum(len(item['content']) for item in content_utils.get_checked_content(self))
        estimated_tokens = int((prompt_chars + log_chars + code_chars) / 4)
        self.token_count_label.setText(f"Size: ~{estimated_tokens:,} tokens")

        budgets = self.settings_manager.get("llm_token_budgets", {})
        selected_budget_name = self.token_budget_combo.currentText()
        if selected_budget_name in budgets:
            budget = budgets[selected_budget_name]
            self.token_progress_bar.setVisible(True)
            self.token_progress_bar.setMaximum(budget)
            self.token_progress_bar.setValue(min(estimated_tokens, budget))
            ratio = estimated_tokens / budget if budget > 0 else 0
            color = "green"
            if ratio > 0.9: color = "red"
            elif ratio > 0.7: color = "orange"
            self.token_progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
        else:
            self.token_progress_bar.setVisible(False)

    # --- Project Loading and Management ---
    @Slot()
    def show_welcome_or_load_project(self):
        path_to_load = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
        if path_to_load:
            self.load_project(path_to_load)
        else:
            dialog = WelcomeDialog(self.config_manager.get_recent_projects(), self)
            if dialog.exec():
                if dialog.selected_path == "OPEN_NEW": self.select_folder_dialog()
                elif dialog.selected_path: self.load_project(dialog.selected_path)

    @Slot()
    def refresh_project(self):
        if self.project_path: self.load_project(self.project_path)

    @Slot()
    def select_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Root Folder")
        if folder: self.load_project(folder)

    def load_project(self, path):
        self._is_loading_project = True
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.stop()
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000):
                print("Warning: Worker thread did not terminate gracefully.")
        
        self.project_path = get_long_path_name(path)
        self.setWindowTitle(f"LLM-Sherpa - {os.path.basename(self.project_path)}")
        self.tree_model.clear(); self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        self.key_files_table.setRowCount(0)
        self.log_text_edit.clear()
        self.config_manager.add_recent_project(self.project_path)
        self.update_recent_projects_menu()
        
        self.set_ui_enabled(False); self.loading_status_label.setText("Scanning project files...")
        QApplication.processEvents()
        
        self.worker_thread = QThread(self)
        self.worker = FileSystemWorker(self.project_path, self.settings_manager.settings)
        self.worker.moveToThread(self.worker_thread)
        
        self.worker_thread.started.connect(self.worker.run)
        self.worker.results_ready.connect(self.populate_tree_from_data)
        self.worker.error.connect(self.on_loading_error)
        
        # Connect finished signals for proper cleanup
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._on_worker_finished)
        
        self.worker_thread.start()

    @Slot()
    def _on_worker_finished(self):
        """Slot to safely nullify worker and thread references after they are finished."""
        self.worker = None
        self.worker_thread = None

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
            type_item = QStandardItem(item_data['type']); type_item.setEditable(False)
            rel_path_item = QStandardItem(item_data['rel_path']); rel_path_item.setEditable(False)
            
            icon = file_icon
            if item_data['type'] == 'folder': icon = folder_icon
            elif os.path.splitext(item_data['name'])[-1].lower() == '.py': icon = py_icon
            elif item_data['type'] == 'class': icon = class_icon
            elif item_data['type'] == 'function': icon = func_icon
            name_item.setIcon(icon)

            parent_item.appendRow([name_item, type_item, rel_path_item if item_data['type'] != 'function' else QStandardItem("")])
            path_to_item_map[item_data['id']] = name_item
        
        self.on_loading_finished()
        QTimer.singleShot(0, lambda: self.tree_view.header().resizeSection(0, 400))

    @Slot(str)
    def on_loading_error(self, error_message):
        QMessageBox.critical(self, "Loading Error", f"Failed to load project structure:\n{error_message}")
        self.on_loading_finished()

    def on_loading_finished(self):
        self.loading_status_label.setText(""); self.set_ui_enabled(True)
        if self.project_path:
            if self.settings_manager.get("restore_tree_selection"):
                tree_handler.restore_tree_state(self)
            self._restore_component_roles()
        self.update_token_count()
        self._is_loading_project = False

    def set_ui_enabled(self, enabled):
        is_project_loaded = bool(self.project_path)
        self.generate_action.setEnabled(enabled and is_project_loaded)
        self.open_action.setEnabled(enabled)
        self.refresh_action.setEnabled(enabled and is_project_loaded)
        self.toggle_all_action.setEnabled(enabled and is_project_loaded)
        self.tree_view.setEnabled(enabled and is_project_loaded)

    # --- Menu, Toolbar, and Window Setup ---
    def create_actions(self):
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DirOpenIcon), "&Open Project...", self); self.open_action.triggered.connect(self.select_folder_dialog)
        self.refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "&Refresh", self); self.refresh_action.triggered.connect(self.refresh_project); self.refresh_action.setEnabled(False)
        self.generate_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "&Generate Context", self); self.generate_action.triggered.connect(self.generate_markdown); self.generate_action.setEnabled(False)
        self.exit_action = QAction("E&xit", self); self.exit_action.triggered.connect(self.close)
        self.toggle_all_action = QAction("&Toggle All Selections", self); self.toggle_all_action.triggered.connect(self.toggle_all_selections)
        self.settings_action = QAction("Settings...", self); self.settings_action.triggered.connect(self.open_settings)
        self.about_action = QAction("&About", self); self.about_action.triggered.connect(self.show_about_dialog)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("&File"); self.file_menu.addAction(self.open_action)
        self.recent_projects_menu = self.file_menu.addMenu("Recent Projects")
        self.file_menu.addSeparator(); self.file_menu.addAction(self.generate_action); self.file_menu.addSeparator(); self.file_menu.addAction(self.exit_action)
        edit_menu = menu_bar.addMenu("&Edit"); edit_menu.addAction(self.refresh_action); edit_menu.addAction(self.toggle_all_action)
        settings_menu = menu_bar.addMenu("&Settings"); settings_menu.addAction(self.settings_action)
        help_menu = menu_bar.addMenu("&Help"); help_menu.addAction(self.about_action)
        self.update_recent_projects_menu()

    def update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        recent_paths = list(dict.fromkeys(self.config_manager.get_recent_projects()))
        for path in recent_paths:
            if os.path.isdir(path):
                action = QAction(path, self); action.triggered.connect(partial(self.load_project, path)); self.recent_projects_menu.addAction(action)
        self.recent_projects_menu.setEnabled(len(recent_paths) > 0)

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar"); tool_bar.setMovable(False)
        tool_bar.addAction(self.open_action); tool_bar.addAction(self.refresh_action); tool_bar.addAction(self.generate_action)
        tool_bar.addSeparator(); tool_bar.addAction(self.settings_action)

    @Slot()
    def show_about_dialog(self):
        QMessageBox.about(self, "About LLM-Sherpa", "<h2>LLM-Sherpa v3.4</h2><p>An intelligent project briefing and context generation tool.</p>")

    def _get_component_roles(self):
        roles = {}
        for row in range(self.key_files_table.rowCount()):
            file_item = self.key_files_table.item(row, 0)
            role_item = self.key_files_table.item(row, 1)
            if file_item and role_item and file_item.text():
                roles[file_item.text().strip()] = role_item.text().strip()
        return roles

    def _restore_component_roles(self):
        state = self.config_manager.get("tree_states", {}).get(self.project_path, {})
        roles = state.get("component_roles", {})
        self.key_files_table.setRowCount(0)
        for file_path, role in roles.items():
            row_count = self.key_files_table.rowCount()
            self.key_files_table.insertRow(row_count)
            self.key_files_table.setItem(row_count, 0, QTableWidgetItem(file_path))
            self.key_files_table.setItem(row_count, 1, QTableWidgetItem(role))
        self.key_files_table.resizeColumnsToContents()

    def _save_project_state(self):
        """Saves the current state of the tree and component roles for the current project."""
        if not self.project_path or not self.settings_manager.get("restore_tree_selection"):
            return
        
        tree_states = self.config_manager.get("tree_states", {})
        current_state = tree_handler.get_tree_state(self)
        current_state["component_roles"] = self._get_component_roles()
        tree_states[self.project_path] = current_state
        
        self.config_manager.set("tree_states", tree_states)
        self.config_manager.save_config()

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.stop(); self.worker_thread.quit(); self.worker_thread.wait()
        if self.project_path:
            if self.settings_manager.get("remember_project_path"): 
                self.config_manager.set("last_project_path", self.project_path)
            self._save_project_state()
        self.config_manager.save_config()
        event.accept()

    @Slot()
    def on_tree_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes: self.code_preview.clear(); return
        item = self.tree_model.itemFromIndex(indexes[0])
        item_data = item.data(Qt.UserRole)
        if not item_data or item_data.get('type') == 'folder': self.code_preview.clear(); return
        
        code = content_utils.get_code_from_item(item_data)
        if PYGMENTS_AVAILABLE:
            try:
                lexer = get_lexer_by_name(self.settings_manager.get("extension_map").get(os.path.splitext(item_data['full_path'])[1].lower(), 'text'))
            except Exception:
                lexer = guess_lexer(code)
            formatter = HtmlFormatter(style='monokai', linenos='table', noclasses=False)
            html_fragment = highlight(code, lexer, formatter)
            full_html = f"<html><head><style>{self.pygments_css} body{{background-color:#272822;color:#f8f8f2;}}</style></head><body>{html_fragment}</body></html>"
            self.code_preview.setHtml(full_html)
        else:
            self.code_preview.setText(code)

    @Slot()
    def apply_prompt_template(self):
        template_name = self.prompt_template_combo.currentText()
        if template_name != "Custom Prompt":
            self.objective_text_edit.setPlainText(self.settings_manager.get("prompt_templates", {}).get(template_name, ""))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())