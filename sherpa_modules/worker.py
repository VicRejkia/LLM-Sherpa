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

    def _parse_python_file(self, full_path, file_rel_path, results):
        """
        BUG FIX: Rewritten for robust AST parsing.
        This version wraps the child node iteration in a try-except block to handle
        node types that are not iterable (e.g., BinOp, Constant), fixing the console errors.
        """
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source)
            
            node_parents = {}
            for node in ast.walk(tree):
                # This try-except block makes the AST parsing much more robust.
                try:
                    for child in ast.iter_child_nodes(node):
                        node_parents[child] = node
                except TypeError:
                    # Some node types like BinOp, Constant, etc., are not iterable
                    continue

            for node in ast.walk(tree):
                parent_id = file_rel_path 

                if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                    parent_node = node_parents.get(node)
                    while parent_node:
                        if isinstance(parent_node, ast.ClassDef):
                            parent_id = f"{file_rel_path}::{parent_node.name}"
                            break
                        parent_node = node_parents.get(parent_node)

                if isinstance(node, ast.ClassDef):
                    results.append({
                        'name': node.name, 'full_path': full_path,
                        'id': f"{file_rel_path}::{node.name}", 'parent_id': parent_id,
                        'rel_path': "", 'type': 'class', 'is_dir': False,
                        'start_line': node.lineno, 'end_line': node.end_lineno
                    })
                elif isinstance(node, ast.FunctionDef):
                    func_id = f"{parent_id}::{node.name}" if parent_id != file_rel_path else f"{file_rel_path}::{node.name}"
                    results.append({
                        'name': node.name, 'full_path': full_path,
                        'id': func_id, 'parent_id': parent_id,
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

            # BUG FIX: Ensure correct parent_id for files in the root directory.
            # If the current_path is the project_path, the parent is the root ('.').
            # Otherwise, it's the relative path of the directory.
            item_parent_id = '.' if current_path == self.project_path else os.path.relpath(current_path, self.project_path).replace(os.sep, '/')

            if is_dir:
                results.append({
                    'name': name, 'full_path': full_path, 'rel_path': rel_path,
                    'id': rel_path, 'parent_id': item_parent_id, 'type': 'folder', 'is_dir': True
                })
                self._scan_directory(full_path, rel_path, results)
            else:
                _, ext = os.path.splitext(name)
                if ext.lower() in extension_map:
                    file_item_data = {
                        'name': name, 'full_path': full_path, 'rel_path': rel_path,
                        'id': rel_path, 'parent_id': item_parent_id, 'type': 'file', 'is_dir': False
                    }
                    results.append(file_item_data)
                    if ext.lower() == '.py':
                        self._parse_python_file(full_path, rel_path, results)

    def stop(self):
        self.is_running = False
