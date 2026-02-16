# Contributing to Charter

Charter is open source because governance shouldn't be behind a paywall. Contributions are welcome.

## Getting Started

```bash
git clone https://github.com/germpharm/charter.git
cd charter
pip install -e ".[test]"
pytest tests/ -v
```

## How to Contribute

1. **Fork the repo** and create a branch from `main`.
2. **Write tests** for any new functionality.
3. **Run the test suite** before submitting: `pytest tests/ -v`
4. **Open a pull request** with a clear description of what you changed and why.

## What We're Looking For

- **Domain templates.** If you work in a regulated industry (legal, energy, defense, biotech), we want governance presets that reflect your domain's constraints.
- **Identity integrations.** Verification providers beyond ID.me. Org HR system connectors. SSO bridges.
- **Bug fixes.** If something doesn't work, fix it.
- **Documentation.** If something isn't clear, clarify it.

## What We're Not Looking For

- Features that break local-first. Charter runs on your machine. Data stays on your machine unless you choose to share it.
- Telemetry or analytics. We don't track users.
- Vendor lock-in. Charter works with any AI provider.

## Code Style

- Python 3.9+ compatible.
- No external dependencies beyond `pyyaml` for the core package.
- Tests use `pytest`.
- Keep it simple. If a function does one thing, that's good.

## Governance

Charter governs AI. We also use Charter to govern Charter. The project's own `charter.yaml` defines the rules we follow as maintainers.

## License

By contributing, you agree that your contributions will be licensed under the Apache 2.0 License.
