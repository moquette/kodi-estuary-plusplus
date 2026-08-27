"""Skin Shortcuts v3 Entry Point.

Usage from skin:
    RunScript(script.estuary8.shortcuts,type=buildxml)

Or with custom paths:
    RunScript(script.estuary8.shortcuts,type=buildxml&path=special://skin/shortcuts/)
"""

from resources.lib.skinshortcuts.entry import main

if __name__ == "__main__":
    main()
