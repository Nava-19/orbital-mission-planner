import os
import sys

# The project's modules (environment.py, orbital.py, solver.py, ...) live
# at the repo root, one level up from this tests/ directory — add it to
# sys.path so `import environment` etc. work regardless of where pytest
# is invoked from.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
