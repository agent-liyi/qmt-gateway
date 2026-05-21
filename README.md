# qmt-gateway

`qmt-gateway` is the Windows-only live gateway extracted from the original
`pyqmt` codebase. It focuses on two responsibilities only:

- live trading via QMT / xtquant
- real-time market data subscription and websocket broadcasting

The repository is intentionally independent from `quantide` so the main
application can continue to run on macOS/Linux while the gateway stays on the
Windows machine that has QMT installed.

## Scope

The gateway currently provides:

- FastHTML-based login and initialization flow
- runtime configuration and local SQLite persistence
- quote subscription / websocket publishing
- trade, holdings, account and stock related REST endpoints
- historical minute-bar download tasks
- a lightweight emergency trading UI for manual operations

## Requirements

- Windows
- Python 3.13
- QMT installed on the same machine
- xtquant import path available through configured `QMT` / `xtquant` paths

## Development Setup

`uv` is the default dependency manager for this repository.

Install `uv` once if needed:

```bat
C:\Users\aaron\miniconda3\envs\qmt\python.exe -m pip install --user uv
```

Create the virtual environment and sync dependencies:

```bat
setup-venv.bat
```

Start the gateway in the foreground:

```bat
start-qmt-gateway.bat
```

The server runs in the foreground, so `Ctrl+C` stops it cleanly.

## Runtime Defaults

- host: `0.0.0.0`
- port: `8130`
- home: `<repo>\data\home`

You can override them with environment variables before launch:

- `QMT_GATEWAY_HOST`
- `QMT_GATEWAY_PORT`
- `QMT_GATEWAY_HOME`

## Validation

```bat
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m qmt_gateway.__main__ --help
```
