from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
from sherpa_modules import actions

class LogView(QWidget):
    """
    A component widget for displaying and managing logs.
    Encapsulates the log text area and related cleanup actions.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Paste logs or console output here."))
        toolbar.addStretch()
        
        btn_clean_timestamps = QPushButton("Rm Timestamps")
        btn_clean_timestamps.clicked.connect(self.clean_logs_timestamps)
        toolbar.addWidget(btn_clean_timestamps)
        
        btn_clean_ansi = QPushButton("Strip ANSI")
        btn_clean_ansi.clicked.connect(self.clean_logs_ansi)
        toolbar.addWidget(btn_clean_ansi)
        
        btn_collapse_dups = QPushButton("Collapse Duplicates")
        btn_collapse_dups.clicked.connect(self.collapse_duplicates)
        toolbar.addWidget(btn_collapse_dups)
        
        btn_clear_logs = QPushButton("❌ Clear")
        btn_clear_logs.clicked.connect(self.clear)
        toolbar.addWidget(btn_clear_logs)
        
        layout.addLayout(toolbar)
        
        self.log_text_edit = QTextEdit()
        layout.addWidget(self.log_text_edit)

    def toPlainText(self):
        """Provides access to the text content."""
        return self.log_text_edit.toPlainText()

    def setPlainText(self, text):
        """Allows setting the text content from outside."""
        self.log_text_edit.setPlainText(text)

    def clear(self):
        """Clears the content of the log text edit."""
        self.log_text_edit.clear()

    def clean_logs_timestamps(self):
        actions.clean_logs_timestamps_action(self.log_text_edit)

    def clean_logs_ansi(self):
        actions.clean_logs_ansi_action(self.log_text_edit)

    def collapse_duplicates(self):
        actions.collapse_duplicates_action(self.log_text_edit)