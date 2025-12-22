"""
Configuration management for racket sports analytics.
"""

import os
from pathlib import Path
from typing import Any

import yaml


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    return Path(__file__).parent.parent / "configs"


def load_config(sport: str = "badminton") -> dict[str, Any]:
    """
    Load sport-specific configuration.

    Args:
        sport: Sport name (badminton, table_tennis)

    Returns:
        Configuration dictionary
    """
    config_path = get_config_dir() / f"{sport}.yaml"

    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    return config


def merge_configs(base: dict, override: dict) -> dict:
    """
    Recursively merge two configuration dictionaries.

    Args:
        base: Base configuration
        override: Override values

    Returns:
        Merged configuration
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value

    return result


class Config:
    """Configuration wrapper with attribute access."""

    def __init__(self, config_dict: dict[str, Any]):
        for key, value in config_dict.items():
            if isinstance(value, dict):
                setattr(self, key, Config(value))
            else:
                setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        """Convert back to dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, Config):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result

    def __repr__(self) -> str:
        return f"Config({self.to_dict()})"
