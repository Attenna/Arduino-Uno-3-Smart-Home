"""Provision local credentials once; never print passwords or tokens to logs."""
import argparse
from pathlib import Path
import os
import secrets
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser()
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--username", default="HwHiAiUser")
args = parser.parse_args()
paths = [args.directory / name for name in
         (".auth.web.env", ".auth.voice.env", ".auth-admin-credentials.txt")]
if any(path.exists() for path in paths):
    raise SystemExit("Authentication files already exist; refusing to replace credentials")
password = secrets.token_urlsafe(18)
token = secrets.token_urlsafe(48)
web = {"SMART_HOME_ADMIN_USER": args.username,
       "SMART_HOME_ADMIN_PASSWORD_HASH": generate_password_hash(password),
       "SMART_HOME_SESSION_SECRET": secrets.token_urlsafe(48),
       "SMART_HOME_SERVICE_TOKEN": token,
       "PYTHONDONTWRITEBYTECODE": "1", "HOME": "/tmp"}
# Single quotes prevent Compose from interpolating dollar signs in password hashes.
contents = ["".join(f"{key}='{value}'\n" for key, value in web.items()),
            f"SMART_HOME_SERVICE_TOKEN='{token}'\nHOME='/tmp'\nPYTHONDONTWRITEBYTECODE='1'\n",
            f"Web: http://10.29.127.49:5000/login\nUsername: {args.username}\nPassword: {password}\n"]
for path, content in zip(paths, contents):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(content)
print("Authentication files created (0600); credentials saved privately")
