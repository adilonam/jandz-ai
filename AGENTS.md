# Agent rules (FastAPI / Python)

1. **Use FastAPI patterns** — Define routes on an `app = FastAPI()` instance; use path/query/body parameters with type hints and Pydantic models for request and response shapes.

2. **Keep async I/O correct** — Use `async def` for handlers that await I/O (DB, HTTP clients, queues); use plain `def` only for CPU-bound or sync code, and avoid blocking the event loop in async routes.

3. **Validate at the edge** — Rely on Pydantic for input validation and explicit response models (`response_model`) so errors and serialization stay consistent.

4. **Structured layout** — Split routers (`APIRouter`), settings/config, and shared dependencies (`Depends`) into modules as the API grows instead of putting everything in one file.

5. **Dependencies explicit** — Pin versions in `requirements.txt` or `pyproject.toml`; run tests and linters locally before merging changes that touch API behavior.

- use psql to ask the database credential are on DATABASE_URL

- make a good architecture 