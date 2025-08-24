import os
# --- MODIFIED: Add QThread, QObject, and Signal for background processing ---
from PySide6.QtWidgets import QWidget, QVBoxLayout, QSplitter, QTreeView, QLabel, QTextBrowser, QStyle
from PySide6.QtGui import QStandardItemModel, QStandardItem, QIcon, QFont
from PySide6.QtCore import Qt, Slot, QThread, QObject, Signal

from sherpa_modules import content_utils

try:
    from pygments import highlight
    from pygments.lexers import get_lexer_by_name, guess_lexer
    from pygments.formatters import HtmlFormatter
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False

# --- NEW: Worker for asynchronously reading and highlighting files ---
class FileContentWorker(QObject):
    """
    Worker to fetch file content and perform syntax highlighting in a background thread.
    """
    # Emits the final content (HTML or plain text) and a boolean indicating if it's HTML
    result_ready = Signal(str, bool)

    def __init__(self, item_data, settings_manager, pygments_css):
        super().__init__()
        self.item_data = item_data
        self.settings_manager = settings_manager
        self.pygments_css = pygments_css

    @Slot()
    def run(self):
        """
        Fetches the code from the item, highlights it if possible, and emits the result.
        """
        code = content_utils.get_code_from_item(self.item_data)
        
        if not code.strip():
            self.result_ready.emit("<i>(File is empty or contains only whitespace)</i>", True)
            return

        if PYGMENTS_AVAILABLE:
            try:
                ext_map = self.settings_manager.get("extension_map", {})
                ext = os.path.splitext(self.item_data['full_path'])[1].lower()
                lexer = get_lexer_by_name(ext_map.get(ext, 'text'))
            except Exception:
                lexer = guess_lexer(code)
            
            formatter = HtmlFormatter(style='monokai', linenos='table', noclasses=False)
            html_fragment = highlight(code, lexer, formatter)
            full_html = f"<html><head><style>{self.pygments_css} body{{background-color:#272822;color:#f8f8f2;}}</style></head><body>{html_fragment}</body></html>"
            self.result_ready.emit(full_html, True)
        else:
            self.result_ready.emit(code, False)


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

        self.file_reader_thread = None
        self.file_reader_worker = None

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

    @Slot(str, bool)
    def _display_code_content(self, content, is_html):
        """Updates the code preview widget with the fetched content."""
        if is_html:
            self.code_preview.setHtml(content)
        else:
            self.code_preview.setText(content)

    # --- NEW ---
    # This new slot safely clears the reference to the thread after it's finished.
    @Slot()
    def _on_file_reader_finished(self):
        """Slot to nullify thread and worker references after completion."""
        self.file_reader_thread = None
        self.file_reader_worker = None

    @Slot()
    def on_tree_selection_changed(self, selected, deselected):
        """
        Handles selection changes in the tree view by loading file content
        asynchronously in a background thread to keep the UI responsive.
        """
        indexes = selected.indexes()
        if not indexes:
            self.code_preview.clear()
            return
        
        item = self.tree_model.itemFromIndex(indexes[0])
        item_data = item.data(Qt.UserRole)
        
        # Clear preview for folders
        if not item_data or item_data.get('type') == 'folder':
            self.code_preview.clear()
            return

        # --- Asynchronous Loading Logic ---

        # 1. Stop any previous worker that might still be running
        # This check is now safe because the reference is cleared on thread finish.
        if self.file_reader_thread and self.file_reader_thread.isRunning():
            self.file_reader_thread.quit()
            self.file_reader_thread.wait()

        # 2. Display a loading message immediately
        self.code_preview.setText("Loading content...")

        # 3. Set up the new worker and thread
        self.file_reader_thread = QThread()
        self.file_reader_worker = FileContentWorker(
            item_data,
            self.settings_manager,
            self.pygments_css
        )
        self.file_reader_worker.moveToThread(self.file_reader_thread)

        # 4. Connect signals for communication and cleanup
        self.file_reader_thread.started.connect(self.file_reader_worker.run)
        self.file_reader_worker.result_ready.connect(self._display_code_content)
        self.file_reader_worker.result_ready.connect(self.file_reader_thread.quit)
        self.file_reader_worker.result_ready.connect(self.file_reader_worker.deleteLater)
        self.file_reader_thread.finished.connect(self.file_reader_thread.deleteLater)
        # --- NEW ---
        # Connect the finished signal to our new cleanup slot.
        self.file_reader_thread.finished.connect(self._on_file_reader_finished)

        # 5. Start the background thread
        self.file_reader_thread.start()