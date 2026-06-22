"""Top-level launcher for PyInstaller.

PyInstaller needs a single entry script; this just forwards to the real main().
"""

from paper_reviewer.main import main


if __name__ == "__main__":
    main()
