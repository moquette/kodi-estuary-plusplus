import pathlib
import sys

# The skin's scripts/ dir, so tests import the REAL services.py.
sys.path.insert(
    0, str(pathlib.Path(__file__).resolve().parent.parent / "skin.estuary.pov" / "scripts")
)
