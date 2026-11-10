"""Keep host GIO plugins from linking against the frozen application's GLib."""

import os
import sys


if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
    os.environ["GIO_MODULE_DIR"] = os.path.join(sys._MEIPASS, "nuwriter-gio-modules")
    os.environ.pop("GIO_EXTRA_MODULES", None)
    os.environ["GIO_USE_VFS"] = "local"
    os.environ["GSETTINGS_BACKEND"] = "memory"