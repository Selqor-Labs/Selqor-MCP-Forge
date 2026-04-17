# Contributing

## Getting Started

1. Install Python 3.11+ and Node.js 20+.
2. Create an editable Python install with dev dependencies:

```bash
pip install -e .[dev]
```

3. Build the dashboard frontend:

```bash
cd src/dashboard/frontend
npm ci
npm run build
cd ../../..
```

## Development Workflow

1. Create a branch from `forge-mcp`.
2. Make focused changes with tests for behavior changes.
3. Run the local checks before opening a pull request:

```bash
pytest -q
```

```bash
cd src/dashboard/frontend
npm run build
```

## Pull Requests

- Keep pull requests scoped to one concern when possible.
- Update docs and examples when behavior changes.
- Call out any follow-up work or known limitations in the PR description.
