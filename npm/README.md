# selqor-mcp-forge (npm wrapper)

Node wrapper around the [Selqor MCP Forge](https://github.com/Selqor-Labs/Selqor-MCP-Forge) Python CLI.

Turn noisy API surfaces into curated MCP servers agents can actually use. Parse OpenAPI specs, preserve coverage, compress tool sprawl, and generate hardened MCP targets.

## Requirements

- **Node.js 18+**
- **Python 3.11+** (the actual Selqor MCP Forge engine is Python)

## Install

```bash
npm install -g selqor-mcp-forge
pipx install selqor-mcp-forge    # or: pip install --user selqor-mcp-forge
```

Both are needed: the npm package provides the `selqor-mcp-forge` command shim, and the Python package provides the engine it runs.

If you forget the Python half, the wrapper prints explicit install guidance instead of failing silently.

## Use

```bash
selqor-mcp-forge generate https://petstore.swagger.io/v2/swagger.json --out ./petstore-output
```

That is the golden path: a curated tool plan and a generated TypeScript MCP server, ready to boot over `stdio`.

Dashboard and all other subcommands forward transparently — see the full CLI docs in the main repository README.

## Why a wrapper, not a port

Selqor MCP Forge's analysis pipeline, spec parser, and MCP codegen are Python. The npm wrapper exists so Node-first developers can discover and install it through their native package manager without giving up the Python engine's depth. It is intentionally thin: a single `bin/selqor-mcp-forge.js` that resolves a compatible Python interpreter and forwards stdin/stdout/exit code.

## License

Apache-2.0. See [LICENSE](./LICENSE).
