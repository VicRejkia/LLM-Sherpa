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
    QHeaderView, QSizePolicy, QSplitter, QTabWidget, QComboBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QCheckBox
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QKeySequence, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QTimer

# --- Local Module Imports ---
from sherpa_modules.config import SettingsManager, ConfigManager
from sherpa_modules.worker import FileSystemWorker, get_long_path_name
from sherpa_modules.ui import WelcomeDialog, SettingsWindow, IterativeRefinementDialog, TDDWizard

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
        self.setWindowTitle("LLM-Sherpa - Project Documenter v3.2")
        self.setGeometry(100, 100, 1400, 950)

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
            formatter = HtmlFormatter(style=self.pygments_style)
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

        # --- Main vertical splitter (Top: Tree/Preview, Bottom: Prompt Studio) ---
        main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(main_splitter)

        # --- Top half container for Project/Logs tabs ---
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.main_tabs = QTabWidget()
        top_layout.addWidget(self.main_tabs)
        main_splitter.addWidget(top_container)

        # --- Tab 1: Project View ---
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
        preview_label_text = "Code Preview ✨"
        if not PYGMENTS_AVAILABLE:
            preview_label_text += " (Syntax highlighting requires 'pip install Pygments')"
        preview_layout.addWidget(QLabel(preview_label_text))
        self.code_preview = QTextBrowser()
        self.code_preview.setReadOnly(True)
        self.code_preview.setFont(QFont("Courier New", 11))
        preview_layout.addWidget(self.code_preview)
        self.horizontal_splitter.addWidget(preview_container)
        self.horizontal_splitter.setSizes([500, 600])

        # --- Tab 2: Logs/Console View ---
        log_tab_widget = QWidget()
        log_layout = QVBoxLayout(log_tab_widget)
        log_toolbar = QHBoxLayout()
        log_toolbar.addWidget(QLabel("Paste logs or console output here. Use tools to clean and reduce token count."))
        log_toolbar.addStretch()
        btn_clean_timestamps = QPushButton("Rm Timestamps"); btn_clean_timestamps.clicked.connect(self.clean_logs_timestamps); log_toolbar.addWidget(btn_clean_timestamps)
        btn_clean_ansi = QPushButton("Strip ANSI"); btn_clean_ansi.clicked.connect(self.clean_logs_ansi); log_toolbar.addWidget(btn_clean_ansi)
        btn_collapse_dups = QPushButton("Collapse Duplicates"); btn_collapse_dups.clicked.connect(self.collapse_duplicates); log_toolbar.addWidget(btn_collapse_dups)
        log_layout.addLayout(log_toolbar)
        self.log_text_edit = QTextEdit()
        self.log_text_edit.setPlaceholderText("Paste your error logs or console output here...")
        log_layout.addWidget(self.log_text_edit)
        self.main_tabs.addTab(log_tab_widget, "📋 Logs / Console")

        # --- Tab 3: Workflows (Bypassed as requested) ---
        # workflows_tab = QWidget()
        # workflows_layout = QVBoxLayout(workflows_tab)
        # workflows_layout.addWidget(QLabel("<h2>Automated Workflows</h2>"))
        # workflows_layout.addWidget(QLabel("Use these tools to orchestrate multi-step interactions with the LLM."))
        # btn_iterative = QPushButton("🔁 Start Iterative Refinement..."); btn_iterative.clicked.connect(self._start_iterative_refinement_dialog)
        # btn_tdd = QPushButton("✅ Generate TDD Feature..."); btn_tdd.clicked.connect(self._start_tdd_wizard)
        # workflows_layout.addWidget(btn_iterative); workflows_layout.addWidget(btn_tdd)
        # workflows_layout.addStretch()
        # self.main_tabs.addTab(workflows_tab, "🔁 Workflows")


        # --- Bottom half container for Prompt Studio ---
        prompt_studio_container = QWidget()
        prompt_studio_layout = QVBoxLayout(prompt_studio_container)
        
        # Task Selector
        task_selector_layout = QHBoxLayout()
        task_selector_layout.addWidget(QLabel("<b>Select a Task:</b>"))
        self.task_selector_combo = QComboBox()
        # Check if prompt_modules exists before accessing keys
        prompt_modules = self.settings_manager.get("prompt_modules", {})
        if prompt_modules:
            self.task_selector_combo.addItems(prompt_modules.keys())
        task_selector_layout.addWidget(self.task_selector_combo, 1)
        prompt_studio_layout.addLayout(task_selector_layout)

        self.prompt_tabs = QTabWidget()
        prompt_studio_layout.addWidget(self.prompt_tabs)
        main_splitter.addWidget(prompt_studio_container)
        
        # Prompt Tab 1: Objective
        objective_tab = QWidget()
        objective_layout = QVBoxLayout(objective_tab)
        self.prompt_template_combo = QComboBox()
        self.prompt_template_combo.addItem("Custom Prompt")
        self.prompt_template_combo.addItems(self.settings_manager.get("prompt_templates", {}).keys())
        self.objective_text_edit = QTextEdit()
        self.objective_text_edit.setPlaceholderText("Describe your main goal here...")
        objective_layout.addWidget(self.prompt_template_combo)
        objective_layout.addWidget(self.objective_text_edit)
        self.prompt_tabs.addTab(objective_tab, "🎯 Objective")

        # Prompt Tab 2: Components
        components_tab = QWidget()
        components_layout = QVBoxLayout(components_tab)
        self.preamble_checkbox = QCheckBox("Generate 'Table of Contents' Preamble in Context File")
        self.preamble_checkbox.setChecked(True)
        components_layout.addWidget(self.preamble_checkbox)
        components_layout.addWidget(QLabel("<b>Key Files & Roles (Optional):</b>"))
        self.key_files_table = QTableWidget(0, 2)
        self.key_files_table.setHorizontalHeaderLabels(["File", "Role/Description"])
        self.key_files_table.horizontalHeader().setStretchLastSection(True)
        components_layout.addWidget(self.key_files_table, 1)
        # Add button to populate table from selection
        btn_add_files_to_table = QPushButton("Add Selected Files from Tree")
        btn_add_files_to_table.clicked.connect(self._populate_key_files_table)
        components_layout.addWidget(btn_add_files_to_table)
        self.prompt_tabs.addTab(components_tab, "🧩 Components")

        # Prompt Tab 3: Preview
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
    
    @Slot()
    def _update_prompt_preview_and_tokens(self):
        self._update_prompt_preview()
        self.update_token_count()

    def _assemble_prompt(self):
        """Gathers all inputs and builds the final prompt string."""
        master_template = self.settings_manager.get("master_prompt_template", "{objective}")
        
        # 1. Get Objective
        objective = self.objective_text_edit.toPlainText().strip()
        
        # 2. Get Components
        components_text = ""
        key_files = []
        for row in range(self.key_files_table.rowCount()):
            file_item = self.key_files_table.item(row, 0)
            role_item = self.key_files_table.item(row, 1)
            if file_item and role_item and file_item.text() and role_item.text():
                key_files.append(f"- **{file_item.text().strip()}**: {role_item.text().strip()}")
        if key_files:
            components_text += "### Key Files Overview\n" + "\n".join(key_files) + "\n\n"
        
        # 3. Assemble
        full_prompt = master_template.format(objective=objective, components=components_text)
        return full_prompt.strip()

    @Slot()
    def _update_prompt_preview(self):
        """Updates the preview tab with the assembled prompt."""
        assembled_prompt = self._assemble_prompt()
        self.prompt_preview_browser.setPlainText(assembled_prompt)

    @Slot(str)
    def _on_task_selected(self, task_name):
        """Handles dynamic UI changes when a task is selected."""
        task_modules = self.settings_manager.get("prompt_modules", {})
        task_data = task_modules.get(task_name, {})
        
        # Pre-fill objective
        objective_template = task_data.get("objective", "")
        self.objective_text_edit.setPlainText(objective_template)
        
        # Focus relevant tab
        focus_tab = task_data.get("focus_tab")
        if focus_tab == "Logs / Console":
            self.main_tabs.setCurrentIndex(1) # Index of Logs tab
        else:
            self.main_tabs.setCurrentIndex(0) # Index of Project tab
        
        self._update_prompt_preview()

    @Slot()
    def _populate_key_files_table(self):
        selected_indexes = self.tree_view.selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.information(self, "Info", "Select files in the tree view first.")
            return

        # Get unique file paths from selection
        files_to_add = set()
        for index in selected_indexes:
            if index.column() == 0:
                item = self.tree_model.itemFromIndex(index)
                item_data = item.data(Qt.UserRole)
                if item_data and item_data.get('type') == 'file':
                    files_to_add.add(item_data.get('rel_path'))
        
        # Add new rows to table
        for file_path in sorted(list(files_to_add)):
            row_count = self.key_files_table.rowCount()
            self.key_files_table.insertRow(row_count)
            self.key_files_table.setItem(row_count, 0, QTableWidgetItem(file_path))
            self.key_files_table.setItem(row_count, 1, QTableWidgetItem(""))
        self.key_files_table.resizeColumnsToContents()
    
    @Slot()
    def _start_iterative_refinement_dialog(self):
        dialog = IterativeRefinementDialog(self)
        dialog.exec()
        
    @Slot()
    def _start_tdd_wizard(self):
        # Pass the main settings to the wizard so it can pull templates
        wizard = TDDWizard(self.settings_manager, self)
        wizard.exec()

    def _apply_tree_column_widths(self):
        header = self.tree_view.header()
        header.setSectionResizeMode(0, QHeaderView.Interactive); header.resizeSection(0, 400)
        header.setSectionResizeMode(1, QHeaderView.Interactive); header.resizeSection(1, 120)
        header.setSectionResizeMode(2, QHeaderView.Stretch)

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
        if item_data: # No need to check for type
            if item.hasChildren(): self._set_children_check_state(item, item.checkState())
        self._update_ancestor_check_state(item)
        self._is_updating_checks = False
        self.update_token_count()

    @Slot()
    def show_welcome_or_load_project(self):
        path_to_load = sys.argv[1] if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]) else None
        if path_to_load: self.load_project(path_to_load, is_initial_load=True)
        else:
            dialog = WelcomeDialog(self.config_manager.get_recent_projects(), self)
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
            self.worker.stop(); self.worker_thread.quit()
            if not self.worker_thread.wait(5000): print("Warning: Worker thread did not terminate gracefully.")
        self.project_path = get_long_path_name(path)
        self.setWindowTitle(f"LLM-Sherpa - {os.path.basename(self.project_path)}")
        self.tree_model.clear(); self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        self.key_files_table.setRowCount(0) # Clear components table
        if not is_initial_load: self.log_text_edit.clear()
        self.config_manager.add_recent_project(self.project_path); self.config_manager.save_config(); self.update_recent_projects_menu()
        self.set_ui_enabled(False); self.loading_status_label.setText("Scanning project files...")
        QApplication.processEvents()
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
            if item_type == 'folder': name_item.setIcon(folder_icon)
            elif item_type == 'file': name_item.setIcon(py_icon if os.path.splitext(item_data['name'])[-1].lower() == '.py' else file_icon)
            elif item_type == 'class': name_item.setIcon(class_icon)
            elif item_type == 'function': name_item.setIcon(func_icon)
            parent_item.appendRow([name_item, type_item, rel_path_item if item_type != 'function' else QStandardItem("")])
            path_to_item_map[item_data['id']] = name_item
        self.on_loading_finished()
        QTimer.singleShot(0, self._apply_tree_column_widths)

    @Slot(str)
    def on_loading_error(self, error_message):
        QMessageBox.critical(self, "Loading Error", f"Failed to load project structure:\n{error_message}")
        self.on_loading_finished()

    def on_loading_finished(self):
        self.loading_status_label.setText(""); self.set_ui_enabled(True)
        if self.project_path:
            if self.settings_manager.get("restore_tree_selection"):
                self.restore_tree_state()
            self._restore_component_roles() # Restore roles after tree is built
        self.update_token_count()

    def set_ui_enabled(self, enabled):
        is_project_loaded = bool(self.project_path)
        self.generate_action.setEnabled(enabled and is_project_loaded)
        self.open_action.setEnabled(enabled)
        self.refresh_action.setEnabled(enabled and is_project_loaded)
        self.toggle_all_action.setEnabled(enabled and is_project_loaded)
        self.tree_view.setEnabled(enabled and is_project_loaded)

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
        # BUG FIX: setEnabled expects a boolean. Check if the list of paths is non-empty.
        self.recent_projects_menu.setEnabled(len(recent_paths) > 0)

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar"); tool_bar.setMovable(False)
        tool_bar.addAction(self.open_action); tool_bar.addAction(self.refresh_action); tool_bar.addAction(self.generate_action)
        tool_bar.addSeparator(); tool_bar.addAction(self.settings_action)

    @Slot()
    def toggle_all_selections(self):
        root = self.tree_model.invisibleRootItem()
        if root.rowCount() > 0:
            is_all_checked = all(root.child(i, 0).checkState() == Qt.CheckState.Checked for i in range(root.rowCount()))
            new_state = Qt.CheckState.Unchecked if is_all_checked else Qt.CheckState.Checked
            for i in range(root.rowCount()):
                item = root.child(i, 0)
                if item: self._set_children_check_state(item, new_state)


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
                    if item.hasChildren() and self.tree_view.isExpanded(item.index()):
                        expanded_ids.append(item_id)
                        recurse(item)
        recurse(root)
        return {"checked": checked_ids, "expanded": expanded_ids}

    def restore_tree_state(self):
        state = self.config_manager.get("tree_states", {}).get(self.project_path)
        if not state: return
        self._is_updating_checks = True
        checked_set = set(state.get("checked", [])); expanded_set = set(state.get("expanded", []))
        q = [self.tree_model.invisibleRootItem()]
        while q:
            parent_item = q.pop(0)
            for row in range(parent_item.rowCount()):
                item = parent_item.child(row, 0)
                if not item: continue
                item_data = item.data(Qt.UserRole)
                if item_data:
                    item_id = item_data.get('id')
                    if item_id in checked_set: item.setCheckState(Qt.CheckState.Checked)
                    if item_id in expanded_set: self.tree_view.expand(item.index())
                if item.hasChildren(): q.append(item)
        self._is_updating_checks = False
        # Update ancestor states after restoring
        root = self.tree_model.invisibleRootItem()
        for row in range(root.rowCount()):
            for col in range(root.columnCount()):
                 child_item = root.child(row, col)
                 if child_item:
                    self._update_ancestor_check_state(child_item)


    def _get_code_from_item(self, item_data):
        file_path = item_data.get('full_path', '')
        if not file_path: return ""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: lines = f.readlines()
            if item_data.get('type') == 'file': return "".join(lines)
            elif item_data.get('type') in ('class', 'function'):
                start = item_data.get('start_line', 1) - 1
                end = item_data.get('end_line', len(lines))
                return "".join(lines[start:end])
        except (IOError, OSError): return ""
        return ""

    def _get_checked_content(self):
        """
        BUG FIX: Rewritten to prevent duplicate content and fix hashing error.
        It performs a top-down search. If a parent (like a file) is fully checked,
        it adds its content and skips all its children. It now uses a unique item ID
        for the `processed_items` set to avoid the unhashable type error.
        """
        content_map = {}
        # BUG FIX: QStandardItem is unhashable. Use a unique, hashable ID instead.
        processed_item_ids = set()

        def get_all_descendant_ids(item):
            """Returns a set of all descendant item IDs."""
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

        q = [self.tree_model.invisibleRootItem().child(i, 0) for i in range(self.tree_model.invisibleRootItem().rowCount())]
        
        while q:
            item = q.pop(0)
            if not item:
                continue

            item_data = item.data(Qt.UserRole)
            if not item_data:
                continue
            
            item_id = item_data.get('id')
            if item_id in processed_item_ids:
                continue

            is_checked = item.checkState() == Qt.CheckState.Checked
            is_partially_checked = item.checkState() == Qt.CheckState.PartiallyChecked
            
            item_type = item_data.get('type')

            if is_checked and item_type in ('file', 'class', 'function'):
                file_path = item_data.get('full_path')
                if file_path:
                    if file_path not in content_map:
                        content_map[file_path] = {'rel_path': os.path.relpath(file_path, self.project_path).replace(os.sep, '/'), 'snippets': []}
                    
                    content_map[file_path]['snippets'].append({
                        'content': self._get_code_from_item(item_data),
                        'name': item_data.get('name'),
                        'type': item_type
                    })
                
                # Since this item is fully checked, we don't need to process its children.
                processed_item_ids.add(item_id)
                processed_item_ids.update(get_all_descendant_ids(item))

            elif item.hasChildren() and (is_checked or is_partially_checked):
                # If it's partially checked, or a checked folder, we need to check its children.
                q.extend(item.child(i, 0) for i in range(item.rowCount()))

        # Consolidate snippets into final content
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


    def update_token_count(self):
        prompt_chars = len(self._assemble_prompt())
        log_chars = len(self.log_text_edit.toPlainText())
        code_chars = sum(len(item['content']) for item in self._get_checked_content())
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
            if ratio > 1.0: color, text = "red", f"Size: ~{estimated_tokens:,} tokens (Budget Exceeded!)"
            elif ratio > 0.9: color, text = "red", self.token_count_label.text()
            elif ratio > 0.7: color, text = "orange", self.token_count_label.text()
            else: color, text = "green", self.token_count_label.text()
            self.token_progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
            self.token_count_label.setText(text)
        else:
            self.token_progress_bar.setVisible(False)

    @Slot()
    def open_settings(self):
        dialog = SettingsWindow(self.settings_manager, self)
        if dialog.exec():
            self.prompt_template_combo.clear(); self.prompt_template_combo.addItems(["Custom Prompt"] + list(self.settings_manager.get("prompt_templates", {}).keys()))
            self.token_budget_combo.clear(); self.token_budget_combo.addItems(["No Budget"] + list(self.settings_manager.get("llm_token_budgets", {}).keys()))
            self.task_selector_combo.clear(); self.task_selector_combo.addItems(self.settings_manager.get("prompt_modules", {}).keys())
            if self.project_path: self.refresh_project()

    def _generate_tree_structure(self, file_paths):
        tree = {}; lines = ["."]
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
    
    def _generate_preamble(self, selected_content):
        """Generates a 'Table of Contents' style preamble."""
        preamble = "This project briefing contains the following key files:\n"
        paths = sorted([c['rel_path'] for c in selected_content])
        for rel_path in paths:
            preamble += f"- `{rel_path}`\n"
        return preamble + "\n"

    def generate_markdown(self):
        prompt_text = self._assemble_prompt()
        selected_content = self._get_checked_content()
        log_content = self.log_text_edit.toPlainText().strip()
        if not selected_content and not prompt_text and not log_content:
            QMessageBox.information(self, "Info", "Nothing to generate."); return
        
        # Get component roles
        component_roles = self._get_component_roles()

        output_file, _ = QFileDialog.getSaveFileName(self, "Save Context File", f"{os.path.basename(self.project_path)}_context.md", "Markdown Files (*.md)")
        if not output_file: return
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                if prompt_text: f.write(f"# 🎯 Objective\n\n{prompt_text}\n\n---\n\n")
                project_name = os.path.basename(os.path.normpath(self.project_path))
                f.write(f"## 📚 Project Context: `{project_name}`\n\n")
                
                if self.preamble_checkbox.isChecked() and selected_content:
                    f.write(self._generate_preamble(selected_content))
                    
                section_counter = 1
                if log_content:
                    f.write(f"### {section_counter}. Console Log / Error Output\n\n```\n{log_content}\n```\n\n")
                    section_counter += 1
                if self.settings_manager.get("show_project_structure") and selected_content:
                    f.write(f"### {section_counter}. Project Structure\n\n```\n{self._generate_tree_structure([c['rel_path'] for c in selected_content])}\n```\n\n")
                    section_counter += 1
                if selected_content:
                    f.write(f"### {section_counter}. File Contents\n\n")
                    ext_map = self.settings_manager.get("extension_map")
                    for code_file in sorted(selected_content, key=lambda x: x['rel_path']):
                        filename = os.path.basename(code_file['full_path'])
                        rel_path = code_file['rel_path'].replace(os.sep, '/')
                        lang = ext_map.get(os.path.splitext(filename)[1].lower(), "")
                        
                        f.write(f"#### 📄 `{filename}`\n")
                        # Add role if it exists
                        if rel_path in component_roles:
                            f.write(f"**Role:** {component_roles[rel_path]}\n\n")

                        f.write(f"*path: `{rel_path}`*\n\n```{lang}\n{code_file['content']}\n```\n\n")
            QMessageBox.information(self, "Success", f"Context file generated at:\n{output_file}")
        except Exception as e: QMessageBox.critical(self, "Error", f"Failed to generate documentation:\n{e}")

    @Slot()
    def show_about_dialog(self):
        QMessageBox.about(self, "About LLM-Sherpa", "<h2>LLM-Sherpa v3.2</h2><p>An intelligent project briefing and context generation tool for Large Language Models.</p><p><b>GitHub:</b> <a href='https://github.com/VicRejkia/LLM-Sherpa'>VicRejkia/LLM-Sherpa</a></p>")

    def _get_component_roles(self):
        """Extracts component roles from the QTableWidget."""
        roles = {}
        for row in range(self.key_files_table.rowCount()):
            file_item = self.key_files_table.item(row, 0)
            role_item = self.key_files_table.item(row, 1)
            if file_item and role_item and file_item.text() and role_item.text():
                roles[file_item.text().strip()] = role_item.text().strip()
        return roles

    def _restore_component_roles(self):
        """Populates the QTableWidget from saved config."""
        state = self.config_manager.get("tree_states", {}).get(self.project_path, {})
        roles = state.get("component_roles", {})
        self.key_files_table.setRowCount(0) # Clear existing
        for file_path, role in roles.items():
            row_count = self.key_files_table.rowCount()
            self.key_files_table.insertRow(row_count)
            self.key_files_table.setItem(row_count, 0, QTableWidgetItem(file_path))
            self.key_files_table.setItem(row_count, 1, QTableWidgetItem(role))
        self.key_files_table.resizeColumnsToContents()

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.stop(); self.worker_thread.quit(); self.worker_thread.wait()
        if self.project_path:
            if self.settings_manager.get("remember_project_path"): self.config_manager.set("last_project_path", self.project_path)
            if self.settings_manager.get("restore_tree_selection"):
                tree_states = self.config_manager.get("tree_states", {})
                current_state = self.get_tree_state()
                current_state["component_roles"] = self._get_component_roles() # Add roles
                tree_states[self.project_path] = current_state
                self.config_manager.set("tree_states", tree_states)
        self.config_manager.save_config(); event.accept()

    @Slot()
    def on_tree_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes: self.code_preview.clear(); return
        item = self.tree_model.itemFromIndex(indexes[0])
        item_data = item.data(Qt.UserRole)
        if not item_data or item_data.get('type') == 'folder': self.code_preview.clear(); return
        code = self._get_code_from_item(item_data)
        if PYGMENTS_AVAILABLE:
            try:
                lexer = get_lexer_by_name(self.settings_manager.get("extension_map").get(os.path.splitext(item_data['full_path'])[1].lower(), 'text'))
            except Exception:
                lexer = guess_lexer(code)
            formatter = HtmlFormatter(style=self.pygments_style, linenos='table', noclasses=False)
            html_fragment = highlight(code, lexer, formatter)
            full_html = f"<html><head><style>{self.pygments_css} body{{background-color:#272822;color:#f8f8f2;}} table{{border-spacing:0;}} td{{padding:0;white-space:pre-wrap;}} .linenos{{color:#8F908A;padding:.4em .8em;border-right:1px solid #49483e;user-select:none;}} .code{{padding:.4em !important;}}</style></head><body>{html_fragment}</body></html>"
            self.code_preview.setHtml(full_html)
        else:
            self.code_preview.setText(code)

    @Slot()
    def apply_prompt_template(self):
        template_name = self.prompt_template_combo.currentText()
        if template_name != "Custom Prompt": self.objective_text_edit.setPlainText(self.settings_manager.get("prompt_templates", {}).get(template_name, ""))

    @Slot()
    def clean_logs_timestamps(self):
        text = self.log_text_edit.toPlainText()
        pattern = re.compile(r"^\s*(?:\[.*?\])?\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?\s*-?\s*", re.MULTILINE)
        text = pattern.sub('', text)
        text = "\n".join(line for line in text.splitlines() if line.strip())
        self.log_text_edit.setPlainText(text.strip())

    @Slot()
    def clean_logs_ansi(self):
        text = self.log_text_edit.toPlainText()
        ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|\x1B\[[0-?]*[ -/]*[@-~])')
        text = ansi_escape.sub('', text)
        text = re.sub(r'\n\s*\n+', '\n', text)
        self.log_text_edit.setPlainText(text.strip())

    @Slot()
    def collapse_duplicates(self):
        lines = [line.strip() for line in self.log_text_edit.toPlainText().splitlines() if line.strip()]
        seen, order = {}, []
        for line in lines:
            if line not in seen:
                seen[line] = 1; order.append(line)
            else:
                seen[line] += 1
        new_lines = [f"{line} (x{seen[line]})" if seen[line] > 1 else line for line in order]
        self.log_text_edit.setPlainText("\n".join(new_lines))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())
