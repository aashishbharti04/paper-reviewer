"""PyInstaller entry point for the WEB dashboard build.

Launches the FastAPI server and opens the browser. This is what the installed
PaperReviewer.exe runs — it bundles the full web app (rules engine, plagiarism,
corpus, originality report) rather than the older desktop Tkinter app.
"""

from paper_reviewer_web.app import main


if __name__ == "__main__":
    main()
