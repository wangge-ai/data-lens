# Agent compatibility

The canonical repository is itself the installable Skill folder. Keep platform-neutral instructions in `SKILL.md` and avoid product-specific tool names in the shared frontmatter.

| Host | User installation path | Notes |
|---|---|---|
| Codex | `~/.codex/skills/data-lens/` | `agents/openai.yaml` supplies optional UI metadata. |
| Claude Code | `~/.claude/skills/data-lens/` | The shared `SKILL.md`, scripts, references, and assets are discovered directly. |
| WorkBuddy/CodeBuddy | `~/.codebuddy/skills/data-lens/` | The same folder can be installed at user scope or imported through the Skill interface. |

Platform-specific fields such as tool allowlists, forked context, or model selection are intentionally absent from the canonical `SKILL.md`; their meanings and tool names differ across hosts. Permissions remain controlled by the host.

Compatibility checks verify the common frontmatter, relative resource links, portable paths, and absence of hard-coded user directories. They do not claim that an unavailable optional runtime is installed.
