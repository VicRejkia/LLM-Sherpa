import os
import sys
import ast
from PySide6.QtCore import QObject, Signal

# --- Long Path Handling Utility ---
def get_long_path_name(path):
    """Converts a path to its long path representation if on Windows."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            _GetLongPathNameW = ctypes.windll.kernel32.GetLongPathNameW
            _GetLongPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
            _GetLongPathNameW.restype = wintypes.DWORD
            buffer_size = _GetLongPathNameW(path, None, 0)
            if buffer_size == 0: return path
            buffer = ctypes.create_unicode_buffer(buffer_size)
            if _GetLongPathNameW(path, buffer, buffer_size) == 0: return path
            return buffer.value
        except (ImportError, AttributeError):
            return path
    return path

# --- FileSystem Worker Class ---

class FileSystemWorker(QObject):
    """
    A worker that scans a project directory, parses Python files for structure (classes/functions),
    and builds a list of all items for the tree view.
    """
    results_ready = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, project_path, settings):
        super().__init__()
        self.project_path = project_path
        self.settings = settings
        self._is_running = True

    def stop(self):
        """Stops the worker gracefully."""
        self._is_running = False

    def run(self):
        """
        High-level method to start the scan and emit signals.
        """
        try:
            items_data = list(self._scan_directory(self.project_path))
            if self._is_running:
                self.results_ready.emit(items_data)
        except Exception as e:
            self.error.emit(f"An error occurred during the scan: {str(e)}")
        finally:
            self.finished.emit()

    def _parse_python_file(self, file_full_path, file_rel_path):
        """
        Parses a single Python file to find top-level classes and functions using AST.
        It yields a dictionary for the file itself, then for each class and function found.
        """
        if not self._is_running: return

        # First, yield the file item itself
        parent_rel_path = os.path.dirname(file_rel_path) or '.'
        yield {
            'id': file_rel_path,
            'parent_id': parent_rel_path,
            'name': os.path.basename(file_full_path),
            'type': 'file',
            'rel_path': file_rel_path,
            'full_path': file_full_path,
        }

        # Now, parse the file for classes and functions
        try:
            with open(file_full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            tree = ast.parse(content)
            for node in tree.body:
                if not self._is_running: return
                
                # Determine end line for class/function to allow for accurate content extraction
                end_lineno = node.end_lineno if hasattr(node, 'end_lineno') else node.lineno
                
                if isinstance(node, ast.ClassDef):
                    yield {
                        'id': f"{file_rel_path}/{node.name}",
                        'parent_id': file_rel_path,
                        'name': node.name,
                        'type': 'class',
                        'rel_path': file_rel_path,
                        'full_path': file_full_path,
                        'start_line': node.lineno,
                        'end_line': end_lineno
                    }
                elif isinstance(node, ast.FunctionDef):
                    yield {
                        'id': f"{file_rel_path}/{node.name}",
                        'parent_id': file_rel_path,
                        'name': node.name,
                        'type': 'function',
                        'rel_path': file_rel_path,
                        'full_path': file_full_path,
                        'start_line': node.lineno,
                        'end_line': end_lineno
                    }
        except (SyntaxError, UnicodeDecodeError, OSError, ValueError) as e:
            print(f"Warning: Could not parse {file_rel_path}: {e}")
            pass

    def _scan_directory(self, path):
        """
        Recursively scans a directory. It yields dictionaries for each folder and file.
        For Python files, it delegates to _parse_python_file.
        """
        # --- FIXED: Corrected settings keys and added comprehensive exclusion logic ---
        include_all = self.settings.get("include_all_files", False)
        exclude_list = set(self.settings.get("exclude_list", []))
        exclude_dotfiles = self.settings.get("exclude_dotfiles", True)
        allowed_extensions = set(self.settings.get("extension_map", {}).keys())

        for entry in os.scandir(path):
            if not self._is_running: return

            # --- FIXED: Apply exclusion rules to both files and directories ---
            if entry.name in exclude_list:
                continue
            if exclude_dotfiles and entry.name.startswith('.'):
                continue

            if entry.is_dir():
                dir_full_path = entry.path
                dir_rel_path = os.path.relpath(dir_full_path, self.project_path).replace(os.sep, '/')
                parent_rel_path = os.path.dirname(dir_rel_path) or '.'
                
                yield {
                    'id': dir_rel_path,
                    'parent_id': parent_rel_path,
                    'name': entry.name,
                    'type': 'folder',
                    'rel_path': dir_rel_path,
                    'full_path': dir_full_path,
                }
                yield from self._scan_directory(dir_full_path)

            elif entry.is_file():
                file_full_path = entry.path
                file_rel_path = os.path.relpath(file_full_path, self.project_path).replace(os.sep, '/')
                file_ext = os.path.splitext(entry.name)[1].lower()

                if file_ext == '.py':
                    yield from self._parse_python_file(file_full_path, file_rel_path)
                
                elif include_all or file_ext in allowed_extensions:
                    parent_rel_path = os.path.dirname(file_rel_path) or '.'
                    yield {
                        'id': file_rel_path,
                        'parent_id': parent_rel_path,
                        'name': entry.name,
                        'type': 'file',
                        'rel_path': file_rel_path,
                        'full_path': file_full_path,
                    }