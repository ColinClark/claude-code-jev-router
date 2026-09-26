import sys
from pathlib import Path

# Make the shared generator module (tests/_gen.py) importable.
sys.path.insert(0, str(Path(__file__).parent))
