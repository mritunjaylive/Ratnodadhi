"""
conftest.py – pytest configuration for the booklib test suite.

Makes the booklib package importable from the project root without
needing an editable install.
"""
import sys
from pathlib import Path

# Ensure project root is on sys.path so `import booklib` works.
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(["pytest", "-platform", "offscreen"])
    return app
