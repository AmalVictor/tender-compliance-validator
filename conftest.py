"""
conftest.py
-----------
Pytest configuration — ensures project root is on sys.path
so all test imports resolve correctly on Windows.
"""
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))