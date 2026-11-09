# 0001 – Use uv for Python packaging

- **Date:** 2026-11-09
- **Status:** Accepted

## Context
The backend needs an isolated environment per project, a dependency list,
and a lockfile so local, Docker and CI installs are identical.

## Options considered
1. **pip + venv** – built in, but no lockfile; versions must be pinned by hand.
2. **Poetry** – mature, has a lockfile, but slow and doesn't install Python itself.
3. **uv** – one fast tool for Python versions, environments, dependencies and locking.

## Decision
Use **uv**.

## Consequences
- ✅ One tool to learn instead of 2–3; fast installs in Docker and CI.
- ✅ Uses the standard `pyproject.toml`, so we can switch tools later if needed.
- ⚠️ Newer than Poetry, so fewer old tutorials and StackOverflow answers.