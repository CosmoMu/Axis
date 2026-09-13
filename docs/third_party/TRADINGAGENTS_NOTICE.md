# TradingAgents Architecture Review Notice

AXIS Multi-Agent Research was designed after reviewing:

- Project: TauricResearch/TradingAgents
- Release/tag: `v0.4.0`
- Reviewed commit: `2448d0a`
- License: Apache License 2.0
- Source: https://github.com/TauricResearch/TradingAgents/tree/v0.4.0
- Release: https://github.com/TauricResearch/TradingAgents/releases/tag/v0.4.0
- License: https://github.com/TauricResearch/TradingAgents/blob/v0.4.0/LICENSE

AXIS adapted high-level architectural concepts only: specialized analyst roles, Bull/Bear research
debate, a research manager, multiple risk perspectives, and point-in-time outcome memory. No
TradingAgents source code, package, graph runtime, prompts, or assets were copied, vendored, or
imported. AXIS uses its own Stock Analyst, GEX, Massive providers, OpenAI ModelRouter, database,
Discord controls, audit, cache, alerts, and policy system.

This notice preserves the provenance of the architecture review even though the resulting AXIS
implementation is independent and AXIS-native.
