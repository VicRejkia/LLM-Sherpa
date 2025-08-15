import os
import json
from PySide6.QtCore import QStandardPaths

class SettingsManager:
    """Manages application-wide settings, loaded from settings.json."""
    def __init__(self, filename="settings.json"):
        # Place settings.json in the same directory as the script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.filename = os.path.join(script_dir, filename)
        self.settings = {}
        self.load_settings()

    def _create_default_settings(self):
        """Creates a default settings dictionary."""
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
            "exclude_dotfiles": True,
            "show_project_structure": True,
            "remember_project_path": True,
            "restore_tree_selection": True,
            "llm_token_budgets": {
                "GPT-4 (8k)": 8192,
                "GPT-4 Turbo (128k)": 128000,
                "Claude 3 Sonnet (200k)": 200000,
                "Gemini 1.5 Pro (1M)": 1000000
            },
            "prompt_templates": {
                "Find Bug": "The following code and error log are from my application. Find the bug and suggest a fix.",
                "Write Unit Tests (pytest)": "Generate a comprehensive set of unit tests for the selected code using the pytest framework.",
                "Explain Code": "Explain the following code to a junior developer, focusing on the overall architecture and the purpose of each key function.",
                "Refactor Code": "Review the selected code for potential improvements. Suggest refactorings to enhance readability, performance, and maintainability."
            },
            "prompt_modules": {
                "General Query": { "objective": "My goal is to...", "focus_tab": "Project" },
                "Debug Error": { "objective": "I am encountering an error. The console output is provided below. Please identify the cause and suggest a solution.", "focus_tab": "Logs / Console" }
            },
            "tdd_prompts": {
                "test_generation": "You are a software developer specializing in Test-Driven Development. Based on the following feature description, write a comprehensive test suite using the pytest framework. The tests should cover all success paths, edge cases, and potential failure scenarios.\n\nFeature Description:\n---\n{feature_description}",
                "code_implementation": "You are a software developer. The following is a test suite written in pytest. Your task is to write the Python code that makes all of these tests pass.\n\nTest Suite:\n---\n{test_suite}"
            }
        }

    def load_settings(self):
        """Loads settings from the file, applying defaults for missing keys."""
        try:
            with open(self.filename, 'r') as f:
                loaded_settings = json.load(f)
            defaults = self._create_default_settings()
            # Ensure new default keys are added to existing user configs
            for key, value in defaults.items():
                if key not in loaded_settings:
                    loaded_settings[key] = value
            self.settings = loaded_settings
        except (FileNotFoundError, json.JSONDecodeError):
            self.settings = self._create_default_settings()
        finally:
            self.save_settings()

    def save_settings(self):
        """Saves the current settings to the file."""
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            print(f"Settings Error: Could not save settings: {e}")

    def get(self, key, default=None):
        """Gets a setting value by key."""
        return self.settings.get(key, default)

    def set(self, key, value):
        """Sets a setting value by key."""
        self.settings[key] = value

class ConfigManager:
    """Manages user-specific configuration like recent projects and UI states."""
    def __init__(self, app_name="LLMSherpa"):
        self.config_dir = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        if not self.config_dir:
            self.config_dir = os.path.join(os.path.expanduser("~"), f".{app_name.lower()}")
        self.config_path = os.path.join(self.config_dir, "config.json")
        self.config = {}
        os.makedirs(self.config_dir, exist_ok=True)
        self.load_config()

    def load_config(self):
        """Loads the configuration file."""
        try:
            with open(self.config_path, 'r') as f:
                self.config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.config = {"last_project_path": "", "tree_states": {}, "recent_project_paths": []}

    def save_config(self):
        """Saves the current configuration."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Config Error: Could not save config: {e}")

    def get(self, key, default=None):
        """Gets a config value by key."""
        return self.config.get(key, default)

    def set(self, key, value):
        """Sets a config value by key."""
        self.config[key] = value

    def get_recent_projects(self):
        """Returns a list of recent project paths."""
        return self.get("recent_project_paths", [])

    def add_recent_project(self, path):
        """Adds a project path to the top of the recent list."""
        recent_paths = self.get_recent_projects()
        if path in recent_paths:
            recent_paths.remove(path)
        recent_paths.insert(0, path)
        self.set("recent_project_paths", recent_paths[:10])