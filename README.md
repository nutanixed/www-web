# web-www

`web-www` is a Flask-based file manager web application ("LCM Manager") for browsing, uploading, downloading, deleting, and releasing bundle files from a configured server-side directory.

## Features

- Folder-aware file browser with breadcrumb navigation.
- Upload one or more files into a selected subfolder.
- Create folders and rename files/folders.
- Single and bulk delete actions.
- Single-file download and bulk ZIP download.
- Bundle extraction workflow for `.tar.gz` files from `staging` into `release`.
- Optional LDAP authentication support (currently bypassed in code).

## Tech Stack

- Python 3.10
- Flask
- ldap3
- python-dotenv
- Gunicorn (used by restart script for long-running service)
- Tailwind CSS (via CDN in templates)

## Project Structure

```text
web-www/
├── app.py                # Main Flask app and route handlers
├── templates/
│   ├── index.html        # Main dashboard UI
│   └── login.html        # Login page UI (not currently active)
├── static/
│   ├── favicon.svg
│   └── logo.png
├── .env                  # Runtime configuration (local, not committed)
├── restart.sh            # Self-healing Gunicorn watchdog launcher
├── devbox.json           # Devbox config (Python 3.10)
└── README.md
```

## Requirements

- Linux environment
- Python 3.10+
- `tar` CLI available on PATH (used in release flow)
- Writable upload root directory for the app

## Configuration

The app loads configuration from `.env` using `python-dotenv`.

### Required Variables

- `FLASK_SECRET_KEY`: Secret key for Flask session management.
- `UPLOAD_FOLDER`: Absolute path to the file root managed by this app.

### Authentication Variables

- `AUTH_USERNAME`: Local username fallback.
- `AUTH_PASSWORD`: Local password fallback.
- `LDAP_SERVER`: LDAP server URI/host.
- `LDAP_ADMIN_DN`: LDAP bind DN for user lookup.
- `LDAP_ADMIN_PASSWORD`: LDAP bind password.
- `LDAP_USER_SEARCH_BASE`: LDAP search base DN.
- `LDAP_USER_ATTRIBUTE`: LDAP username attribute (for example `sAMAccountName`).
- `LOGOUT_REDIRECT_URL`: Redirect target after logout (default `/`).

### Example `.env`

```env
FLASK_SECRET_KEY=change-me
UPLOAD_FOLDER=/www

AUTH_USERNAME=admin
AUTH_PASSWORD=changeme

LDAP_SERVER=ldap://ldap.example.com
LDAP_ADMIN_DN=cn=readonly,dc=example,dc=com
LDAP_ADMIN_PASSWORD=secret
LDAP_USER_SEARCH_BASE=ou=users,dc=example,dc=com
LDAP_USER_ATTRIBUTE=sAMAccountName

LOGOUT_REDIRECT_URL=/
```

## Local Development

### 1) Create and activate a virtual environment

```bash
cd /home/ubuntu/web-www
python3 -m venv .venv
source .venv/bin/activate
```

### 2) Install dependencies

No lockfile/requirements file is currently tracked in this repo, so install directly:

```bash
pip install flask ldap3 python-dotenv gunicorn
```

### 3) Configure `.env`

Set at least `FLASK_SECRET_KEY` and `UPLOAD_FOLDER`.

### 4) Run the app (dev server)

```bash
python app.py
```

The app listens on `0.0.0.0:5000` by default.

## Running with Devbox (optional)

This repo includes `devbox.json` with Python 3.10:

```bash
cd /home/ubuntu/web-www
devbox shell
```

Then create/activate `.venv`, install dependencies, and run as above.

## Production/Service Run

Use the included watchdog script:

```bash
cd /home/ubuntu/web-www
chmod +x restart.sh
./restart.sh
```

What it does:

- Stops existing matching Gunicorn/watchdog processes.
- Starts Gunicorn on `0.0.0.0:5000` with 2 workers and timeout 300.
- Wraps Gunicorn in a restart loop if it exits unexpectedly.

Log files:

- `/tmp/file-manager-dashboard.log`
- `/tmp/file-manager-error.log`

## Route Overview

UI Routes:

- `GET /` - Main dashboard (directory and file listing).
- `GET|POST /login` - Login endpoint (currently redirects to `/` immediately).
- `GET /logout` - Clears session and redirects.

File Operations:

- `POST /upload` - Upload files to selected subdirectory (root upload blocked).
- `POST /create-folder` - Create folder in current directory.
- `POST /rename` - Rename file/folder.
- `POST /delete/<filename>` - Delete one file/folder.
- `POST /delete-bulk` - Bulk delete selected items.
- `GET /download/<filename>` - Download single file.
- `POST /download-zip` - Download selected files/folders as ZIP.

Bundle Release:

- `POST /release` with `check_only=true` - Detect duplicate extraction targets.
- `POST /release` - Copy/extract selected `.tar.gz` from staging to release and remove source tarball on success.

## Authentication Behavior (Current State)

Authentication is intentionally bypassed in the current code:

- `@app.before_request` auto-sets `session['logged_in'] = True`.
- `/login` immediately redirects to `/`.
- `@requires_auth` protections are commented out on routes.

If you need real authentication, remove the bypass logic and re-enable route decorators.

## Security Notes

- Path traversal is mitigated by resolving absolute paths and verifying they remain under `UPLOAD_FOLDER`.
- Folder and renamed item names are sanitized using `secure_filename`.
- Bulk delete strips path components via `os.path.basename`.

## Operational Notes

- Uploads to root (`.`) are intentionally rejected.
- Release workflow is designed around `staging` and `release` directories under `UPLOAD_FOLDER`.
- Extraction uses system `tar`, so behavior depends on server tar implementation and permissions.

## Troubleshooting

- **App fails on startup**: verify `.env` exists and `UPLOAD_FOLDER` path is valid/writable.
- **LDAP login issues**: verify bind DN/password, search base, and username attribute values.
- **Release extraction fails**: ensure selected files are valid `.tar.gz` and `tar` is installed.
- **Permission errors**: ensure the process user has read/write permissions under `UPLOAD_FOLDER`.

## Recommended Next Improvements

- Add `requirements.txt` (or lockfile) for reproducible dependency install.
- Re-enable auth and protect all write/delete routes with `@requires_auth`.
- Add automated tests for upload/delete/release edge cases.
- Add containerization and health checks for deployment consistency.
