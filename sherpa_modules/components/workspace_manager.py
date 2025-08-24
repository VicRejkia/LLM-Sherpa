from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTabWidget, QLabel, QTextEdit, QTableWidget,
    QTableWidgetItem, QCheckBox, QHBoxLayout, QPushButton, QComboBox,
    QScrollArea, QFormLayout, QListWidget, QInputDialog, QMessageBox, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal, Slot

class WorkspaceManager(QWidget):
    """
    Manages the bottom workspace area including Prompt Studio, Components,
    and Selection Templates. Encapsulates all related state and UI logic.
    """
    content_changed = Signal()
    template_selected = Signal(str)

    def __init__(self, prompt_templates, parent=None):
        super().__init__(parent)
        self.prompt_templates = prompt_templates
        self.prompt_module_widgets = {}
        
        self.active_template_name = "Default"
        self.templates = {}
        self._is_switching_templates = False

        self.init_ui()
        self._connect_signals()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self._create_prompt_studio_tab()
        self._create_components_tab()
        self._create_templates_tab()
        
    def _create_prompt_studio_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        selector_layout = QHBoxLayout()
        selector_layout.addWidget(QLabel("<b>Select a Prompt Template:</b>"))
        self.template_selector_combo = QComboBox()
        if self.prompt_templates:
            self.template_selector_combo.addItems([""] + list(self.prompt_templates.keys()))
        selector_layout.addWidget(self.template_selector_combo, 1)
        layout.addLayout(selector_layout)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.prompt_module_container = QWidget()
        self.prompt_module_layout = QFormLayout(self.prompt_module_container)
        self.prompt_module_layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self.scroll_area.setWidget(self.prompt_module_container)
        layout.addWidget(self.scroll_area, 1)

        self.tabs.addTab(container, "🚀 Prompt Studio")

    def _create_components_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        
        layout.addWidget(QLabel("<b>📝 Project Description:</b>"))
        description_hint = QLabel("Use the `Codebase Analysis and Documentation` prompt-template, copy the Prompt to your LLM chatbox and upload the markdown file.")
        description_hint.setWordWrap(True)
        description_hint.setStyleSheet("padding: 5px; border: 1px solid #444; border-radius: 4px; background-color: #333;")
        layout.addWidget(description_hint)
        self.project_description_text_edit = QTextEdit()
        self.project_description_text_edit.setAcceptRichText(False)
        self.project_description_text_edit.setPlaceholderText("Paste the markdown-formatted project description here...")
        layout.addWidget(self.project_description_text_edit, 1)
        
        layout.addSpacing(15)
        self.preamble_checkbox = QCheckBox("Generate 'Table of Contents' Preamble")
        self.preamble_checkbox.setChecked(True)
        layout.addWidget(self.preamble_checkbox)
        
        layout.addWidget(QLabel("<b>Key Files & Roles (for Project Context):</b>"))
        self.key_files_table = QTableWidget(0, 2)
        self.key_files_table.setHorizontalHeaderLabels(["File", "Role/Description"])
        self.key_files_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.key_files_table, 1)

        button_layout = QHBoxLayout()
        self.btn_add_files_to_table = QPushButton("Add Selected Files from Tree")
        self.btn_remove_files_from_table = QPushButton("Remove Selected File(s)")
        button_layout.addWidget(self.btn_add_files_to_table)
        button_layout.addWidget(self.btn_remove_files_from_table)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        self.tabs.addTab(container, "🧩 Components")

    def _create_templates_tab(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(QLabel("<b>Manage and load session configurations.</b>"))
        self.template_list_widget = QListWidget()
        self.template_list_widget.setToolTip("Click a template to load it. Your current selections will be saved to the active template first.")
        layout.addWidget(self.template_list_widget)
        
        btn_layout = QHBoxLayout()
        self.btn_save_template = QPushButton("Save Current as New Template...")
        self.btn_delete_template = QPushButton("Delete Selected Template")
        btn_layout.addWidget(self.btn_save_template)
        btn_layout.addWidget(self.btn_delete_template)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.tabs.addTab(container, "💾 Selection Templates")
        
    def _connect_signals(self):
        # Internal content change signals
        self.project_description_text_edit.textChanged.connect(self.content_changed)
        self.key_files_table.itemChanged.connect(self.content_changed)
        self.preamble_checkbox.stateChanged.connect(self.content_changed)
        self.template_selector_combo.currentTextChanged.connect(self.on_template_selected)
        # Template management buttons
        self.btn_save_template.clicked.connect(self.prompt_and_save_new_template)
        self.btn_delete_template.clicked.connect(self.delete_selected_template)
        self.template_list_widget.currentItemChanged.connect(self.handle_template_selection_change)
        # External connections for key files are handled in the main window
        
    @Slot(str)
    def on_template_selected(self, template_name):
        while self.prompt_module_layout.count():
            item = self.prompt_module_layout.takeAt(0)
            widget = item.widget()
            if widget: widget.deleteLater()
        self.prompt_module_widgets.clear()

        if not template_name or template_name not in self.prompt_templates:
            self.content_changed.emit()
            return

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
            widget.textChanged.connect(self.content_changed)
            self.prompt_module_layout.addRow(label, widget)
            self.prompt_module_widgets[name] = widget
        
        self.content_changed.emit()

    def get_component_roles(self):
        roles = {}
        for row in range(self.key_files_table.rowCount()):
            file_item = self.key_files_table.item(row, 0)
            role_item = self.key_files_table.item(row, 1)
            if file_item and role_item and file_item.text():
                roles[file_item.text().strip()] = role_item.text().strip()
        return roles

    def get_full_ui_state(self):
        prompt_studio_state = {
            "selected_template": self.template_selector_combo.currentText(),
            "module_values": {name: widget.toPlainText() for name, widget in self.prompt_module_widgets.items()}
        }
        return {
            "component_roles": self.get_component_roles(),
            "project_description": self.project_description_text_edit.toPlainText(),
            "logs": "", # Logs are managed by a different component
            "prompt_studio": prompt_studio_state
        }

    def load_state(self, state_data, template_name):
        self._is_switching_templates = True
        
        self.project_description_text_edit.setPlainText(state_data.get("project_description", ""))
        roles = state_data.get("component_roles", {})
        self.key_files_table.setRowCount(0)
        for file_path, role in roles.items():
            row_count = self.key_files_table.rowCount()
            self.key_files_table.insertRow(row_count)
            self.key_files_table.setItem(row_count, 0, QTableWidgetItem(file_path))
            self.key_files_table.setItem(row_count, 1, QTableWidgetItem(role))
        self.key_files_table.resizeColumnsToContents()
            
        prompt_state = state_data.get("prompt_studio", {})
        self.template_selector_combo.setCurrentText(prompt_state.get("selected_template", ""))
        
        # Manually trigger update of prompt widgets
        self.on_template_selected(self.template_selector_combo.currentText())

        for name, value in prompt_state.get("module_values", {}).items():
            if name in self.prompt_module_widgets:
                self.prompt_module_widgets[name].setPlainText(value)
        
        self.active_template_name = template_name
        
        for i in range(self.template_list_widget.count()):
            item = self.template_list_widget.item(i)
            if item.text() == template_name:
                self.template_list_widget.setCurrentItem(item)
                break
                
        self._is_switching_templates = False
        self.content_changed.emit()

    def restore_project_templates(self, project_data):
        if "checked" in project_data or "expanded" in project_data:
            self.templates = {"Default": project_data}
            last_active = "Default"
        else:
            self.templates = project_data.get("templates", {"Default": {}})
            last_active = project_data.get("last_active_template", "Default")

        self.template_list_widget.clear()
        self.template_list_widget.addItems(sorted(self.templates.keys()))
        
        self.active_template_name = last_active
        if self.active_template_name in self.templates:
            state_to_load = self.templates[self.active_template_name]
        else:
            self.active_template_name = "Default"
            state_to_load = self.templates.get("Default", {})
        
        return state_to_load, self.active_template_name

    @Slot(QListWidgetItem, QListWidgetItem)
    def handle_template_selection_change(self, current, previous):
        """
        Emits a dedicated signal when the user selects a new template from the list.
        The main window will coordinate saving the old state and loading the new one.
        """
        if self._is_switching_templates or not current:
            return

        # Do nothing if the user clicks the same item again
        if previous and current.text() == previous.text():
            return
        
        # Emit the new signal with the name of the template to load
        self.template_selected.emit(current.text())

    @Slot()
    def prompt_and_save_new_template(self):
        template_name, ok = QInputDialog.getText(self, "Save Template", "Enter a name for this template:")
        if ok and template_name:
            if template_name in self.templates:
                QMessageBox.warning(self, "Name Exists", "A template with this name already exists.")
                return
            
            # The main window will fetch the state and save it
            self.templates[template_name] = {} # Placeholder
            self.active_template_name = template_name
            
            self.template_list_widget.addItem(template_name)
            self.template_list_widget.setCurrentRow(self.template_list_widget.count() - 1)
            
            self.content_changed.emit() # Triggers a save in main window

    @Slot()
    def delete_selected_template(self):
        current_item = self.template_list_widget.currentItem()
        if not current_item:
            QMessageBox.information(self, "Info", "Select a template to delete.")
            return

        template_name = current_item.text()
        if template_name == "Default":
            QMessageBox.warning(self, "Cannot Delete", "The 'Default' template cannot be deleted.")
            return

        reply = QMessageBox.question(self, "Confirm Delete", f"Are you sure you want to delete the template '{template_name}'?")
        if reply == QMessageBox.Yes:
            if template_name in self.templates:
                del self.templates[template_name]
            
            row = self.template_list_widget.row(current_item)
            self.template_list_widget.takeItem(row)
            
            if self.active_template_name == template_name:
                self.active_template_name = "Default" # Fallback
            
            self.content_changed.emit()