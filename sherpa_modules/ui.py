import os
import json
import sys

from PySide6.QtWidgets import (
    QDialog, QCheckBox, QLabel, QDialogButtonBox, QTextEdit,
    QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QMessageBox,
    QTabWidget, QWidget, QTextBrowser
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices

class SettingsWindow(QDialog):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        main_layout = QVBoxLayout(self)
        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # Tab 1: General
        general_tab = QWidget()
        layout = QVBoxLayout(general_tab)
        layout.addWidget(QLabel("<b>Persistence:</b>"))
        self.remember_path_chk = QCheckBox("Remember last project path on startup", checked=self.settings_manager.get("remember_project_path"))
        self.restore_tree_chk = QCheckBox("Restore tree selection for projects", checked=self.settings_manager.get("restore_tree_selection"))
        layout.addWidget(self.remember_path_chk); layout.addWidget(self.restore_tree_chk)
        layout.addWidget(QLabel("\n<b>Output Formatting:</b>"))
        self.show_structure_chk = QCheckBox("Include 'Project Structure' tree in output", checked=self.settings_manager.get("show_project_structure"))
        layout.addWidget(self.show_structure_chk)
        layout.addWidget(QLabel("\n<b>File Scanning:</b>"))
        self.exclude_dotfiles_chk = QCheckBox("Exclude all files and folders starting with '.'", checked=self.settings_manager.get("exclude_dotfiles"))
        layout.addWidget(self.exclude_dotfiles_chk)
        self.include_all_files_checkbox = QCheckBox("Include all file types in project tree")
        current_value = self.settings_manager.get("include_all_files", False)
        self.include_all_files_checkbox.setChecked(current_value)
        layout.addWidget(self.include_all_files_checkbox)
        layout.addStretch()
        tabs.addTab(general_tab, "General")
        

        # Tab 2: Exclusions & Mappings
        exclusions_tab = QWidget()
        layout = QVBoxLayout(exclusions_tab)
        layout.addWidget(QLabel("<b>Exclude files/folders by name (one per line):</b>"))
        self.exclude_text = QTextEdit(text="\n".join(self.settings_manager.get("exclude_list")))
        layout.addWidget(self.exclude_text)
        layout.addWidget(QLabel("\n<b>Map extensions to Markdown language identifiers (JSON):</b>"))
        self.ext_map_text = QTextEdit(text=json.dumps(self.settings_manager.get("extension_map"), indent=4))
        layout.addWidget(self.ext_map_text, stretch=2)
        tabs.addTab(exclusions_tab, "Exclusions & Mappings")

        # LLM Tab
        llm_tab = QWidget()
        layout = QVBoxLayout(llm_tab)
        layout.addWidget(QLabel("<b>LLM Token Budgets (JSON format):</b>"))
        self.token_budgets_text = QTextEdit(text=json.dumps(self.settings_manager.get("llm_token_budgets"), indent=4))
        layout.addWidget(self.token_budgets_text)
        layout.addStretch()
        tabs.addTab(llm_tab, "LLM Budgets")

        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def accept(self):
        self.settings_manager.set("remember_project_path", self.remember_path_chk.isChecked())
        self.settings_manager.set("restore_tree_selection", self.restore_tree_chk.isChecked())
        self.settings_manager.set("show_project_structure", self.show_structure_chk.isChecked())
        self.settings_manager.set("exclude_dotfiles", self.exclude_dotfiles_chk.isChecked())
        self.settings_manager.set("exclude_list", [item.strip() for item in self.exclude_text.toPlainText().strip().split("\n") if item.strip()])
        self.settings_manager.set("include_all_files", self.include_all_files_checkbox.isChecked())
        
        try:
            self.settings_manager.set("extension_map", json.loads(self.ext_map_text.toPlainText()))
            self.settings_manager.set("llm_token_budgets", json.loads(self.token_budgets_text.toPlainText()))
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", f"Error parsing JSON.\n\n{e}")
            return

        self.settings_manager.save_settings()
        super().accept()

class WelcomeDialog(QDialog):
    """Initial dialog to select a recent project or open a new one."""
    def __init__(self, recent_paths, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to LLM-Sherpa")
        self.setMinimumSize(500, 300)
        self.selected_path = None
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>Recent Projects</h2>"))
        self.list_widget = QListWidget()
        for path in recent_paths:
            if os.path.isdir(path):
                item = QListWidgetItem(f"{os.path.basename(path)}\n{path}"); item.setData(Qt.UserRole, path)
                self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)
        button_layout = QHBoxLayout()
        open_new_button = QPushButton("Open Another Project..."); open_new_button.clicked.connect(self.open_new)
        open_button = QPushButton("Open Selected"); open_button.clicked.connect(self.accept)
        cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(open_new_button); button_layout.addStretch(); button_layout.addWidget(open_button); button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def accept(self):
        current_item = self.list_widget.currentItem()
        if current_item: self.selected_path = current_item.data(Qt.UserRole)
        super().accept()
    
    def open_new(self):
        self.selected_path = "OPEN_NEW"; super().accept()

class DocumentationViewer(QDialog):
    """A non-modal window to display the project's README.md."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("LLM-Sherpa Documentation")
        self.setGeometry(150, 150, 800, 600)

        layout = QVBoxLayout(self)
        self.text_browser = QTextBrowser()
        self.text_browser.setOpenExternalLinks(True)
        layout.addWidget(self.text_browser)

        self.load_content()

    def load_content(self):
        try:
            # Determine the base path (works for script and frozen exe)
            base_path = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
            # Navigate up one level to the project root from 'sherpa_modules'
            project_root = os.path.dirname(base_path)
            readme_path = os.path.join(project_root, 'README.md')
            
            if os.path.exists(readme_path):
                with open(readme_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.text_browser.setMarkdown(content)
            else:
                self.show_fallback_link()
        except Exception as e:
            self.show_fallback_link(error=str(e))
    
    def show_fallback_link(self, error=None):
        github_url = "https://github.com/VicRejkia/LLM-Sherpa/blob/ui_pyside/README.md"
        error_message = f"<p><b>Error loading local README.md:</b> {error}</p>" if error else ""
        
        fallback_html = f"""
        <html>
            <body>
                <h2>Documentation</h2>
                <p>The local `README.md` file could not be found.</p>
                {error_message}
                <p>You can view the most up-to-date documentation on our GitHub page:</p>
                <p><a href="{github_url}">{github_url}</a></p>
            </body>
        </html>
        """
        self.text_browser.setHtml(fallback_html)