"""Config file management for Charter governance."""

import os
import yaml


CONFIG_NAME = "charter.yaml"


def find_config(path=None):
    """Find charter.yaml starting from path, walking up to root."""
    start = path or os.getcwd()
    current = os.path.abspath(start)
    while True:
        candidate = os.path.join(current, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load_config(path=None):
    """Load and return the charter config dict."""
    config_path = path if path and os.path.isfile(path) else find_config()
    if not config_path:
        return None
    with open(config_path) as f:
        return yaml.safe_load(f)


def save_config(config, path=None):
    """Save config dict to charter.yaml."""
    out = path or CONFIG_NAME
    with open(out, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return os.path.abspath(out)
