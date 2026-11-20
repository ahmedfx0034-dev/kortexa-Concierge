"""Keep every test away from the real data/ folder."""
import os
import tempfile

os.environ["STUDIO_DATA_DIR"] = tempfile.mkdtemp(prefix="studio-test-")
for _k in ("ANTHROPIC_API_KEY", "IG_USER_ID", "IG_ACCESS_TOKEN", "BLOB_READ_WRITE_TOKEN", "APIFY_TOKEN"):
    os.environ.pop(_k, None)
