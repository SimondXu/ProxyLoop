#!/usr/bin/env python3
"""Validate the tracked repository foundation and Codex harness."""

from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_PATHS = (
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "GOALS.md",
    "PLANS.md",
    "PROMPTS.md",
    "CONTEXT.md",
    ".codex/config.toml",
    ".codex/agents/implementer.toml",
    ".codex/agents/reviewer.toml",
    ".codex/agents/fast-worker.toml",
    ".codex/agents/explorer.toml",
    ".github/pull_request_template.md",
    "harness/README.md",
    "harness/build/phase-00b-contracts.md",
    "harness/context/README.md",
    "harness/code_review",
    "harness/build-log.md",
    "docs/README.md",
    "docs/specs/2026-08-21-telecom-bill-optimization-agent.md",
    "docs/architecture.md",
    "docs/decisions/2026-08-21-monorepo.md",
    "docs/decisions/2026-08-22-implementation-defaults.md",
    "docs/planning/initial-project-plan.md",
    "docs/planning/progress.md",
    "docs/research/foundations.md",
    "apps/web",
    "runtime/packages/contracts/pyproject.toml",
    "runtime/services/api/pyproject.toml",
    "ml/data_pipeline",
    "voice/worker",
    "contracts/jsonschema",
    "data/manifests",
    "infra/compose",
    "tests/contract",
)

AGENT_CONFIGS = (
    "implementer.toml",
    "reviewer.toml",
    "fast-worker.toml",
    "explorer.toml",
)

EXPECTED_AGENT_SETTINGS = {
    "implementer.toml": ("gpt-5.6-luna", "xhigh", "workspace-write"),
    "reviewer.toml": ("gpt-5.6-terra", "high", "read-only"),
    "fast-worker.toml": ("gpt-5.6-luna", "medium", "workspace-write"),
    "explorer.toml": ("gpt-5.6-luna", "medium", "read-only"),
}


def read_toml(relative_path: str) -> dict[str, object]:
    with (ROOT / relative_path).open("rb") as config_file:
        return tomllib.load(config_file)


def main() -> int:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    if missing:
        print("Missing required paths:", *missing, sep="\n- ")
        return 1
    if not readme.startswith("# ProxyLoop\n"):
        print("README.md must identify the project as ProxyLoop.")
        return 1

    codex_config = read_toml(".codex/config.toml")
    if codex_config.get("model") != "gpt-5.6-sol":
        print(".codex/config.toml must keep Sol as the root orchestrator model.")
        return 1

    agents_config = codex_config.get("agents")
    if not isinstance(agents_config, dict):
        print(".codex/config.toml must define an [agents] table.")
        return 1
    if agents_config.get("max_concurrent_threads_per_session") != 3:
        print("Codex subagent concurrency must remain bounded at three.")
        return 1

    for filename in AGENT_CONFIGS:
        role_name = Path(filename).stem
        role = agents_config.get(role_name)
        if not isinstance(role, dict):
            print(f".codex/config.toml must declare [agents.{role_name}].")
            return 1
        expected_config_file = f"agents/{filename}"
        if role.get("config_file") != expected_config_file:
            print(
                f"agents.{role_name}.config_file must be {expected_config_file!r}."
            )
            return 1
        if (
            not isinstance(role.get("description"), str)
            or not role["description"].strip()
        ):
            print(f"agents.{role_name}.description must be non-empty.")
            return 1

        agent = read_toml(f".codex/agents/{filename}")
        missing_fields = [
            field
            for field in ("developer_instructions",)
            if not isinstance(agent.get(field), str) or not agent[field].strip()
        ]
        if missing_fields:
            print(f"{filename} is missing required fields: {', '.join(missing_fields)}")
            return 1
        expected = EXPECTED_AGENT_SETTINGS[filename]
        actual = (
            agent.get("model"),
            agent.get("model_reasoning_effort"),
            agent.get("sandbox_mode"),
        )
        if actual != expected:
            print(
                f"{filename} must use model/effort/sandbox {expected}; found {actual}."
            )
            return 1

    print("Repository foundation and Codex harness are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
