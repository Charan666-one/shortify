# Complete Command List

Every command needed to run the project locally, from a fresh clone.

> Converted from `Execution steps /Complete Command List .pdf`, with two
> corrections: the PDF's `uvicorn main:app —reload` carried an em dash and
> fails as typed (it needs `--reload`), and its
> `pip install fastapi uvicorn sqlalchemy` omitted `python-dotenv` and
> `pydantic`, so the app raised `ModuleNotFoundError` on import. Both are fixed
> below by installing from `requirements.txt`.

## 1. Open a terminal

In VS Code: `Ctrl` + `` ` ``

## 2. Create a virtual environment

```bash
python3 -m venv .venv
```

The directory is `.venv` (not `venv`) because that is what `.gitignore` and the
project tooling expect.

## 3. Activate it

**macOS / Linux**

```bash
source .venv/bin/activate
```

**Windows (PowerShell)**

```powershell
.venv\Scripts\Activate.ps1
```

**Windows (cmd)**

```cmd
.venv\Scripts\activate.bat
```

## 4. Install dependencies

```bash
pip install -r requirements.txt
```

## 5. Configure the environment (optional)

```bash
cp .env.example .env
```

Skip this and the defaults in `main.py` apply: SQLite at `./urls.db` on port
8000. Never commit the resulting `.env`.

## 6. Create the database schema

```bash
alembic upgrade head
```

Alembic owns the schema. Skipping this leaves the app running against a
database with no `urls` table — it logs exactly that at startup and every
request fails.

If you have an older `urls.db` created before migrations existed, run
`alembic stamp head` once so Alembic knows where it starts from.

## 7. Run the server

```bash
uvicorn main:app --reload
```

Or `python main.py`, which reads `PORT` from the environment and binds
`0.0.0.0`.

## 8. Open it

<http://127.0.0.1:8000>

Interactive API docs are at <http://127.0.0.1:8000/docs>.

Press `Ctrl` + `C` to stop the server.

---

## Copy-paste block

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

**Windows (PowerShell)**

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
uvicorn main:app --reload
```

---

## Running in Docker

```bash
docker compose up --build
```

Brings up Postgres and the app together, waits for the database to accept
connections, runs migrations, then serves on <http://localhost:8000> under
gunicorn with uvicorn workers — the same command the production image uses.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```
