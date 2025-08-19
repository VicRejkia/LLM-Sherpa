import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QTreeView, QLabel, QTextBrowser, QStyle
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QFont
from PySide6.QtCore import Qt, Slot

from sherpa_modules import content_utils

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False


class ProjectView(QWidget):
    """
    Component for the project tree and code preview.
    Manages the display of the file system structure and file content.
    """
    item_check_changed = Slot(QStandardItem)

    def __init__(self, settings_manager, parent=None):
        super().__init__(parent)
        self.settings_manager = settings_manager
        self.pygments_css = ""
        if PYGMENTS_AVAILABLE:
            formatter = HtmlFormatter(style='monokai')
            self.pygments_css = formatter.get_style_defs('.highlight')

        self.init_ui()
        self._connect_signals()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # Tree View Container
        tree_container = QWidget()
        tree_layout = QVBoxLayout(tree_container)
        self.tree_view = QTreeView()
        self.tree_model = QStandardItemModel()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])
        self.tree_view.setModel(self.tree_model)
        tree_layout.addWidget(self.tree_view)
        splitter.addWidget(tree_container)

        # Code Preview Container
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_label_text = "Code Preview ✨" + ("" if PYGMENTS_AVAILABLE else " (Syntax highlighting requires 'pip install Pygments')")
        preview_layout.addWidget(QLabel(preview_label_text))
        self.code_preview = QTextBrowser()
        self.code_preview.setReadOnly(True)
        self.code_preview.setFont(QFont("Courier New", 11))
        preview_layout.addWidget(self.code_preview)
        splitter.addWidget(preview_container)
        splitter.setSizes([500, 600])

    def _connect_signals(self):
        self.tree_view.selectionModel().selectionChanged.connect(self.on_tree_selection_changed)

    def model(self):
        return self.tree_model

    def view(self):
        return self.tree_view

    def clear_tree(self):
        self.tree_model.clear()
        self.tree_model.setHorizontalHeaderLabels(['Name', 'Type', 'Path'])

    def populate_from_data(self, items_data):
        path_to_item_map = {'.': self.tree_model.invisibleRootItem()}
        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)
        py_icon = QIcon.fromTheme("text-x-python", file_icon)
        class_icon = QIcon.fromTheme("x-office-document", file_icon)
        func_icon = QIcon.fromTheme("utilities-terminal", file_icon)

        for item_data in items_data:
            parent_item = path_to_item_map.get(item_data['parent_id'])
            if parent_item is None:
                continue

            name_item = QStandardItem(item_data['name'])
            name_item.setCheckable(True)
            name_item.setEditable(False)
            name_item.setData(item_data, Qt.UserRole)
            
            type_item = QStandardItem(item_data['type'])
            type_item.setEditable(False)
            rel_path_item = QStandardItem(item_data['rel_path'])
            rel_path_item.setEditable(False)

            icon = file_icon
            if item_data['type'] == 'folder': icon = folder_icon
            elif os.path.splitext(item_data['name'])[-1].lower() == '.py': icon = py_icon
            elif item_data['type'] == 'class': icon = class_icon
            elif item_data['type'] == 'function': icon = func_icon
            name_item.setIcon(icon)

            parent_item.appendRow([name_item, type_item, rel_path_item if item_data['type'] != 'function' else QStandardItem("")])
            path_to_item_map[item_data['id']] = name_item
        
        self.tree_view.header().resizeSection(0, 400)


    @Slot()
    def on_tree_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        if not indexes:
            self.code_preview.clear()
            return
        
        item = self.tree_model.itemFromIndex(indexes[0])
        item_data = item.data(Qt.UserRole)
        if not item_data or item_data.get('type') == 'folder':
            self.code_preview.clear()
            return

        code = content_utils.get_code_from_item(item_data)
        if PYGMENTS_AVAILABLE:
            try:
                ext_map = self.settings_manager.get("extension_map", {})
                ext = os.path.splitext(item_data['full_path'])[1].lower()
                lexer = get_lexer_by_name(ext_map.get(ext, 'text'))
            except Exception:
                lexer = guess_lexer(code)
            
            formatter = HtmlFormatter(style='monokai', linenos='table', noclasses=False)
            html_fragment = highlight(code, lexer, formatter)
            full_html = f"<html><head><style>{self.pygments_css} body{{background-color:#272822;color:#f8f8f2;}}</style></head><body>{html_fragment}</body></html>"
            self.code_preview.setHtml(full_html)
        else:
            self.code_preview.setText(code)