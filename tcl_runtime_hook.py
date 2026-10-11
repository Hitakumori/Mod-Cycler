import os
import sys


bundle_dir = getattr(sys, "_MEIPASS", "")
if bundle_dir:
    os.environ["TCL_LIBRARY"] = os.path.join(bundle_dir, "_tcl_data")
    os.environ["TK_LIBRARY"] = os.path.join(bundle_dir, "_tk_data")
