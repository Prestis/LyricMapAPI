# Playbook for AI Coding Agents: LyricMap API

Welcome! This document provides instructions, commands, and architecture details to guide any agent working on this repository.

## ⚠️ CRITICAL COMMAND EXECUTION RULE
You **MUST** use the local virtual environment `test_venv` located in the root of this workspace for running any Python scripts, installing packages, or serving the API. 
* Do not use global python or default system-wide python environments.
* PowerShell syntax on Windows is used here.

### Virtual Environment Python Paths
* **Python Executable**: `.\test_venv\Scripts\python.exe`
* **Pip Executable**: `.\test_venv\Scripts\pip.exe`
* **Uvicorn Executable**: `.\test_venv\Scripts\uvicorn.exe`

### 🌐 Windows Console Unicode Encoding
If you encounter `UnicodeEncodeError` issues when executing scripts that output emojis or Greek text, set the encoding environment variable in PowerShell first:
```powershell
$env:PYTHONIOENCODING="utf-8"
```

---

## 🛠️ Common Developer Tasks & Commands

### 1. Install & Update Dependencies
Always run package installs via the `test_venv` pip:
```powershell
.\test_venv\Scripts\pip.exe install -r requirements.txt
```

### 2. Start the FastAPI Application
To run the server in development mode with hot-reloading:
```powershell
.\test_venv\Scripts\uvicorn.exe rest-api:app --reload --host 127.0.0.1 --port 8000
```
Or run `rest-api.py` directly:
```powershell
.\test_venv\Scripts\python.exe rest-api.py
```

### 3. Running Data Migrations
To migrate legacy JSON metadata (`rappers_locations.json`, `processed_songs.json`, `api_usage.json`) into the SQLite database:
```powershell
.\test_venv\Scripts\python.exe tools/migrate_data.py
```

To run schema updates (such as adding columns like `is_manual` to the SQL database):
```powershell
.\test_venv\Scripts\python.exe migrate_is_manual.py
```

### 4. Testing NLP / Named Entity Recognition (NER)
This project extracts locations using `gr-nlp-toolkit`. To test this pipeline in isolation on sample Greek text:
```powershell
.\test_venv\Scripts\python.exe tools/test_ner_switch.py
```
Or check general NER token tagging:
```powershell
.\test_venv\Scripts\python.exe tools/debug_ner.py
```

### 5. Testing Gemini API Geocoding
To verify the Gemini API configuration, network connection, and model selection (`gemini-3.1-flash-lite-preview`):
```powershell
.\test_venv\Scripts\python.exe tools/find_models.py
```

---

## 📂 Project Structure

* `rest-api.py`: The entrypoint FastAPI application containing routes, background queues, and coordinates calculation.
* `database.py`: SQLAlchemy schemas, SQLite database setup, connection session generator (`get_db`).
* `requirements.txt`: Project dependencies list.
* `tools/`: Collection of diagnostic and migration utility scripts.
* `Greek-Rappers-Genius-API.csv`: Seed file of Greek rappers.

---

## 🔑 Environment Variables (`.env`)
Make sure the `.env` file in the root directory contains valid secrets:
* `GENIUS_TOKEN`: Genius Client Access Token for searching artists and fetching song lyrics.
* `GEMINI_API_KEY`: API key for Gemini models to fetch latitude/longitude coordinates of places.
* `SECRET_KEY`: Used to sign JWTs for administrative endpoints (e.g., updating location coordinates).

---

## 🐳 Docker Deployment & Containerization
While local development testing is performed using `test_venv`, production deployment is fully containerized using **Docker** and **Docker Compose**.

### Docker Commands
* **Build and Start Container (Detached)**:
  ```powershell
  docker compose up --build -d
  ```
* **View Container Logs**:
  ```powershell
  docker compose logs -f api
  ```
* **Stop Container**:
  ```powershell
  docker compose down
  ```

### Key Configurations
* **Database Persistence**: The SQLite database (`lyricmap.db`) in the root directory is mounted into the container at `/app/lyricmap.db` to ensure data persistence across container builds and restarts.
* **Greek NLP Models**: The [Dockerfile](file:///c:/Users/orest/Downloads/LyricMapAPI/LyricMap/Dockerfile) includes a pre-download step for Greek NLP models (`RUN python -c 'from gr_nlp_toolkit import Pipeline; Pipeline("ner")'`) to prevent startup latency during container execution.
* **Environment Variables**: The `docker-compose.yml` file imports environment variables dynamically from `.env` via the `env_file` directive.
