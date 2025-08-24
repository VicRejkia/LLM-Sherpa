import os
import sys
import json
import re
import xml.etree.ElementTree as ET
from functools import partial

# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QFileDialog, QMessageBox,
    QLabel, QStatusBar, QTextBrowser, QToolBar, QStyle,
    QSplitter, QTabWidget, QComboBox, QProgressBar,
    QTableWidgetItem
)
from PySide6.QtGui import QStandardItem, QAction, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QTimer

# --- Local Module Imports ---
from sherpa_modules.config import SettingsManager, ConfigManager
from sherpa_modules.worker import FileSystemWorker, get_long_path_name
from sherpa_modules.ui import WelcomeDialog
from sherpa_modules import actions, tree_handler, content_utils
from sherpa_modules.components.project_view import ProjectView
from sherpa_modules.components.log_view import LogView
from sherpa_modules.components.workspace_manager import WorkspaceManager

class ProjectDocumenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM-Sherpa - Project Documenter v4.1 (Refactored)")
        self.setGeometry(100, 100, 1400, 950)

        self.settings_manager = SettingsManager()
        self.config_manager = ConfigManager()
        self.project_path = ""
        self._is_updating_checks = False
        self._is_loading_project = False
        self.prompt_templates = {}
        self.master_template = ""

        self.worker = None
        self.worker_thread = None

        # --- NEW: Debounce timer for UI updates ---
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self.update_timer.setInterval(400) # 400ms delay for updates

        self.load_prompt_templates()
        self.init_ui()
        self._connect_signals()
        QTimer.singleShot(0, self.show_welcome_or_load_project)

    def load_prompt_templates(self):
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__)) if not getattr(sys, 'frozen', False) else os.path.dirname(sys.executable)
            templates_path = os.path.join(script_dir, 'templates', 'prompt_templates.xml')
            
            if not os.path.exists(templates_path):
                QMessageBox.critical(self, "Template Error", "File not found: 'prompt_templates.xml'.")
                return

            tree = ET.parse(templates_path)
            root = tree.getroot()
            self.master_template = root.find('master_template').text.strip()
            for template_node in root.findall('template'):
                template_name = template_node.get('name')
                modules = [
                    {'name': module.get('name'), 'text': (module.text or "").strip(),
                     'type': module.get('type', 'line'), 'editable': module.get('editable') == 'true'}
                    for module in template_node.findall('module')
                ]
                self.prompt_templates[template_name] = modules
        except Exception as e:
            QMessageBox.critical(self, "Template Error", f"Failed to parse 'prompt_templates.xml':\n{e}")

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.create_actions()
        self.create_menu_bar()
        self.create_tool_bar()

        main_splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(main_splitter)

        # --- Top Container (Tabs) ---
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.main_tabs = QTabWidget()
        top_layout.addWidget(self.main_tabs)
        main_splitter.addWidget(top_container)

        # --- Component Instantiation ---
        self.project_view = ProjectView(self.settings_manager)
        self.log_view = LogView()
        self.workspace_manager = WorkspaceManager(self.prompt_templates)

        self.main_tabs.addTab(self.project_view, "📂 Project")
        self.main_tabs.addTab(self.log_view, "📋 Logs / Console")
        
        # Markdown and Prompt Preview Tabs (remain simple)
        self._create_preview_tabs()
        
        main_splitter.addWidget(self.workspace_manager)
        main_splitter.setSizes([650, 300])

        self._create_status_bar()
        
        # Manually trigger initial setup for prompt studio
        self.workspace_manager.on_template_selected(self.workspace_manager.template_selector_combo.currentText())

    def _create_preview_tabs(self):
        # Markdown Preview
        markdown_tab = QWidget()
        markdown_layout = QVBoxLayout(markdown_tab)
        markdown_layout.addWidget(QLabel("<b>Final Markdown Preview:</b>"))
        self.markdown_preview_browser = QTextBrowser()
        self.markdown_preview_browser.setReadOnly(True)
        markdown_layout.addWidget(self.markdown_preview_browser)
        self.main_tabs.addTab(markdown_tab, "📄 Markdown Preview")

        # LLM Prompt Preview
        prompt_tab = QWidget()
        prompt_layout = QVBoxLayout(prompt_tab)
        tip_label = QLabel("<b>Usage Tip:</b> Copy this prompt and upload the saved markdown file to your LLM.")
        tip_label.setWordWrap(True); tip_label.setStyleSheet("padding: 5px; border: 1px solid #444; border-radius: 4px; background-color: #333;")
        prompt_layout.addWidget(tip_label)
        self.prompt_preview_browser = QTextBrowser()
        self.prompt_preview_browser.setReadOnly(True)
        self.prompt_preview_browser.setFont(QFont("Courier New", 11))
        prompt_layout.addWidget(self.prompt_preview_browser)
        btn_copy = QPushButton("📋 Copy Prompt"); btn_copy.clicked.connect(self.copy_prompt_to_clipboard)
        btn_layout = QHBoxLayout(); btn_layout.addStretch(); btn_layout.addWidget(btn_copy)
        prompt_layout.addLayout(btn_layout)
        self.main_tabs.addTab(prompt_tab, "🚀 LLM Prompt")

    def _create_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.loading_status_label = QLabel("")
        self.status_bar.addWidget(self.loading_status_label)
        self.token_budget_combo = QComboBox()
        self.token_budget_combo.addItems(["No Budget"] + list(self.settings_manager.get("llm_token_budgets", {}).keys()))
        self.status_bar.addPermanentWidget(self.token_budget_combo)
        self.token_progress_bar = QProgressBar()
        self.token_progress_bar.setMaximumWidth(200); self.token_progress_bar.setTextVisible(False)
        self.status_bar.addPermanentWidget(self.token_progress_bar)
        self.token_count_label = QLabel("Size: ~0 tokens")
        self.status_bar.addPermanentWidget(self.token_count_label)

    def _connect_signals(self):
        # --- MODIFIED: Connect signals to the debounced update request ---
        self.project_view.model().itemChanged.connect(self.on_item_changed)
        self.log_view.log_text_edit.textChanged.connect(self.request_update)
        self.workspace_manager.content_changed.connect(self.request_update)
        self.workspace_manager.template_selected.connect(self.on_template_switch_requested)

        self.workspace_manager.btn_add_files_to_table.clicked.connect(self._populate_key_files_table)
        self.workspace_manager.btn_remove_files_from_table.clicked.connect(self._remove_selected_key_files)
        
        self.token_budget_combo.currentTextChanged.connect(self.update_token_count)

        # --- NEW: Connect timer to the actual update function ---
        self.update_timer.timeout.connect(self.perform_update)


    def _assemble_prompt(self):
        if not self.workspace_manager.template_selector_combo.currentText():
            return "Please select a Prompt Template from the 'Prompt Studio' tab."
        if not self.master_template: return "Error: Master template not loaded."

        prompt_text = self.master_template
        for name, widget in self.workspace_manager.prompt_module_widgets.items():
            prompt_text = prompt_text.replace(f"{{{{{name}}}}}", widget.toPlainText().strip())

        def handle_optional(match):
            module_name, inner_content = match.groups()
            widgets = self.workspace_manager.prompt_module_widgets
            return inner_content if module_name in widgets and widgets[module_name].toPlainText().strip() else ""
        prompt_text = re.sub(r"\{\{#if (\w+)\}\}(.*?)\{\{/if\}\}", handle_optional, prompt_text, flags=re.DOTALL)
        
        prompt_text = re.sub(r"<project_context>.*?</project_context>", "", prompt_text, flags=re.DOTALL)
        prompt_text = re.sub(r"<(\w+)>([\s\S]*?)</\1>", lambda m: f"### {m.group(1).replace('_', ' ').title()}\n\n{m.group(2).strip()}" if m.group(2).strip() else "", prompt_text)
        prompt_text = re.sub(r"\{\{\w+\}\}", "", prompt_text)
        return re.sub(r'\n\s*\n', '\n\n', prompt_text).strip()

    # --- NEW: Lightweight slot that starts the debouncing timer ---
    @Slot()
    def request_update(self):
        """Restarts the update timer. Called frequently by UI events."""
        if self._is_loading_project or self.workspace_manager._is_switching_templates:
            return
        self.update_timer.start()

    # --- MODIFIED: Renamed from _on_content_changed. Now called by the timer. ---
    @Slot()
    def perform_update(self):
        """Performs all expensive UI updates. Called infrequently by the timer."""
        if self._is_loading_project or self.workspace_manager._is_switching_templates:
            return
        self.update_token_count()
        self._update_markdown_preview()
        self._update_prompt_preview()
        self._save_project_state()

    # --- Action Slots (Delegated) ---
    @Slot()
    def save_codebase_markdown(self): actions.save_codebase_markdown_action(self)
    @Slot()
    def open_settings(self): actions.open_settings_action(self)
    @Slot()
    def toggle_all_selections(self): actions.toggle_all_selections_action(self)

    @Slot()
    def focus_prompt_tab(self):
        self.main_tabs.setCurrentIndex(3) # Index of LLM Prompt tab

    @Slot()
    def copy_prompt_to_clipboard(self):
        QApplication.clipboard().setText(self.prompt_preview_browser.toPlainText())
        QMessageBox.information(self, "Copied!", "The final prompt has been copied to your clipboard.")

    @Slot(QStandardItem)
    def on_item_changed(self, item): tree_handler.on_item_changed(self, item)

    def _update_markdown_preview(self):
        markdown_content = actions.assemble_codebase_markdown(self)
        self.markdown_preview_browser.setMarkdown(markdown_content)
    
    def _update_prompt_preview(self):
        prompt_content = self._assemble_prompt()
        self.prompt_preview_browser.setText(prompt_content)

    @Slot(str)
    def on_template_switch_requested(self, new_template_name):
        """
        Handles the entire process of switching between selection templates.
        First, it saves the current UI state to the outgoing template, then it
        loads the state from the newly selected template.
        """
        wm = self.workspace_manager

        # Prevent recursive signals or reloading the same template
        if wm._is_switching_templates or wm.active_template_name == new_template_name:
            return

        # 1. Save the current UI state to the *old* active template.
        # The wm.active_template_name still holds the name of the template we are leaving.
        self._save_project_state()

        # 2. Get the state data for the new template.
        if new_template_name in wm.templates:
            state_to_load = wm.templates[new_template_name]
            # 3. Load the new state. This will also update wm.active_template_name.
            self._load_state_from_template(new_template_name, state_to_load)
        else:
            QMessageBox.warning(self, "Template Error", f"Could not find data for template '{new_template_name}'.")


    @Slot()
    def _populate_key_files_table(self):
        selected_indexes = self.project_view.view().selectionModel().selectedIndexes()
        if not selected_indexes:
            QMessageBox.information(self, "Info", "Select files in the tree view first.")
            return

        files_to_add = {
            item.data(Qt.UserRole).get('rel_path')
            for index in selected_indexes if index.column() == 0
            for item in [self.project_view.model().itemFromIndex(index)]
            if item.data(Qt.UserRole) and item.data(Qt.UserRole).get('type') == 'file'
        }
        
        table = self.workspace_manager.key_files_table
        for file_path in sorted(list(files_to_add)):
            row_count = table.rowCount()
            table.insertRow(row_count)
            table.setItem(row_count, 0, QTableWidgetItem(file_path))
            table.setItem(row_count, 1, QTableWidgetItem(""))
        table.resizeColumnsToContents()

    @Slot()
    def _remove_selected_key_files(self):
        table = self.workspace_manager.key_files_table
        selected_rows = sorted(list(set(index.row() for index in table.selectedIndexes())), reverse=True)
        if not selected_rows:
            QMessageBox.information(self, "Info", "Select a file in the table to remove.")
            return
        for row in selected_rows: table.removeRow(row)

    def update_token_count(self):
        prompt_chars = len(self._assemble_prompt())
        # Use the same function that builds the markdown preview for an accurate count
        markdown_chars = len(actions.assemble_codebase_markdown(self))
        
        estimated_tokens = int((prompt_chars + markdown_chars) / 4)
        self.token_count_label.setText(f"Size: ~{estimated_tokens:,} tokens")

        budgets = self.settings_manager.get("llm_token_budgets", {})
        budget_name = self.token_budget_combo.currentText()
        if budget_name in budgets:
            budget = budgets[budget_name]
            self.token_progress_bar.setVisible(True)
            self.token_progress_bar.setMaximum(budget)
            self.token_progress_bar.setValue(min(estimated_tokens, budget))
            ratio = estimated_tokens / budget if budget > 0 else 0
            color = "green" if ratio <= 0.7 else "orange" if ratio <= 0.9 else "red"
            self.token_progress_bar.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")
        else:
            self.token_progress_bar.setVisible(False)

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
            self.worker_thread.wait(5000)

        self.project_path = get_long_path_name(os.path.normpath(path)).replace(os.sep, '/')
        self.setWindowTitle(f"LLM-Sherpa - {os.path.basename(self.project_path)}")
        self.project_view.clear_tree()
        self.log_view.clear()
        self.workspace_manager.key_files_table.setRowCount(0)
        self.workspace_manager.project_description_text_edit.clear()

        self.config_manager.add_recent_project(self.project_path)
        self.update_recent_projects_menu()

        self.set_ui_enabled(False)
        self.loading_status_label.setText("Scanning project files...")

        self.worker_thread = QThread(self)
        self.worker = FileSystemWorker(self.project_path, self.settings_manager.settings)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.results_ready.connect(self.on_worker_results)
        self.worker.error.connect(self.on_loading_error)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._on_worker_finished)
        self.worker_thread.start()

    @Slot()
    def _on_worker_finished(self): self.worker = self.worker_thread = None

    @Slot(list)
    def on_worker_results(self, items_data):
        self.loading_status_label.setText("Building tree view...")
        self.project_view.populate_from_data(items_data)
        self.on_loading_finished()

    @Slot(str)
    def on_loading_error(self, error_message):
        QMessageBox.critical(self, "Loading Error", f"Failed to load project structure:\n{error_message}")
        self.on_loading_finished()

    def on_loading_finished(self):
        self.loading_status_label.setText(""); self.set_ui_enabled(True)
        if self.project_path and self.settings_manager.get("restore_tree_selection"):
            self._restore_project_state()
        self._is_loading_project = False
        self.perform_update() # Perform an initial update immediately

    def set_ui_enabled(self, enabled):
        is_project_loaded = bool(self.project_path)
        self.save_markdown_action.setEnabled(enabled and is_project_loaded)
        self.generate_prompt_action.setEnabled(enabled and is_project_loaded)
        self.open_action.setEnabled(enabled)
        self.refresh_action.setEnabled(enabled and is_project_loaded)
        self.toggle_all_action.setEnabled(enabled and is_project_loaded)
        self.project_view.setEnabled(enabled and is_project_loaded)

    def create_actions(self):
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DirOpenIcon), "&Open Project...", self, triggered=self.select_folder_dialog)
        self.refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "&Refresh", self, triggered=self.refresh_project, enabled=False)
        self.save_markdown_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "&Save Codebase Markdown...", self, triggered=self.save_codebase_markdown, enabled=False)
        self.exit_action = QAction("E&xit", self, triggered=self.close)
        self.toggle_all_action = QAction("&Toggle All Selections", self, triggered=self.toggle_all_selections)
        self.settings_action = QAction("Settings...", self, triggered=self.open_settings)
        self.about_action = QAction("&About", self, triggered=self.show_about_dialog)
        self.generate_prompt_action = QAction(QIcon.fromTheme("document-send"), "🚀 &Generate Final Prompt", self, triggered=self.focus_prompt_tab, enabled=False)

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
        menu_bar.addMenu("&Settings").addAction(self.settings_action)
        menu_bar.addMenu("&Help").addAction(self.about_action)
        self.update_recent_projects_menu()

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar")
        tool_bar.setMovable(False)
        tool_bar.addActions([self.open_action, self.refresh_action])
        tool_bar.addSeparator()
        tool_bar.addActions([self.save_markdown_action, self.generate_prompt_action])
        tool_bar.addSeparator()
        tool_bar.addAction(self.settings_action)

    def update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        paths = [p for p in self.config_manager.get_recent_projects() if os.path.isdir(p)]
        for path in paths:
            # --- FIXED LINE ---
            # The lambda captures the current 'path' value (p=path) and ignores the
            # 'checked' boolean argument sent by the triggered signal.
            action = QAction(path, self, triggered=lambda checked=False, p=path: self.load_project(p))
            self.recent_projects_menu.addAction(action)
        self.recent_projects_menu.setEnabled(bool(paths))

    def show_about_dialog(self): QMessageBox.about(self, "About LLM-Sherpa", "<h2>LLM-Sherpa v4.1</h2><p>Refactored with a component-based architecture.</p>")

    def _get_full_ui_state(self):
        state = tree_handler.get_tree_state(self)
        workspace_state = self.workspace_manager.get_full_ui_state()
        state.update(workspace_state)
        state["logs"] = self.log_view.toPlainText()
        state["token_budget"] = self.token_budget_combo.currentText()
        return state

    def _load_state_from_template(self, template_name, state_data):
        self.workspace_manager._is_switching_templates = True
        
        if state_data:
            tree_handler.restore_tree_state(self, state=state_data)
            self.log_view.setPlainText(state_data.get("logs", ""))
            self.workspace_manager.load_state(state_data, template_name)
            self.token_budget_combo.setCurrentText(state_data.get("token_budget", "No Budget"))
        
        QApplication.processEvents() # Allow UI to update before finishing
        self.workspace_manager._is_switching_templates = False
        self.perform_update() # Update immediately after loading state

    def _restore_project_state(self):
        project_data = self.config_manager.get("tree_states", {}).get(self.project_path, {})
        state_to_load, active_template = self.workspace_manager.restore_project_templates(project_data)
        self._load_state_from_template(active_template, state_to_load)

    def _save_project_state(self):
        if not self.project_path or self._is_loading_project or self.workspace_manager._is_switching_templates or not self.settings_manager.get("restore_tree_selection"):
            return

        wm = self.workspace_manager
        
        # --- FIXED: Do not read the current selection from the widget here. ---
        # The wm.active_template_name is the source of truth and is managed
        # correctly by the template switching and creation logic.
        
        # Ensure the active template exists in the dictionary before saving
        if wm.active_template_name and wm.active_template_name not in wm.templates:
            wm.templates[wm.active_template_name] = {}
        
        # Get the full state and save it to the active template
        if wm.active_template_name:
            current_state = self._get_full_ui_state()
            wm.templates[wm.active_template_name] = current_state
        
            # Save all templates for the project back to the config
            tree_states = self.config_manager.get("tree_states", {})
            project_data = {"last_active_template": wm.active_template_name, "templates": wm.templates}
            tree_states[self.project_path] = project_data
            self.config_manager.set("tree_states", tree_states)

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker.stop(); self.worker_thread.quit(); self.worker_thread.wait()
        if self.project_path:
            if self.settings_manager.get("remember_project_path"):
                self.config_manager.set("last_project_path", self.project_path)
            self._save_project_state()
        self.config_manager.save_config()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())