"""
_bootstrap.py
-------------
Shared sys.path bootstrap for all Streamlit pages.
Import this at the top of every page file BEFORE any project imports.
Ensures the project root is on sys.path regardless of how Streamlit loads the file.
"""
import sys
import os

# Walk up from this file's location to find the project root
# _bootstrap.py lives at: <root>/frontend/_bootstrap.py
_HERE = os.path.dirname(os.path.abspath(__file__))       # frontend/
_ROOT = os.path.dirname(_HERE)                            # project root

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Also add frontend/ so pages can import api_client directly
if _HERE not in sys.path:
    sys.path.insert(1, _HERE)