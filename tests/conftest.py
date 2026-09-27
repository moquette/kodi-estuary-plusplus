import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent

# The shim add-on's scripts dir, so tests import the REAL service.py rather than
# asserting on its source text.
#
# ONE directory, not two. The skin (then skin.estuary.pov) had a scripts/services.py of its own
# through 1.2.8 and it was on this path beside this one; 1.3.0 deleted it and
# moved its payload into service.tvos.pythonfix. The skin now ships no Python at
# all, which tests/test_skin_has_no_tvos_code.py asserts. If a second directory
# ever comes back here, it must be a second separately installable Kodi add-on
# and neither may import the other: Kodi gives each its own interpreter and its
# own sys.path built from its own declared dependencies.
sys.path.insert(0, str(ROOT / "service.tvos.pythonfix" / "scripts"))
