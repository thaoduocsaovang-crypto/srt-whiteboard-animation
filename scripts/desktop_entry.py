"""Entry point used only by the distributable Windows executable."""
from gui_server import main


if __name__ == "__main__":
    # A double-clicked one-file executable should behave as a desktop app.
    main(["--open"])
