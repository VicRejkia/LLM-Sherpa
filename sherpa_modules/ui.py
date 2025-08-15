import os
import json
import ast

from PySide6.QtWidgets import (
    QDialog, QCheckBox, QLabel, QDialogButtonBox, QTextEdit,
    QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem, QMessageBox,
    QTabWidget, QWidget, QWizard, QWizardPage, QSplitter, QApplication
)
from PySide6.QtCore import Qt, QTimer

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

        # LLM & Prompts Tab
        llm_tab = QWidget()
        layout = QVBoxLayout(llm_tab)
        layout.addWidget(QLabel("<b>LLM Token Budgets (JSON format):</b>"))
        self.token_budgets_text = QTextEdit(text=json.dumps(self.settings_manager.get("llm_token_budgets"), indent=4))
        layout.addWidget(self.token_budgets_text)
        layout.addWidget(QLabel("\n<b>Prompt Modules (JSON format for Task Selector):</b>"))
        self.prompt_modules_text = QTextEdit(text=json.dumps(self.settings_manager.get("prompt_modules"), indent=4))
        layout.addWidget(self.prompt_modules_text)
        tabs.addTab(llm_tab, "LLM & Prompts")

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
        
        try:
            self.settings_manager.set("extension_map", json.loads(self.ext_map_text.toPlainText()))
            self.settings_manager.set("llm_token_budgets", json.loads(self.token_budgets_text.toPlainText()))
            self.settings_manager.set("prompt_modules", json.loads(self.prompt_modules_text.toPlainText()))
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

class IterativeRefinementDialog(QDialog):
    """A dialog for the iterative refinement workflow."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Iterative Refinement Workflow")
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        left_widget = QWidget(); left_layout = QVBoxLayout(left_widget)
        left_layout.addWidget(QLabel("<b>1. Paste LLM's initial code generation here:</b>"))
        self.llm_output_text = QTextEdit(); left_layout.addWidget(self.llm_output_text)
        splitter.addWidget(left_widget)
        right_widget = QWidget(); right_layout = QVBoxLayout(right_widget)
        right_layout.addWidget(QLabel("<b>2. Copy this prompt and send it to the LLM:</b>"))
        self.critique_prompt_text = QTextEdit(); self.critique_prompt_text.setReadOnly(True)
        critique_prompt = "Now, review the code you just wrote. Identify potential bugs, edge cases that are not handled, and areas where readability could be improved."
        self.critique_prompt_text.setPlainText(critique_prompt)
        btn_copy = QPushButton("Copy to Clipboard")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(critique_prompt))
        right_layout.addWidget(self.critique_prompt_text); right_layout.addWidget(btn_copy)
        splitter.addWidget(right_widget)
        layout.addWidget(splitter)
        self.button_box = QDialogButtonBox(QDialogButtonBox.Close)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

class TDDWizard(QWizard):
    """A wizard for the Test-Driven Development workflow."""
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.setWindowTitle("TDD Feature Generation")
        self.addPage(self.create_feature_page())
        self.addPage(self.create_implementation_page())

    def create_feature_page(self):
        page = QWizardPage(); page.setTitle("Step 1: Generate Tests")
        page.setSubTitle("Describe the feature you want to build.")
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Feature Description:</b>"))
        self.feature_description = QTextEdit()
        self.feature_description.setPlaceholderText("e.g., 'A function that takes a list of integers and returns the sum of all even numbers.'")
        layout.addWidget(self.feature_description, 1)
        self.test_prompt_preview = QTextEdit(); self.test_prompt_preview.setReadOnly(True)
        layout.addWidget(QLabel("<b>Generated Prompt for Tests:</b>"))
        layout.addWidget(self.test_prompt_preview, 1)
        self.feature_description.textChanged.connect(self.update_test_prompt)
        QTimer.singleShot(0, self.update_test_prompt)
        return page

    def create_implementation_page(self):
        page = QWizardPage(); page.setTitle("Step 2: Implement Code")
        page.setSubTitle("Paste the generated tests from the LLM.")
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("<b>Paste Generated Test Suite Here:</b>"))
        self.test_suite_input = QTextEdit(); layout.addWidget(self.test_suite_input, 1)
        self.code_prompt_preview = QTextEdit(); self.code_prompt_preview.setReadOnly(True)
        layout.addWidget(QLabel("<b>Generated Prompt for Code Implementation:</b>"))
        layout.addWidget(self.code_prompt_preview, 1)
        self.test_suite_input.textChanged.connect(self.update_code_prompt)
        return page

    def update_test_prompt(self):
        template = self.settings_manager.get("tdd_prompts", {}).get("test_generation", "")
        description = self.feature_description.toPlainText()
        self.test_prompt_preview.setPlainText(template.format(feature_description=description))

    def update_code_prompt(self):
        template = self.settings_manager.get("tdd_prompts", {}).get("code_implementation", "")
        test_suite = self.test_suite_input.toPlainText()
        self.code_prompt_preview.setPlainText(template.format(test_suite=test_suite))