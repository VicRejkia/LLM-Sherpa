import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from functools import partial

# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QTextBrowser, QToolBar, QStyle,
    QHeaderView, QSplitter, QTabWidget, QComboBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QCheckBox, QScrollArea, QFormLayout
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QTimer

# --- Local Module Imports ---
from sherpa_modules.config import SettingsManager, ConfigManager
from sherpa_modules.worker import FileSystemWorker, get_long_path_name
from sherpa_modules.ui import WelcomeDialog
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
        self.setWindowTitle("LLM-Sherpa - Project Documenter v4.0")
        self.setGeometry(100, 100, 1400, 950)

        self.settings_manager = SettingsManager()
        self.config_manager = ConfigManager()
        self.project_path = ""
        self._is_updating_checks = False
        self._is_loading_project = False
        self.prompt_templates = {}
        self.master_template = ""
        self.prompt_module_widgets = {}

        self.worker = None
        self.worker_thread = None

        self.pygments_css = ""
        if PYGMENTS_AVAILABLE:
            formatter = HtmlFormatter(style='monokai')
            self.pygments_css = formatter.get_style_defs('.highlight')

        self.load_prompt_templates()
        self.init_ui()
        self._connect_signals()
        QTimer.singleShot(0, self.show_welcome_or_load_project)

    def load_prompt_templates(self):
        try:
            # Determine the base directory of the application
            if getattr(sys, 'frozen', False):
                # The application is frozen (e.g., packaged with PyInstaller)
                script_dir = os.path.dirname(sys.executable)
            else:
                # The application is running from a script
                script_dir = os.path.dirname(os.path.abspath(__file__))

            templates_path = os.path.join(script_dir, 'templates', 'prompt_templates.xml')
            
            if not os.path.exists(templates_path):
                QMessageBox.critical(self, "Template Error", f"File not found: 'prompt_templates.xml'.\n\nPlease ensure the 'templates' folder exists in the same directory as the application and contains this file.")
                return

            tree = ET.parse(templates_path)
            root = tree.getroot()
            self.master_template = root.find('master_template').text.strip()
            for template_node in root.findall('template'):
                template_name = template_node.get('name')
                # MODIFICATION: Use a list of dicts to preserve module order from XML
                modules = [
                    {
                        'name': module.get('name'),
                        'text': module.text.strip() if module.text else "",
                        'type': module.get('type', 'line'),
                        'editable': module.get('editable') == 'true'
                    }
                    for module in template_node.findall('module')
                ]
                self.prompt_templates[template_name] = modules
        except ET.ParseError as e:
            QMessageBox.critical(self, "Template Error", f"Failed to parse 'prompt_templates.xml':\n\n{e}")
            self.master_template = "Error: Master template could not be loaded."
            self.prompt_templates = {"Error": {}}
        except Exception as e:
            QMessageBox.critical(self, "Initialization Error", f"An unexpected error occurred while loading templates:\n\n{e}")

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

        self.markdown_preview_tab = QWidget()
        markdown_preview_layout = QVBoxLayout(self.markdown_preview_tab)
        markdown_preview_layout.addWidget(QLabel("<b>Final Markdown Preview:</b>"))
        self.markdown_preview_browser = QTextBrowser()
        self.markdown_preview_browser.setReadOnly(True)
        markdown_preview_layout.addWidget(self.markdown_preview_browser)
        self.main_tabs.addTab(self.markdown_preview_tab, "📄 Markdown Preview")

        # --- LLM Prompt Tab ---
        self.prompt_preview_tab = QWidget()
        prompt_preview_layout = QVBoxLayout(self.prompt_preview_tab)

        tip_label = QLabel("<b>Usage Tip:</b> For the best results, copy this prompt into your LLM's chat window and upload the saved codebase markdown file as an attachment.")
        tip_label.setWordWrap(True)
        tip_label.setStyleSheet("padding: 5px; border: 1px solid #444; border-radius: 4px; background-color: #333;")
        prompt_preview_layout.addWidget(tip_label)

        self.prompt_preview_browser = QTextBrowser()
        self.prompt_preview_browser.setReadOnly(True)
        self.prompt_preview_browser.setFont(QFont("Courier New", 11))
        prompt_preview_layout.addWidget(self.prompt_preview_browser)

        prompt_button_layout = QHBoxLayout()
        prompt_button_layout.addStretch()
        btn_copy_prompt = QPushButton("📋 Copy Prompt")
        btn_copy_prompt.clicked.connect(self.copy_prompt_to_clipboard)
        prompt_button_layout.addWidget(btn_copy_prompt)
        prompt_preview_layout.addLayout(prompt_button_layout)
        
        self.main_tabs.addTab(self.prompt_preview_tab, "🚀 LLM Prompt")


        # --- Prompt Engineering Workflow UI ---
        prompt_studio_container = QWidget()
        prompt_studio_layout = QVBoxLayout(prompt_studio_container)

        template_selector_layout = QHBoxLayout()
        template_selector_layout.addWidget(QLabel("<b>Select a Prompt Template:</b>"))
        self.template_selector_combo = QComboBox()
        if self.prompt_templates:
            self.template_selector_combo.addItems([""] + list(self.prompt_templates.keys()))
        template_selector_layout.addWidget(self.template_selector_combo, 1)
        prompt_studio_layout.addLayout(template_selector_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.prompt_module_container = QWidget()
        self.prompt_module_layout = QFormLayout(self.prompt_module_container)
        self.prompt_module_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.scroll_area.setWidget(self.prompt_module_container)
        prompt_studio_layout.addWidget(self.scroll_area, 1)

        self.components_tab = QWidget()
        components_layout = QVBoxLayout(self.components_tab)
        self.preamble_checkbox = QCheckBox("Generate 'Table of Contents' Preamble")
        self.preamble_checkbox.setChecked(True)
        components_layout.addWidget(self.preamble_checkbox)
        components_layout.addWidget(QLabel("<b>Key Files & Roles (for Project Context):</b>"))
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
        
        self.prompt_tabs = QTabWidget()
        self.prompt_tabs.addTab(prompt_studio_container, "🚀 Prompt Studio")
        self.prompt_tabs.addTab(self.components_tab, "🧩 Components")
        main_splitter.addWidget(self.prompt_tabs)

        main_splitter.setSizes([650, 300])

        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.loading_status_label = QLabel("")
        self.status_bar.addWidget(self.loading_status_label)
        self.token_budget_combo = QComboBox(); self.token_budget_combo.addItems(["No Budget"] + list(self.settings_manager.get("llm_token_budgets", {}).keys())); self.status_bar.addPermanentWidget(self.token_budget_combo)
        self.token_progress_bar = QProgressBar(); self.token_progress_bar.setMaximumWidth(200); self.token_progress_bar.setTextVisible(False); self.status_bar.addPermanentWidget(self.token_progress_bar)
        self.token_count_label = QLabel("Size: ~0 tokens"); self.status_bar.addPermanentWidget(self.token_count_label)

        if self.prompt_templates:
            self._on_template_selected(self.template_selector_combo.currentText())

    def _connect_signals(self):
        self.tree_view.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)
        self.tree_model.itemChanged.connect(self.on_item_changed)
        self.log_text_edit.textChanged.connect(self._on_content_changed)
        self.key_files_table.itemChanged.connect(self._on_content_changed)
        self.token_budget_combo.currentTextChanged.connect(self.update_token_count)
        self.preamble_checkbox.stateChanged.connect(self._on_content_changed)
        self.template_selector_combo.currentTextChanged.connect(self._on_template_selected)

    @Slot(str)
    def _on_template_selected(self, template_name):
        # Clear existing dynamic widgets
        while self.prompt_module_layout.count():
            item = self.prompt_module_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.prompt_module_widgets.clear()

        if not template_name or template_name not in self.prompt_templates:
            self._on_content_changed()
            return

        # MODIFICATION: Iterate over the list of modules to preserve order
        template_modules = self.prompt_templates[template_name]
        for module_data in template_modules:
            name = module_data['name']
            label = QLabel(f"<b>{name.replace('_', ' ').title()}:</b>")
            
            if module_data['type'] == 'multiline':
                widget = QTextEdit(module_data['text'])
                widget.setAcceptRichText(False)
                doc_height = widget.document().size().height()
                widget.setMinimumHeight(int(doc_height) + 15)
            else:
                widget = QTextEdit(module_data['text'])
                widget.setAcceptRichText(False)
                widget.setFixedHeight(40)

            widget.setReadOnly(not module_data['editable'])
            widget.textChanged.connect(self._on_content_changed)
            self.prompt_module_layout.addRow(label, widget)
            self.prompt_module_widgets[name] = widget
        
        self._on_content_changed()

    def _assemble_prompt(self):
        """
        Assembles the final prompt from the master template and module widgets.
        The prompt is formatted for readability and excludes the project context,
        which is intended to be provided as a separate file.
        """
        # If no template is selected, show a helpful hint.
        if not self.template_selector_combo.currentText():
            return "Please select a Prompt Template from the 'Prompt Studio' tab to generate a final prompt."

        if not self.master_template:
            return "Error: Master template not loaded."

        prompt_text = self.master_template
        
        # 1. Populate modules from UI widgets
        for name, widget in self.prompt_module_widgets.items():
            placeholder = f"{{{{{name}}}}}"
            content = widget.toPlainText().strip()
            prompt_text = prompt_text.replace(placeholder, content)

        # 2. Handle optional sections (e.g., {{#if reasoning_module}}...{{/if}})
        def handle_optional(match):
            module_name = match.group(1)
            inner_content = match.group(2)
            if module_name in self.prompt_module_widgets and self.prompt_module_widgets[module_name].toPlainText().strip():
                return inner_content
            return ""
        prompt_text = re.sub(r"\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}", handle_optional, prompt_text, flags=re.DOTALL)
        
        # 3. Exclude the project_context section entirely, as it's provided separately.
        prompt_text = re.sub(r"<project_context>.*?</project_context>", "", prompt_text, flags=re.DOTALL)

        # 4. Convert XML-like tags to Markdown headers for better readability.
        def tags_to_markdown(match):
            tag_name = match.group(1).replace('_', ' ').title()
            content = match.group(2).strip()
            # Only add the section if there is content inside the tags
            return f"### {tag_name}\n\n{content}" if content else ""
        prompt_text = re.sub(r"<(\w+)>([\s\S]*?)</\1>", tags_to_markdown, prompt_text)

        # 5. Clean up any remaining unfilled placeholders and excessive newlines.
        prompt_text = re.sub(r"\{\{\w+\}\}", "", prompt_text)
        prompt_text = re.sub(r'\n\s*\n', '\n\n', prompt_text) # Collapse multiple blank lines

        return prompt_text.strip()

    @Slot()
    def _on_content_changed(self):
        """Central hub for updating UI elements when content changes."""
        self.update_token_count()
        self._update_markdown_preview()
        self._update_prompt_preview() 
        if not self._is_loading_project:
            self._save_project_state()

    # --- Action Slots (Delegating to modules) ---
    @Slot()
    def save_codebase_markdown(self):
        actions.save_codebase_markdown_action(self)

    @Slot()
    def focus_prompt_tab(self): # NEW METHOD
        """Switches the main tab view to the LLM Prompt tab."""
        for i in range(self.main_tabs.count()):
            if self.main_tabs.tabText(i) == "🚀 LLM Prompt":
                self.main_tabs.setCurrentIndex(i)
                break

    @Slot()
    def open_settings(self):
        actions.open_settings_action(self)
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

    @Slot()
    def _update_markdown_preview(self):
        """Generates and displays the codebase markdown preview."""
        markdown_content = actions.assemble_codebase_markdown(self)
        self.markdown_preview_browser.setMarkdown(markdown_content)
    
    @Slot()
    def _update_prompt_preview(self): # NEW METHOD
        """Generates and displays the final LLM prompt preview."""
        prompt_content = self._assemble_prompt()
        self.prompt_preview_browser.setText(prompt_content)

    @Slot()
    def copy_prompt_to_clipboard(self): # NEW METHOD
        """Copies the content of the prompt preview browser to the clipboard."""
        from PySide6.QtGui import QClipboard
        clipboard = QApplication.clipboard()
        clipboard.setText(self.prompt_preview_browser.toPlainText())
        QMessageBox.information(self, "Copied!", "The final prompt has been copied to your clipboard.")

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
        prompt_chars = len(actions.assemble_final_prompt(self))
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

    # --- Project Loading and Management (largely unchanged) ---
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
        self._on_content_changed() # Initial update
        self._is_loading_project = False

    def set_ui_enabled(self, enabled):
        is_project_loaded = bool(self.project_path)
        self.save_markdown_action.setEnabled(enabled and is_project_loaded)
        self.generate_prompt_action.setEnabled(enabled and is_project_loaded)
        self.open_action.setEnabled(enabled)
        self.refresh_action.setEnabled(enabled and is_project_loaded)
        self.toggle_all_action.setEnabled(enabled and is_project_loaded)
        self.tree_view.setEnabled(enabled and is_project_loaded)

    # --- Menu, Toolbar, and Window Setup ---
    def create_actions(self):
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DirOpenIcon), "&Open Project...", self)
        self.open_action.triggered.connect(self.select_folder_dialog)
        
        self.refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "&Refresh", self)
        self.refresh_action.triggered.connect(self.refresh_project)
        self.refresh_action.setEnabled(False)

        self.save_markdown_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "&Save Codebase Markdown...", self)
        self.save_markdown_action.triggered.connect(self.save_codebase_markdown)
        self.save_markdown_action.setEnabled(False)

        self.exit_action = QAction("E&xit", self)
        self.exit_action.triggered.connect(self.close)
        
        self.toggle_all_action = QAction("&Toggle All Selections", self)
        self.toggle_all_action.triggered.connect(self.toggle_all_selections)
        
        self.settings_action = QAction("Settings...", self)
        self.settings_action.triggered.connect(self.open_settings)
        
        self.about_action = QAction("&About", self)
        self.about_action.triggered.connect(self.show_about_dialog)

        self.generate_prompt_action = QAction(QIcon.fromTheme("document-send", self.style().standardIcon(QStyle.SP_CustomBase)), "🚀 &Generate Final Prompt", self)
        self.generate_prompt_action.triggered.connect(self.focus_prompt_tab) # CHANGED
        self.generate_prompt_action.setEnabled(False)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("&File")
        self.file_menu.addAction(self.open_action)
        self.recent_projects_menu = self.file_menu.addMenu("Recent Projects")
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.save_markdown_action)
        self.file_menu.addAction(self.generate_prompt_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.refresh_action)
        edit_menu.addAction(self.toggle_all_action)
        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self.settings_action)
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.about_action)
        self.update_recent_projects_menu()

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar")
        tool_bar.setMovable(False)
        tool_bar.addAction(self.open_action)
        tool_bar.addAction(self.refresh_action)
        tool_bar.addSeparator()
        tool_bar.addAction(self.save_markdown_action)
        tool_bar.addAction(self.generate_prompt_action)
        tool_bar.addSeparator()
        tool_bar.addAction(self.settings_action)

    def update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        recent_paths = list(dict.fromkeys(self.config_manager.get_recent_projects()))
        for path in recent_paths:
            if os.path.isdir(path):
                action = QAction(path, self); action.triggered.connect(partial(self.load_project, path)); self.recent_projects_menu.addAction(action)
        self.recent_projects_menu.setEnabled(len(recent_paths) > 0)

    @Slot()
    def show_about_dialog(self):
        QMessageBox.about(self, "About LLM-Sherpa", "<h2>LLM-Sherpa v4.0</h2><p>An intelligent project briefing and context generation tool.</p>")

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())