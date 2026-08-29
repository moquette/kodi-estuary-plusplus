import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The skin's scripts/ dir, so tests import the REAL services.py, and the shim
# add-on's, so they import the REAL service.py. Two directories rather than a
# package, because these are two separately installable Kodi add-ons and neither
# may ever import the other: Kodi gives each its own interpreter and its own
# sys.path built from its own declared dependencies.
sys.path.insert(0, str(ROOT / "skin.estuary.pov" / "scripts"))
sys.path.insert(0, str(ROOT / "service.tvos.pythonfix" / "scripts"))
