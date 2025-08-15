import os
import json
from PySide6.QtCore import QStandardPaths

class SettingsManager:
    def __init__(self, filename="settings.json"):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.filename = os.path.join(script_dir, '..', filename) # Place it in the parent dir
        self.settings = {}
        self.load_settings()

    def _create_default_settings(self):
        return {
            "extension_map": {
                ".py": "python", ".sql": "sql", ".js": "javascript", ".html": "html",
                ".css": "css", ".json": "json", ".md": "markdown", ".txt": "text",
                ".yml": "yaml", ".yaml": "yaml", ".toml": "toml", ".ini": "ini",
                ".sh": "bash", ".bat": "batch", ".dockerfile": "dockerfile", ".java": "java",
                ".cpp": "cpp", ".c": "c", ".h": "c", ".hpp": "cpp", ".cs": "csharp"
            },
            "exclude_list": [
                "__pycache__", ".git", ".vscode", "node_modules", "venv", ".env", "target", "build", "dist"
            ],
            "known_dependency_files": [
                "requirements.txt", "package.json", "Pipfile", "pyproject.toml",
                "pom.xml", "build.gradle", "go.mod", "Cargo.toml"
            ],
            "exclude_dotfiles": True,
            "show_project_structure": True,
            "remember_project_path": True,
            "restore_tree_selection": True,

            # --- NEW FEATURE: Advanced Token & Context Management ---
            "llm_token_budgets": {
                "GPT-4 (8k)": 8192,
                "GPT-4 Turbo (128k)": 128000,
                "Claude 3 Sonnet (200k)": 200000,
                "Gemini 1.5 Pro (1M)": 1000000
            },
            
            # --- NEW FEATURE: Prompt Engineering Suite ---
            "prompt_templates": {
                "Find Bug": "The following code and error log are from my application. Find the bug and suggest a fix.",
                "Write Unit Tests (pytest)": "Generate a comprehensive set of unit tests for the selected code using the pytest framework.",
                "Explain Code": "Explain the following code to a junior developer, focusing on the overall architecture and the purpose of each key function.",
                "Refactor Code": "Review the selected code for potential improvements. Suggest refactorings to enhance readability, performance, and maintainability."
            }
        }

    def load_settings(self):
        try:
            with open(self.filename, 'r') as f:
                loaded_settings = json.load(f)
                defaults = self._create_default_settings()
                # --- CONFIGURATION ROBUSTNESS CHANGE ---
                # This ensures new default keys are added to existing user configs.
                for key, value in defaults.items():
                    if key not in loaded_settings:
                        loaded_settings[key] = value
                self.settings = loaded_settings
        except (FileNotFoundError, json.JSONDecodeError):
            self.settings = self._create_default_settings()
        finally:
            self.save_settings()


    def save_settings(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Settings Error: Could not save settings: {e}")

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        self.settings[key] = value

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
        self.set("recent_project_paths", recent_paths[:10])