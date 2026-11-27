"""Test isolation, applied before any app module is imported (app.settings reads the environment at import).

- DATA_DIR points at a throwaway folder, so no test can open or write the app's real database in backend/data.
- OPENROUTER_API_KEY is set empty: python-dotenv never overrides a variable that is already set, so the key in
  backend/.env is never loaded and no test can reach a model.
"""

import atexit
import os
import shutil
import tempfile

_data_dir = tempfile.mkdtemp(prefix="ap-tests-")
atexit.register(shutil.rmtree, _data_dir, True)
os.environ["DATA_DIR"] = _data_dir
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["STAGE_MIN_VISIBLE_SECONDS"] = "0"
