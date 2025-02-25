from plain.assets.finders import APP_ASSETS_DIR
from plain.runtime import APP_PATH

# The tailwind.css source file is stored at the root of the repo,
# where can see all sources in the repo and manually refer to other plain sources.
TAILWIND_SRC_PATH = APP_PATH.parent / "tailwind.css"

# The compiled css goes in the root assets directory.
# It is typically gitignored.
TAILWIND_DIST_PATH = APP_ASSETS_DIR / "tailwind.min.css"
