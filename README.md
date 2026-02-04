# pqtrader (QTrader)

A flexible, event-driven backtesting framework for quantitative trading.

This repository provides the `qtrader` Python package, including a backtest engine, accounts/positions, matching & slippage/commission models, performance analysis, and a built-in monitoring server.

## Features

- Event-driven backtesting engine
- Strategy / framework separation
- Pluggable data providers (implement the standard interface)
- Snapshot & state persistence (pause / resume / fork)
- Performance analytics and report generation
- Built-in web monitoring server (Flask + SocketIO)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
```

## Quick Start

Run the example backtest runner:

```bash
python -m qtrader.examples.run_backtest
```

If you prefer to run the script directly:

```bash
python qtrader/examples/run_backtest.py
```

## Documentation

- User guide: `USER_GUIDE.md`
- Design notes: `design/design_v7.md`

## Development

```bash
pip install -e .[test]
pytest -q
```

## License

No license file is included yet. If you plan to open-source this repository, add a `LICENSE` file (e.g., MIT/Apache-2.0) before making it public.
