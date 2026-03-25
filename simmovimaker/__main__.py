"""Entry point for ``python -m simmovimaker``.

When invoked without command-line arguments the GUI application is launched.
When arguments are present the CLI interface is used instead.
"""

import sys


def main():
    """Top-level entry point that dispatches to GUI or CLI mode.

    Returns an integer exit code suitable for passing to ``sys.exit``.
    """
    if len(sys.argv) > 1:
        from .cli import cli_mode
        return cli_mode()
    else:
        from .app import main as gui_main
        return gui_main()


if __name__ == "__main__":
    sys.exit(main())
