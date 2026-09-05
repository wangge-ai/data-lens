# Agent compatibility

The canonical `SKILL.md` is shared by Codex, Claude Code, and WorkBuddy/CodeBuddy. Keep its frontmatter platform-neutral. WorkBuddy/CodeBuddy's official Skill specification requires `name` and `description`; scripts, references, and assets are optional bundled resources. Data Lens therefore does not fork the analytical instructions or inject unverified host-only metadata.

| Host | User installation path | Notes |
|---|---|---|
| Codex | `~/.codex/skills/data-lens/` | `agents/openai.yaml` supplies optional UI metadata. |
| Claude Code | `~/.claude/skills/data-lens/` | The shared `SKILL.md`, scripts, references, and assets are discovered directly. |
| WorkBuddy/CodeBuddy | `~/.codebuddy/skills/data-lens/` or `<project>/.codebuddy/skills/data-lens/` | Run `python scripts/package_workbuddy_skill.py`, then import the generated local Skill package. |

The generated ZIP keeps the canonical `SKILL.md`, executable resources, synthetic test fixtures, the host-neutral core smoke suite, and public usage notes. It omits repository instructions, host-specific UI metadata, changelogs, developer-only tests, historical comparison material, and private expectations. Platform-specific fields such as tool allowlists, forked context, or model selection stay out of the shared frontmatter because their meanings and tool names differ across hosts. Permissions remain controlled by the host.

Compatibility checks validate the shared frontmatter, relative resource links, portable paths, package contents, and an extracted-package capability run. They do not claim that an unavailable host or optional runtime is installed, nor do they replace an actual invocation inside WorkBuddy/CodeBuddy.

Package checks do not judge report quality. Verify that separately with a fresh WorkBuddy task and new source material.

Official references: [WorkBuddy/CodeBuddy Skills](https://cloud.tencent.com/document/product/1831/134516) and [`.codebuddy` directory structure](https://cloud.tencent.com/document/product/1831/137016).
