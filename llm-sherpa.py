import os
import sys
import json
import ast
import re
from datetime import datetime
import ctypes
from ctypes import wintypes
from functools import partial


# --- PySide6 Imports ---
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTreeView, QTextEdit, QFileDialog, QMessageBox,
    QDialog, QCheckBox, QLabel, QDialogButtonBox, QStatusBar,
    QTextBrowser, QToolBar, QStyle, QHeaderView, QSizePolicy, QListWidget,
    QListWidgetItem
)
from PySide6.QtGui import QStandardItemModel, QStandardItem, QAction, QKeySequence
from PySide6.QtCore import Qt, Slot, QStandardPaths, QObject, Signal, QThread, QTimer

# --- Helper Function (Unchanged) ---
def get_long_path_name(short_path):
    if sys.platform != 'win32': return short_path
    try:
        _GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
        _GetLongPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetLongPathNameW.restype = wintypes.DWORD
        buffer_size = _GetLongPathNameW(short_path, None, 0)
        if buffer_size == 0: return short_path
        long_path_buffer = ctypes.create_unicode_buffer(buffer_size)
        result = _GetLongPathNameW(short_path, long_path_buffer, buffer_size)
        if result == 0: return short_path
        return long_path_buffer.value
    except Exception: return short_path

# --- Worker for Background File Scanning (Unchanged) ---
class FileSystemWorker(QObject):
    results_ready = Signal(list); error = Signal(str); finished = Signal()
    def __init__(self, path, settings):
        super().__init__(); self.project_path = path; self.settings = settings; self.is_running = True
    @Slot()
    def run(self):
        try:
            results = []; self._scan_directory(self.project_path, results)
            if self.is_running: self.results_ready.emit(results)
        except Exception as e:
            if self.is_running: self.error.emit(f"An unexpected error occurred: {e}")
        finally: self.finished.emit()
    def _scan_directory(self, current_path, results):
        if not self.is_running: return
        exclude_list = self.settings.get("exclude_list"); exclude_dotfiles = self.settings.get("exclude_dotfiles"); extension_map = self.settings.get("extension_map")
        try: items = sorted(os.listdir(current_path))
        except (PermissionError, FileNotFoundError) as e: print(f"Skipping inaccessible path: {e}"); return
        for name in items:
            if not self.is_running: break
            if name in exclude_list or (exclude_dotfiles and name.startswith('.')): continue
            full_path = os.path.join(current_path, name); rel_path = os.path.relpath(full_path, self.project_path).replace(os.sep, '/')
            item_data = {'name': name, 'full_path': full_path, 'rel_path': rel_path, 'parent_rel_path': os.path.dirname(rel_path) if '/' in rel_path else '.', 'is_dir': os.path.isdir(full_path)}
            if item_data['is_dir']: results.append(item_data); self._scan_directory(full_path, results)
            else:
                _, ext = os.path.splitext(name)
                if ext.lower() in extension_map: results.append(item_data)
    def stop(self): self.is_running = False

# --- Settings and Config Management (Unchanged) ---
class SettingsManager:
    def __init__(self, filename="settings.json"):
        script_dir = os.path.dirname(os.path.abspath(__file__)); self.filename = os.path.join(script_dir, filename); self.settings = {}; self.load_settings()
    def _create_default_settings(self):
        return {"extension_map":{".py":"python",".sql":"sql",".js":"javascript",".html":"html",".css":"css",".json":"json",".md":"markdown",".txt":"text",".yml":"yaml",".yaml":"yaml",".toml":"toml",".ini":"ini",".sh":"bash",".bat":"batch",".dockerfile":"dockerfile"},"exclude_list":["__pycache__",".git",".vscode","node_modules","venv",".env"],"exclude_dotfiles":True,"show_project_structure":True,"remember_project_path":False,"restore_tree_selection":False}
    def load_settings(self):
        try:
            with open(self.filename,'r') as f: loaded_settings=json.load(f);defaults=self._create_default_settings();defaults.update(loaded_settings);self.settings=defaults
        except (FileNotFoundError,json.JSONDecodeError): self.settings=self._create_default_settings();self.save_settings()
    def save_settings(self):
        try:
            with open(self.filename,'w') as f:json.dump(self.settings,f,indent=4)
        except IOError as e:print(f"Settings Error: Could not save settings: {e}")
    def get(self,key):return self.settings.get(key)
    def set(self,key,value):self.settings[key]=value

class ConfigManager:
    def __init__(self, app_name="LLMSherpa"):
        self.config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        if not self.config_dir:
            self.config_dir = os.path.join(os.path.expanduser("~"), f".{app_name.lower()}")
        self.config_path = os.path.join(self.config_dir, "config.json")
        self.config = {}
        os.makedirs(self.config_dir, exist_ok=True)
        self.load_config()

    def load_config(self):
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {"last_project_path": "", "tree_states": {}, "recent_project_paths": []}

    def save_config(self):
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Config Error: Could not save config: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value

    def get_recent_projects(self):
        return self.get("recent_project_paths", [])

    def add_recent_project(self, path):
        recent_paths = self.get_recent_projects()
        if path in recent_paths:
            recent_paths.remove(path)
        recent_paths.insert(0, path)
        self.set("recent_project_paths", recent_paths[:10]) # Keep only the 10 most recent

class SettingsWindow(QDialog):
    def __init__(self, settings_manager, parent=None):
        super().__init__(parent);self.settings_manager=settings_manager;self.setWindowTitle("Settings");self.setMinimumWidth(500);layout=QVBoxLayout(self);layout.addWidget(QLabel("Persistence:"));self.remember_path_chk=QCheckBox("Remember last project path on startup");self.remember_path_chk.setChecked(self.settings_manager.get("remember_project_path"));layout.addWidget(self.remember_path_chk);self.restore_tree_chk=QCheckBox("Restore tree selection for the last project");self.restore_tree_chk.setChecked(self.settings_manager.get("restore_tree_selection"));layout.addWidget(self.restore_tree_chk);layout.addWidget(QLabel("\nGeneral:"));self.exclude_dotfiles_chk=QCheckBox("Exclude all files and folders starting with '.'");self.exclude_dotfiles_chk.setChecked(self.settings_manager.get("exclude_dotfiles"));layout.addWidget(self.exclude_dotfiles_chk);self.show_structure_chk=QCheckBox("Include 'Project Structure' tree in output");self.show_structure_chk.setChecked(self.settings_manager.get("show_project_structure"));layout.addWidget(self.show_structure_chk);layout.addWidget(QLabel("\nExclude files/folders by name (one per line):"));self.exclude_text=QTextEdit();self.exclude_text.setText("\n".join(self.settings_manager.get("exclude_list")));layout.addWidget(self.exclude_text);layout.addWidget(QLabel("\nMap extensions to Markdown language identifiers:"));self.ext_map_text=QTextEdit();self.ext_map_text.setText(json.dumps(self.settings_manager.get("extension_map"),indent=4));layout.addWidget(self.ext_map_text);self.button_box=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);self.button_box.accepted.connect(self.accept);self.button_box.rejected.connect(self.reject);layout.addWidget(self.button_box)
    def accept(self):
        self.settings_manager.set("remember_project_path",self.remember_path_chk.isChecked());self.settings_manager.set("restore_tree_selection",self.restore_tree_chk.isChecked());self.settings_manager.set("exclude_dotfiles",self.exclude_dotfiles_chk.isChecked());self.settings_manager.set("show_project_structure",self.show_structure_chk.isChecked());exclude_list=self.exclude_text.toPlainText().strip().split("\n");self.settings_manager.set("exclude_list",[item.strip() for item in exclude_list if item.strip()])
        try:
            new_ext_map=ast.literal_eval(self.ext_map_text.toPlainText())
            if not isinstance(new_ext_map,dict):raise ValueError("Input is not a dictionary.")
            self.settings_manager.set("extension_map",new_ext_map)
        except (ValueError,SyntaxError) as e:QMessageBox.critical(self,"Invalid Format",f"File type mapping is not a valid Python dictionary.\nError: {e}");return
        self.settings_manager.save_settings();super().accept()

# --- Welcome Dialog (Unchanged) ---
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
        open_button = QPushButton("Open Selected")
        open_button.clicked.connect(self.accept)
        open_new_button = QPushButton("Open Another Project...")
        open_new_button.clicked.connect(self.open_new)
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        button_layout.addWidget(open_new_button)
        button_layout.addStretch()
        button_layout.addWidget(open_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    def accept(self):
        current_item = self.list_widget.currentItem()
        if current_item:
            self.selected_path = current_item.data(Qt.UserRole)
        super().accept()
    
    def open_new(self):
        self.selected_path = "OPEN_NEW"
        super().accept()

class ProjectDocumenter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LLM-Sherpa - Project Documenter v1.2")
        self.setGeometry(100, 100, 900, 800)

        self.settings_manager = SettingsManager()
        self.config_manager = ConfigManager()
        self.project_path = ""
        self._is_updating_checks = False
        
        self.worker = None
        self.worker_thread = None

        self.init_ui()
        QTimer.singleShot(0, self.show_welcome_or_load_project)


    def init_ui(self):
        central_widget = QWidget(); self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.create_actions()
        self.create_menu_bar()
        self.create_tool_bar()

        self.tree_view = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Path', 'Type'])
        self.tree_view.setModel(self.tree_model)

        header = self.tree_view.header()
        header.setStretchLastSection(False)
        self.tree_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.Interactive)

        main_layout.addWidget(self.tree_view, stretch=3)
        main_layout.addWidget(QLabel("🎯 Objective / Prompt (Optional)"))
        self.prompt_text = QTextEdit(); main_layout.addWidget(self.prompt_text, stretch=1)
        self.status_bar = QStatusBar(); self.setStatusBar(self.status_bar)
        self.token_count_label = QLabel("Estimated Size: ~0 tokens")
        self.loading_status_label = QLabel("")
        self.status_bar.addPermanentWidget(self.loading_status_label)
        self.status_bar.addPermanentWidget(self.token_count_label)
        self.tree_model.itemChanged.connect(self.on_item_changed)
        self.prompt_text.textChanged.connect(self.update_token_count)

    def _apply_tree_column_widths(self):
        header = self.tree_view.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)
        header.resizeSection(0, 400)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.resizeSection(1, 200)
        header.setSectionResizeMode(2, QHeaderView.Interactive)
        header.resizeSection(2, 100)
        self.tree_view.updateGeometry()
        self.tree_view.viewport().update()
    
    def _set_children_check_state(self, item, state):
        item.setCheckState(state)
        if item.hasChildren():
            for i in range(item.rowCount()):
                child = item.child(i, 0)
                if child: self._set_children_check_state(child, state)

    def _update_ancestor_check_state(self, item):
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

    @Slot(QStandardItem)
    def on_item_changed(self, item):
        if self._is_updating_checks: return
        self._is_updating_checks = True
        if item.hasChildren(): self._set_children_check_state(item, item.checkState())
        self._update_ancestor_check_state(item)
        self._is_updating_checks = False
        self.update_token_count()

    # --- Corrected Startup Logic ---
    @Slot()
    def show_welcome_or_load_project(self):
        # First, check if a path was given as a command-line argument.
        path_to_load = None
        if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
            path_to_load = sys.argv[1]

        # If a path was given, load it directly and skip the welcome screen.
        if path_to_load:
            self.load_project(path_to_load, is_initial_load=True)
        # Otherwise, always show the welcome screen.
        else:
            recent_paths = self.config_manager.get_recent_projects()
            dialog = WelcomeDialog(recent_paths, self)
            if dialog.exec():
                if dialog.selected_path == "OPEN_NEW":
                    # User clicked "Open Another Project..."
                    self.select_folder_dialog()
                elif dialog.selected_path:
                    # User selected a project from the list and clicked "Open"
                    self.load_project(dialog.selected_path)
    
    @Slot()
    def refresh_project(self):
        if self.project_path:
            self.load_project(self.project_path, is_initial_load=False)

    @Slot()
    def select_folder_dialog(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Root Folder")
        if folder:
            self.load_project(folder, is_initial_load=False)

    def load_project(self, path, is_initial_load=False):
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker:
                self.worker.stop()
            self.worker_thread.quit()
            if not self.worker_thread.wait(5000):
                print("Warning: Worker thread did not terminate gracefully.")

        self.project_path = get_long_path_name(path)
        self.setWindowTitle(f"LLM-Sherpa - {os.path.basename(self.project_path)}")
        self.tree_model.clear()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Path', 'Type'])
        
        self.config_manager.add_recent_project(self.project_path)
        self.config_manager.save_config()
        self.update_recent_projects_menu()

        if not is_initial_load:
            self.set_ui_enabled(False)
            self.loading_status_label.setText("Scanning project files...")

        self.worker_thread = QThread(self)
        self.worker = FileSystemWorker(self.project_path, self.settings_manager.settings)
        self.worker.moveToThread(self.worker_thread)

        self.worker_thread.started.connect(self.worker.run)
        self.worker.results_ready.connect(self.populate_tree_from_data)
        self.worker.error.connect(self.on_loading_error)
        
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.finished.connect(self._clear_worker_refs)
        
        self.worker_thread.start()

    @Slot()
    def _clear_worker_refs(self):
        self.worker = None
        self.worker_thread = None

    @Slot(list)
    def populate_tree_from_data(self, items_data):
        if not self.loading_status_label.text():
            self.loading_status_label.setText("Building tree view...")
        path_to_item_map = {'.': self.tree_model.invisibleRootItem()}
        for item_data in items_data:
            parent_item = path_to_item_map.get(item_data['parent_rel_path'])
            if parent_item is None: continue
            name_item = QStandardItem(item_data['name']); name_item.setCheckable(True); name_item.setEditable(False)
            name_item.setData(item_data['full_path'], Qt.UserRole); name_item.setData(item_data['rel_path'], Qt.UserRole + 1)
            path_item = QStandardItem(item_data['rel_path']); path_item.setEditable(False)
            if item_data['is_dir']:
                type_item = QStandardItem("Folder"); type_item.setEditable(False)
                parent_item.appendRow([name_item, path_item, type_item])
                path_to_item_map[item_data['rel_path']] = name_item
            else:
                _, ext = os.path.splitext(item_data['name']); type_item = QStandardItem(ext[1:].upper() if ext else "FILE"); type_item.setEditable(False)
                parent_item.appendRow([name_item, path_item, type_item])
        self.on_loading_finished()
        QTimer.singleShot(0, self._apply_tree_column_widths)
        
    @Slot(str)
    def on_loading_error(self, error_message):
        QMessageBox.critical(self, "Loading Error", f"Failed to load project structure:\n{error_message}")
        self.on_loading_finished()

    def on_loading_finished(self):
        self.loading_status_label.setText("")
        self.set_ui_enabled(True)
        if self.project_path and self.settings_manager.get("restore_tree_selection"):
            self.restore_tree_state()
        self.update_token_count()

    def set_ui_enabled(self, enabled):
        self.generate_action.setEnabled(enabled and bool(self.project_path))
        self.open_action.setEnabled(enabled)
        self.refresh_action.setEnabled(enabled and bool(self.project_path))
        self.toggle_all_action.setEnabled(enabled)
        self.tree_view.setEnabled(enabled)
        
    def create_actions(self):
        self.open_action = QAction(self.style().standardIcon(QStyle.SP_DirOpenIcon), "&Open Project Folder...", self);self.open_action.setShortcut(QKeySequence.Open);self.open_action.triggered.connect(self.select_folder_dialog)
        self.refresh_action = QAction(self.style().standardIcon(QStyle.SP_BrowserReload), "&Refresh", self); self.refresh_action.setShortcut(QKeySequence.Refresh); self.refresh_action.triggered.connect(self.refresh_project); self.refresh_action.setEnabled(False)
        self.generate_action = QAction(self.style().standardIcon(QStyle.SP_DialogSaveButton), "&Generate Documentation", self);self.generate_action.setShortcut(QKeySequence.Save);self.generate_action.triggered.connect(self.generate_markdown);self.generate_action.setEnabled(False)
        self.exit_action = QAction("E&xit", self);self.exit_action.setShortcut(QKeySequence.Quit);self.exit_action.triggered.connect(self.close)
        self.toggle_all_action = QAction(self.style().standardIcon(QStyle.SP_FileDialogDetailedView), "&Toggle All Selections", self);self.toggle_all_action.setShortcut(QKeySequence("Ctrl+A"));self.toggle_all_action.triggered.connect(self.toggle_all_selections)
        self.settings_action = QAction(self.style().standardIcon(QStyle.SP_ToolBarHorizontalExtensionButton), "Settings...", self);self.settings_action.triggered.connect(self.open_settings)
        self.docs_action = QAction("&Documentation", self);self.docs_action.triggered.connect(self.show_docs_dialog)
        self.about_action = QAction("&About", self);self.about_action.triggered.connect(self.show_about_dialog)

    def create_menu_bar(self):
        menu_bar = self.menuBar()
        self.file_menu = menu_bar.addMenu("&File")
        self.file_menu.addAction(self.open_action)
        
        self.recent_projects_menu = self.file_menu.addMenu("Recent Projects")
        self.update_recent_projects_menu()
        
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.generate_action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.exit_action)
        
        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.addAction(self.refresh_action)
        edit_menu.addAction(self.toggle_all_action)
        
        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction(self.settings_action)
        
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self.docs_action)
        help_menu.addAction(self.about_action)

    def update_recent_projects_menu(self):
        self.recent_projects_menu.clear()
        recent_paths = self.config_manager.get_recent_projects()
        for path in recent_paths:
            if os.path.isdir(path):
                action = QAction(path, self)
                action.triggered.connect(partial(self.load_project, path))
                self.recent_projects_menu.addAction(action)
        self.recent_projects_menu.setEnabled(len(recent_paths) > 0)

    def create_tool_bar(self):
        tool_bar = self.addToolBar("Main Toolbar");tool_bar.setMovable(False)
        tool_bar.addAction(self.open_action)
        tool_bar.addAction(self.refresh_action)
        tool_bar.addAction(self.generate_action)
        tool_bar.addSeparator()
        tool_bar.addAction(self.toggle_all_action)
        tool_bar.addAction(self.settings_action)

    @Slot()
    def toggle_all_selections(self):
        root = self.tree_model.invisibleRootItem()
        if root.rowCount() == 0: return
        all_checked = all(root.child(row, 0).checkState() == Qt.CheckState.Checked for row in range(root.rowCount()))
        new_state = Qt.CheckState.Unchecked if all_checked else Qt.CheckState.Checked
        self._is_updating_checks = True
        for row in range(root.rowCount()):
            item = root.child(row, 0)
            if item:
                self._set_children_check_state(item, new_state)
        self._is_updating_checks = False
        self.update_token_count()

    def set_all_checks(self, state):
        self._is_updating_checks = True; root = self.tree_model.invisibleRootItem()
        for row in range(root.rowCount()):
            item = root.child(row, 0)
            if item: item.setCheckState(state)
        self._is_updating_checks = False
        if root.rowCount() > 0: self.on_item_changed(root.child(0,0))

    def get_tree_state(self):
        checked_paths, expanded_paths = [], []; root = self.tree_model.invisibleRootItem()
        def recurse(parent_item):
            for row in range(parent_item.rowCount()):
                item = parent_item.child(row, 0)
                if not item: continue
                rel_path = item.data(Qt.UserRole + 1)
                if item.checkState() in (Qt.CheckState.Checked, Qt.CheckState.PartiallyChecked): checked_paths.append(rel_path)
                if item.hasChildren() and self.tree_view.isExpanded(item.index()): expanded_paths.append(rel_path); recurse(item)
        recurse(root); return {"checked": checked_paths, "expanded": expanded_paths}

    def restore_tree_state(self):
        tree_states = self.config_manager.get("tree_states", {})
        state = tree_states.get(self.project_path)
        if not state:
            return
        self._is_updating_checks = True
        checked_set = set(state.get("checked", []))
        expanded_set = set(state.get("expanded", []))
        leaf_items = []
        def recurse_set_state(parent_item):
            for row in range(parent_item.rowCount()):
                item = parent_item.child(row, 0)
                if not item: continue
                rel_path = item.data(Qt.UserRole + 1)
                if rel_path in checked_set:
                    item.setCheckState(Qt.CheckState.Checked)
                if rel_path in expanded_set:
                    self.tree_view.expand(item.index())
                if item.hasChildren():
                    recurse_set_state(item)
                else:
                    leaf_items.append(item)
        recurse_set_state(self.tree_model.invisibleRootItem())
        self._is_updating_checks = False
        for item in leaf_items:
            self._update_ancestor_check_state(item)

    def _get_checked_file_paths(self, parent_item):
        paths = [];
        for row in range(parent_item.rowCount()):
            child_item = parent_item.child(row, 0)
            if not child_item: continue
            if child_item.hasChildren(): paths.extend(self._get_checked_file_paths(child_item))
            elif child_item.checkState() == Qt.CheckState.Checked:
                file_path = child_item.data(Qt.UserRole)
                if file_path: paths.append(file_path)
        return paths

    def update_token_count(self):
        total_chars = len(self.prompt_text.toPlainText()); checked_files = self._get_checked_file_paths(self.tree_model.invisibleRootItem())
        for file_path in checked_files:
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f: total_chars += len(f.read())
            except (IOError, OSError): continue
        estimated_tokens = int(total_chars / 4); self.token_count_label.setText(f"Estimated Size: ~{estimated_tokens:,} tokens")

    @Slot()
    def open_settings(self):
        dialog = SettingsWindow(self.settings_manager, self)
        if dialog.exec() and self.project_path: self.load_project(self.project_path)

    def _generate_tree_structure(self, file_paths):
        tree = {}; lines = ["."]; P_C, P_S = "├── ", "│   "; E_C, E_S = "└── ", "    "
        for path in file_paths:
            parts = path.replace(os.sep, '/').split('/')
            current_level = tree
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
        prompt_text = self.prompt_text.toPlainText().strip(); selected_files = sorted(self._get_checked_file_paths(self.tree_model.invisibleRootItem()))
        if not selected_files and not prompt_text: QMessageBox.information(self, "Info", "No files selected and no prompt provided."); return
        output_file, _ = QFileDialog.getSaveFileName(self, "Save Documentation", f"{os.path.basename(self.project_path)}_context.md", "Markdown Files (*.md);;All Files (*)")
        if not output_file: return
        has_objective=bool(prompt_text);show_structure_setting=self.settings_manager.get("show_project_structure");has_structure=show_structure_setting and selected_files;known_deps=['requirements.txt','package.json','Pipfile','pyproject.toml','pom.xml','build.gradle'];dependency_files=[p for p in selected_files if os.path.basename(p) in known_deps];has_dependencies=bool(dependency_files);main_code_files=[p for p in selected_files if p not in dependency_files];has_main_files=bool(main_code_files)
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                if has_objective:f.write("# 🎯 Objective\n\n");f.write(prompt_text);f.write("\n\n---\n\n")
                if has_structure or has_dependencies or has_main_files:
                    project_name=os.path.basename(os.path.normpath(self.project_path));f.write(f"## 📚 Project Context: `{project_name}`\n\n");f.write("This document provides the necessary files and structure for the task.\n\n");section_counter=1
                    if has_structure:f.write(f"### {section_counter}. Project Structure\n\n");relative_paths=[os.path.relpath(p, self.project_path) for p in selected_files];f.write(f"```\n{self._generate_tree_structure(relative_paths)}\n```\n\n");section_counter+=1
                    if has_dependencies:
                        f.write(f"### {section_counter}. Dependencies\n\n")
                        for dep_path in dependency_files:
                            filename,rel_path=os.path.basename(dep_path),os.path.relpath(dep_path,self.project_path).replace(os.sep,'/');f.write(f"#### `{filename}`\n*path: `{rel_path}`*\n\n```\n")
                            try:
                                with open(dep_path,"r",encoding="utf-8",errors='replace') as src:f.write(src.read())
                            except Exception as e:f.write(f"Error reading file: {e}")
                            f.write("\n```\n\n");section_counter+=1
                    if has_main_files:
                        f.write(f"### {section_counter}. File Contents\n\n");ext_map=self.settings_manager.get("extension_map")
                        for file_path in main_code_files:
                            filename,rel_path=os.path.basename(file_path),os.path.relpath(file_path,self.project_path).replace(os.sep,'/');ext=os.path.splitext(filename)[1].lower();lang=ext_map.get(ext,"");f.write(f"#### 📄 `{filename}`\n\n*path: `{rel_path}`*\n\n```{lang}\n")
                            try:
                                with open(file_path,"r",encoding="utf-8",errors='replace') as src:f.write(src.read())
                            except Exception as e:f.write(f"Error reading file: {e}")
                            f.write("\n```\n\n")
            QMessageBox.information(self,"Success",f"Documentation generated at:\n{output_file}")
        except Exception as e:QMessageBox.critical(self,"Error",f"Failed to generate documentation:\n{e}")

    @Slot()
    def show_about_dialog(self):
        about_text = """<h2>LLM-Sherpa</h2><p>Version 1.5</p><p>A tool to package source code into a single, context-rich Markdown file for Large Language Models.</p><p><b>Developer:</b> VicRejkia</p><p><b>GitHub:</b> <a href='https://github.com/VicRejkia/LLM-Sherpa'>https://github.com/VicRejkia/LLM-Sherpa</a></p>"""
        QMessageBox.about(self, "About LLM-Sherpa", about_text)


    @Slot()
    def show_docs_dialog(self):
        readme_path=os.path.join(os.path.dirname(os.path.abspath(__file__)),"README.md")
        try:
            with open(readme_path,'r',encoding='utf-8') as f:readme_content=f.read()
        except FileNotFoundError:readme_content="<h2>Documentation Not Found</h2><p>Could not find README.md in the application directory.</p>"
        dialog=QDialog(self);dialog.setWindowTitle("Documentation");dialog.setGeometry(150,150,700,500);layout=QVBoxLayout(dialog);text_browser=QTextBrowser();text_browser.setOpenExternalLinks(True);text_browser.setMarkdown(readme_content);layout.addWidget(text_browser);dialog.exec()

    def closeEvent(self, event):
        if self.worker_thread and self.worker_thread.isRunning():
            if self.worker:
                self.worker.stop()
            self.worker_thread.quit()
            self.worker_thread.wait()
            
        if self.project_path:
            if self.settings_manager.get("remember_project_path"):self.config_manager.set("last_project_path",self.project_path)
            if self.settings_manager.get("restore_tree_selection"): current_tree_state=self.get_tree_state();all_tree_states=self.config_manager.get("tree_states",{});all_tree_states[self.project_path]=current_tree_state;self.config_manager.set("tree_states",all_tree_states)
        self.config_manager.save_config();event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName("LLMSherpaOrg"); app.setApplicationName("LLMSherpa")
    main_window = ProjectDocumenter()
    main_window.show()
    sys.exit(app.exec())