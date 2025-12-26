#!/usr/bin/env python3
"""
Backwards-compatible setup.py for older pip versions.
Modern pip (>=21.3) can use pyproject.toml directly.
"""

from setuptools import setup, find_packages

setup(
    name="racket-sports-analytics",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.10",
)
