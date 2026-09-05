"""Makes `import multi_roblox` work from tests/ regardless of pytest's
rootdir-insertion mode - multi_roblox.py lives at the repo root, not in an
installed package."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
