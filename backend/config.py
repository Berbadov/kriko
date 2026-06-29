import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/kriko",
)

# CORS: allow the Chrome extension origin. The extension ID must be set in env
# for production; localhost is allowed for local dev.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "chrome-extension://localhost,http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if o.strip()
]

# Disclaimer text — always appended to every response.
# HUMAN DECISION #4: final legal wording should be reviewed by counsel.
STANDARD_DISCLAIMER = (
    "Known reliability risks from public sources for this specific variant. "
    "Absence of a listed issue does not mean the car is fault-free — "
    "always get an independent pre-purchase inspection before buying."
)
