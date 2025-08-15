import os
import sys
import ctypes
from ctypes import wintypes
import ast

from PySide6.QtCore import QObject, Signal, Slot

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
        return long_path_buffer.value if result > 0 else short_path
    except Exception:
        return short_path

class FileSystemWorker(QObject):
    results_ready = Signal(list)
    error = Signal(str)
    finished = Signal()

    def __init__(self, path, settings):
        super().__init__()
        self.project_path = path
        self.settings = settings
        self.is_running = True

    @Slot()
    def run(self):
        try:
            results = []
            self._scan_directory(self.project_path, '.', results)
            if self.is_running: self.results_ready.emit(results)
        except Exception as e:
            if self.is_running: self.error.emit(f"An unexpected error occurred: {e}")
        finally:
            self.finished.emit()

    # --- REWRITE: For AST-Powered Code Analysis ---
    def _parse_python_file(self, full_path, file_rel_path, results):
        """Parses a Python file to find classes and functions."""
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    # Find the parent of the class definition
                    parent_id = file_rel_path
                    # This is a simplification; nested classes would require tracking the parent class ID.
                    
                    results.append({
                        'name': node.name, 'full_path': full_path,
                        'id': f"{file_rel_path}::{node.name}", 'parent_id': parent_id,
                        'rel_path': "", 'type': 'class', 'is_dir': False,
                        'start_line': node.lineno, 'end_line': node.end_lineno
                    })
                elif isinstance(node, ast.FunctionDef):
                    # Find the parent of the function definition
                    parent_id = file_rel_path
                    # This is a simplification; methods in classes would require tracking the parent class ID.

                    results.append({
                        'name': node.name, 'full_path': full_path,
                        'id': f"{file_rel_path}::{node.name}", 'parent_id': parent_id,
                        'rel_path': "", 'type': 'function', 'is_dir': False,
                        'start_line': node.lineno, 'end_line': node.end_lineno
                    })
        except Exception as e:
            print(f"Could not parse AST for {full_path}: {e}")


    def _scan_directory(self, current_path, parent_id, results):
        if not self.is_running: return
            
        exclude_list = self.settings.get("exclude_list", [])
        exclude_dotfiles = self.settings.get("exclude_dotfiles", True)
        extension_map = self.settings.get("extension_map", {})

        try:
            items = sorted(os.listdir(current_path))
        except (PermissionError, FileNotFoundError): return

        for name in items:
            if not self.is_running: break
            if name in exclude_list or (exclude_dotfiles and name.startswith('.')): continue

            full_path = os.path.join(current_path, name)
            rel_path = os.path.relpath(full_path, self.project_path).replace(os.sep, '/')
            is_dir = os.path.isdir(full_path)

            if is_dir:
                results.append({
                    'name': name, 'full_path': full_path, 'rel_path': rel_path,
                    'id': rel_path, 'parent_id': parent_id, 'type': 'folder', 'is_dir': True
                })
                self._scan_directory(full_path, rel_path, results)
            else:
                _, ext = os.path.splitext(name)
                if ext.lower() in extension_map:
                    # Add the file item itself
                    file_item_data = {
                        'name': name, 'full_path': full_path, 'rel_path': rel_path,
                        'id': rel_path, 'parent_id': parent_id, 'type': 'file', 'is_dir': False
                    }
                    results.append(file_item_data)
                    # If it's a Python file, parse it for functions and classes
                    if ext.lower() == '.py':
                        self._parse_python_file(full_path, rel_path, results)

    def stop(self):
        self.is_running = False