#!/usr/bin/env python3
"""ONI Companion's service for Barry: runs the bundled core in barry mode.

The core reads BARRY_SERVICE_PORT and BARRY_SERVICE_TOKEN itself.
For development only: ONI_COMPANION_MOCK=<repo folder> serves the
synthetic fixtures with devtools/mock-server.py instead.
"""
import os
import runpy
import sys

here = os.path.dirname(os.path.abspath(__file__))
mock = os.environ.get("ONI_COMPANION_MOCK")
if mock:
    sys.argv = ["mock-server.py", "--listen", "127.0.0.1:" + os.environ["BARRY_SERVICE_PORT"],
                "--token=" + os.environ["BARRY_SERVICE_TOKEN"], "--v12"] + os.environ.get("ONI_MOCK_FLAGS", "").split()
    if os.environ.get("ONI_MOCK_TICK"):      # dev: bump events every N seconds
        sys.argv += ["--tick", os.environ["ONI_MOCK_TICK"]]
    runpy.run_path(os.path.join(mock, "devtools", "mock-server.py"), run_name="__main__")
else:
    sys.path.insert(0, here)
    if not os.path.isdir(os.path.join(here, "oni_companion")):
        # Run straight from the repo (Barry Simulator, development): the core is not vendored yet.
        sys.path.insert(0, os.path.normpath(os.path.join(here, "..", "..", "core")))
    sys.argv = ["oni_companion", "--mode", "barry"]
    runpy.run_module("oni_companion", run_name="__main__")
