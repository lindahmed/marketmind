"""Generate local development secrets without printing them or replacing existing config."""
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; edit it explicitly if needed.")
values = (root / ".env.example").read_text(encoding="utf-8")
for placeholder in ("REPLACE_WITH_A_DATABASE_PASSWORD", "REPLACE_WITH_A_RANDOM_SECRET_AT_LEAST_32_CHARACTERS",
                    "REPLACE_WITH_ANOTHER_RANDOM_SECRET", "REPLACE_WITH_A_DISTINCT_RANDOM_URL_SAFE_PASSWORD",
                    "REPLACE_WITH_ANOTHER_RANDOM_URL_SAFE_PASSWORD"):
    values = values.replace(placeholder, secrets.token_hex(32))
target.write_text(values, encoding="utf-8")
print("Created .env with random local development secrets.")
