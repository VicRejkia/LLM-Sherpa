import os
import json
import ast

from PySide6.QtWidgets import (
    QDialog, QCheckBox, QLabel, QDialogButtonBox, QTextEdit,
    QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QMessageBox,
    QTabWidget, QWidget
)
from PySide6.QtCore import Qt

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

        # --- Tab 1: General Settings ---
        general_tab = QWidget()
        layout = QVBoxLayout(general_tab)
        tabs.addTab(general_tab, "General")
        
        layout.addWidget(QLabel("<b>Persistence:</b>"))
        self.remember_path_chk = QCheckBox("Remember last project path on startup")
        self.remember_path_chk.setChecked(self.settings_manager.get("remember_project_path"))
        layout.addWidget(self.remember_path_chk)
        
        self.restore_tree_chk = QCheckBox("Restore tree selection for projects")
        self.restore_tree_chk.setChecked(self.settings_manager.get("restore_tree_selection"))
        layout.addWidget(self.restore_tree_chk)

        layout.addWidget(QLabel("\n<b>Output Formatting:</b>"))
        self.show_structure_chk = QCheckBox("Include 'Project Structure' tree in output")
        self.show_structure_chk.setChecked(self.settings_manager.get("show_project_structure"))
        layout.addWidget(self.show_structure_chk)

        layout.addWidget(QLabel("\n<b>File Scanning:</b>"))
        self.exclude_dotfiles_chk = QCheckBox("Exclude all files and folders starting with '.'")
        self.exclude_dotfiles_chk.setChecked(self.settings_manager.get("exclude_dotfiles"))
        layout.addWidget(self.exclude_dotfiles_chk)
        layout.addStretch()

        # --- Tab 2: Exclusions & Mappings ---
        exclusions_tab = QWidget()
        layout = QVBoxLayout(exclusions_tab)
        tabs.addTab(exclusions_tab, "Exclusions & Mappings")

        layout.addWidget(QLabel("<b>Exclude files/folders by name (one per line):</b>"))
        self.exclude_text = QTextEdit()
        self.exclude_text.setText("\n".join(self.settings_manager.get("exclude_list")))
        layout.addWidget(self.exclude_text)
        
        layout.addWidget(QLabel("\n<b>Dependency filenames (one per line):</b>"))
        self.deps_text = QTextEdit()
        self.deps_text.setText("\n".join(self.settings_manager.get("known_dependency_files")))
        layout.addWidget(self.deps_text, stretch=1)

        layout.addWidget(QLabel("\n<b>Map extensions to Markdown language identifiers:</b>"))
        self.ext_map_text = QTextEdit()
        self.ext_map_text.setText(json.dumps(self.settings_manager.get("extension_map"), indent=4))
        layout.addWidget(self.ext_map_text, stretch=2)

        # --- Tab 3: New Features ---
        # --- NEW FEATURE: UI for Token Management & Prompt Templates ---
        llm_tab = QWidget()
        layout = QVBoxLayout(llm_tab)
        tabs.addTab(llm_tab, "LLM & Prompts")

        layout.addWidget(QLabel("<b>LLM Token Budgets (JSON format):</b>"))
        self.token_budgets_text = QTextEdit()
        self.token_budgets_text.setText(json.dumps(self.settings_manager.get("llm_token_budgets"), indent=4))
        layout.addWidget(self.token_budgets_text)

        layout.addWidget(QLabel("\n<b>Prompt Templates (JSON format):</b>"))
        self.prompt_templates_text = QTextEdit()
        self.prompt_templates_text.setText(json.dumps(self.settings_manager.get("prompt_templates"), indent=4))
        layout.addWidget(self.prompt_templates_text)

        # --- Dialog Buttons ---
        self.button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def accept(self):
        # --- Save General Settings ---
        self.settings_manager.set("remember_project_path", self.remember_path_chk.isChecked())
        self.settings_manager.set("restore_tree_selection", self.restore_tree_chk.isChecked())
        self.settings_manager.set("exclude_dotfiles", self.exclude_dotfiles_chk.isChecked())
        self.settings_manager.set("show_project_structure", self.show_structure_chk.isChecked())
        self.settings_manager.set("exclude_list", [item.strip() for item in self.exclude_text.toPlainText().strip().split("\n") if item.strip()])
        self.settings_manager.set("known_dependency_files", [item.strip() for item in self.deps_text.toPlainText().strip().split("\n") if item.strip()])

        # --- Save JSON-based settings with validation ---
        try:
            self.settings_manager.set("extension_map", json.loads(self.ext_map_text.toPlainText()))
            self.settings_manager.set("llm_token_budgets", json.loads(self.token_budgets_text.toPlainText()))
            self.settings_manager.set("prompt_templates", json.loads(self.prompt_templates_text.toPlainText()))
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "Invalid JSON", f"One of the text fields contains invalid JSON.\nPlease correct it before saving.\n\nError: {e}")
            return

        self.settings_manager.save_settings()
        super().accept()

class WelcomeDialog(QDialog):
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
                item = QListWidgetItem(f"{os.path.basename(path)}\n{path}")
                item.setData(Qt.UserRole, path)
                self.list_widget.addItem(item)
        self.list_widget.itemDoubleClicked.connect(self.accept)
        layout.addWidget(self.list_widget)

        button_layout = QHBoxLayout()
        open_button = QPushButton("Open Selected"); open_button.clicked.connect(self.accept)
        open_new_button = QPushButton("Open Another Project..."); open_new_button.clicked.connect(self.open_new)
        cancel_button = QPushButton("Cancel"); cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(open_new_button); button_layout.addStretch()
        button_layout.addWidget(open_button); button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def accept(self):
        current_item = self.list_widget.currentItem()
        if current_item: self.selected_path = current_item.data(Qt.UserRole)
        super().accept()
    
    def open_new(self):
        self.selected_path = "OPEN_NEW"; super().accept()