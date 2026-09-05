# Agent compatibility

The canonical repository is itself the installable Skill folder for Codex and Claude Code. Keep platform-neutral instructions in `SKILL.md` and avoid product-specific tool names in its shared frontmatter. WorkBuddy's import format requires additional top-level metadata that Codex rejects, so `scripts/package_workbuddy_skill.py` injects those fields only into the generated WorkBuddy ZIP.

| Host | User installation path | Notes |
|---|---|---|
| Codex | `~/.codex/skills/data-lens/` | `agents/openai.yaml` supplies optional UI metadata. |
| Claude Code | `~/.claude/skills/data-lens/` | The shared `SKILL.md`, scripts, references, and assets are discovered directly. |
| WorkBuddy/CodeBuddy | `~/.codebuddy/skills/data-lens/` | Run `python scripts/package_workbuddy_skill.py`, then import the generated ZIP whose root is `skills/data-lens/`. |

Platform-specific fields such as tool allowlists, forked context, or model selection are intentionally absent from the canonical `SKILL.md`; their meanings and tool names differ across hosts. Permissions remain controlled by the host.

Compatibility checks validate the neutral source frontmatter and the generated WorkBuddy metadata, version consistency, relative resource links, portable paths, and absence of hard-coded user directories. They do not claim that an unavailable host or optional runtime is installed, nor do they replace an actual cross-host execution test.

Analytical compatibility is evaluated separately. The shared probes in [semantic-invariants.md](semantic-invariants.md) test causal calibration, unit identity, statistical calibration, mechanism-test directness, and preservation of native-host findings. A host passing package validation has not passed semantic conformance; a host passing the small probes has not yet demonstrated real analytical increment without a full blind task.
