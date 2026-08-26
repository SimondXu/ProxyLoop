#!/usr/bin/env python3
"""Validate the tracked repository foundation and Codex harness."""

import tomllib
from pathlib import Path

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
    "harness/status.toml",
    "harness/log/README.md",
    "harness/log/phase-04c-persistent-case-store.md",
    "harness/log/phase-04d-control-plane-operations.md",
    "harness/build/phase-00b-contracts.md",
    "harness/build/phase-01a-provider-simulator.md",
    "harness/build/phase-01b-simulator-benchmark.md",
    "harness/build/phase-02-data-factory.md",
    "harness/build/phase-03a0-fast-slow-architecture.md",
    "harness/build/phase-03a1-harness.md",
    "harness/build/phase-03a1-hosted-rerun.md",
    "harness/build/phase-03a1-evaluation-validity-smoke.md",
    "harness/build/phase-03b-qwen-qlora-smoke.md",
    "harness/build/phase-04a-thin-agent-runtime.md",
    "harness/build/phase-04b-model-backed-runtime.md",
    "harness/build/phase-04c-persistent-case-store.md",
    "harness/build/phase-04d-control-plane-operations.md",
    "harness/context/README.md",
    "harness/context/phase-00b-preflight.md",
    "harness/context/phase-01a-preflight.md",
    "harness/context/phase-01b-preflight.md",
    "harness/context/phase-02-preflight.md",
    "harness/context/phase-03a0-preflight.md",
    "harness/context/phase-03a1-preflight.md",
    "harness/context/phase-03a1-hosted-rerun-preflight.md",
    "harness/context/phase-03a1-evaluation-validity-smoke-preflight.md",
    "harness/context/phase-03b-readiness-preflight.md",
    "harness/context/phase-04a-preflight.md",
    "harness/context/phase-04b-preflight.md",
    "harness/context/phase-04c-preflight.md",
    "harness/context/phase-04d-preflight.md",
    "harness/code_review",
    "harness/code_review/phase-02.md",
    "harness/code_review/phase-03a0.md",
    "harness/code_review/phase-03a1-harness.md",
    "harness/code_review/phase-03a1-hosted-rerun-pre-provider.md",
    "harness/code_review/phase-03a1-hosted-rerun.md",
    "harness/code_review/phase-04a-thin-agent-runtime.md",
    "harness/code_review/phase-04b-model-backed-runtime.md",
    "harness/code_review/phase-04c-persistent-case-store.md",
    "harness/code_review/phase-04d-control-plane-operations.md",
    "harness/code_review/phase-03b-readiness-stage-0a.md",
    "harness/code_review/phase-03b-source-qualification-agent-review.md",
    "harness/build-log.md",
    "docs/README.md",
    "docs/specs/2026-08-21-telecom-bill-optimization-agent.md",
    "docs/architecture.md",
    "docs/decisions/2026-08-21-monorepo.md",
    "docs/decisions/2026-08-22-implementation-defaults.md",
    "docs/decisions/2026-08-22-contract-wire-format.md",
    "docs/decisions/2026-08-23-fast-slow-orchestration.md",
    "docs/planning/initial-project-plan.md",
    "docs/planning/progress.md",
    "docs/research/foundations.md",
    "apps/web",
    "runtime/packages/contracts/pyproject.toml",
    "runtime/packages/contracts/src/proxyloop_contracts/py.typed",
    "runtime/packages/agent_core/pyproject.toml",
    "runtime/packages/agent_core/src/proxyloop_agent_core/py.typed",
    "runtime/packages/provider_simulator/pyproject.toml",
    "runtime/packages/provider_simulator/src/proxyloop_provider_simulator/py.typed",
    "runtime/packages/telecom_domain/pyproject.toml",
    "runtime/packages/telecom_domain/src/proxyloop_telecom_domain/py.typed",
    "runtime/packages/openai_adapter/pyproject.toml",
    "runtime/packages/openai_adapter/src/proxyloop_openai_adapter/py.typed",
    "runtime/services/api/pyproject.toml",
    "runtime/services/api/src/proxyloop_api/server.py",
    "ml/pyproject.toml",
    "ml/uv.lock",
    "ml/data_pipeline",
    "ml/data_pipeline/src/proxyloop_data_pipeline/py.typed",
    "ml/evaluation/src/proxyloop_evaluation/hosted_rerun.py",
    "ml/evaluation/src/proxyloop_evaluation/validity_smoke.py",
    "voice/worker",
    "contracts/jsonschema/proxyloop-contracts.schema.json",
    "contracts/typescript/proxyloop-contracts.d.ts",
    "contracts/typescript/valid-case.fixture.ts",
    "contracts/typescript/tsconfig.json",
    "data/manifests",
    "data/manifests/phase-01b-split.json",
    "data/manifests/phase-01b-ceiling-report.json",
    "data/manifests/phase-02-pilot-manifest.json",
    "data/manifests/phase-02-quarantine.json",
    "data/manifests/phase-02-quality-report.json",
    "data/manifests/phase-03a1-manifest.json",
    "data/manifests/phase-03a1-episodes.json",
    "data/manifests/phase-03a1-ceiling-report.json",
    "data/evaluation/phase-03a1-r4-hosted-rerun-report.json",
    "data/evaluation/phase-03a1-r5-validity-smoke-report.json",
    "data/schemas/normalized-trajectory-v1.schema.json",
    "data/samples/phase-02-review-sample.json",
    "docs/data/phase-02-annotation-guide.md",
    "infra/compose",
    "tests/contract",
    "tests/integration/test_phase_01a_simulator.py",
    "tests/integration/test_phase_01b_observation.py",
    "tests/integration/test_phase_01b_environment.py",
    "tests/integration/test_phase_01b_benchmark.py",
    "tests/contract/test_phase_02_architecture.py",
    "tests/contract/test_phase_03a0_architecture.py",
    "tests/contract/test_phase_03a1_architecture.py",
    "tests/contract/test_phase_03a1_hosted_rerun_architecture.py",
    "tests/integration/test_phase_02_artifacts.py",
    "tests/fixtures/case.valid.json",
    "scripts/run_phase_03a1_hosted_rerun.py",
    "scripts/run_phase_03a1_validity_smoke.py",
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

MAX_PROJECT_AGENTS_BYTES = 12_000
MIN_AGENT_CONCURRENCY = 4
MAX_AGENT_CONCURRENCY = 8

REQUIRED_ROUTING_MARKERS = {
    "AGENTS.md": (
        "## Adaptive Delegation",
        "## Skill Routing",
        'fork_turns="none"',
        "safety ceiling",
    ),
    "PROMPTS.md": (
        "## Decide Delegation",
        "## Delegate Exploration",
        "ceiling, not a target",
    ),
}

REQUIRED_EXPLORER_MARKERS = (
    "minimal evidence set",
    "Sol must read",
    "Escalation needed",
)


def read_toml(relative_path: str) -> dict[str, object]:
    with (ROOT / relative_path).open("rb") as config_file:
        return tomllib.load(config_file)


def validate_harness_status(
    status: dict[str, object], *, root: Path = ROOT
) -> str | None:
    """Return a validation error for the canonical Harness status, if any."""
    schema_version = status.get("schema_version")
    if (
        not isinstance(schema_version, int)
        or isinstance(schema_version, bool)
        or schema_version != 1
    ):
        return "harness/status.toml must use schema_version = 1."

    phase_state = status.get("product_phase_state")
    if phase_state not in {
        "idle",
        "prepared",
        "in_progress",
        "blocked",
        "at_review",
        "complete",
    }:
        return "harness/status.toml has an invalid product_phase_state."

    active_phase = status.get("active_product_phase")
    active_contract = status.get("active_contract")
    next_phase_authorized = status.get("next_phase_authorized")
    if not isinstance(active_phase, str) or not isinstance(active_contract, str):
        return "harness/status.toml active phase and contract must be strings."
    if not isinstance(next_phase_authorized, bool):
        return "harness/status.toml next_phase_authorized must be a boolean."

    if phase_state == "idle":
        if active_phase or active_contract or next_phase_authorized:
            return (
                "An idle harness status cannot activate a phase, contract, "
                "or next phase."
            )
        return None

    if not active_phase.strip():
        return "A non-idle harness status must name active_product_phase."
    if not active_contract.strip():
        return "A non-idle harness status must name active_contract."

    contract_path = Path(active_contract)
    if (
        contract_path.is_absolute()
        or contract_path.parts[:2] != ("harness", "build")
        or contract_path.suffix != ".md"
        or ".." in contract_path.parts
    ):
        return "active_contract must be a Markdown file under harness/build/."
    contract_candidate = root / contract_path
    try:
        resolved_contract = contract_candidate.resolve(strict=True)
        resolved_build_root = (root / "harness/build").resolve(strict=True)
    except OSError:
        return f"active_contract does not exist: {active_contract}."
    if not resolved_contract.is_relative_to(resolved_build_root):
        return "active_contract must resolve within harness/build/."
    if not resolved_contract.is_file():
        return f"active_contract is not a file: {active_contract}."
    return None


def main() -> int:
    missing = [path for path in REQUIRED_PATHS if not (ROOT / path).exists()]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    if missing:
        print("Missing required paths:", *missing, sep="\n- ")
        return 1
    if not readme.startswith("# ProxyLoop\n"):
        print("README.md must identify the project as ProxyLoop.")
        return 1

    agents_document = (ROOT / "AGENTS.md").read_bytes()
    if len(agents_document) > MAX_PROJECT_AGENTS_BYTES:
        print(
            "AGENTS.md must keep durable instructions under "
            f"{MAX_PROJECT_AGENTS_BYTES} bytes; found {len(agents_document)}."
        )
        return 1

    for relative_path, markers in REQUIRED_ROUTING_MARKERS.items():
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        missing_markers = [marker for marker in markers if marker not in content]
        if missing_markers:
            print(
                f"{relative_path} is missing required token-routing guidance: "
                f"{missing_markers}."
            )
            return 1

    codex_config = read_toml(".codex/config.toml")
    if codex_config.get("model") != "gpt-5.6-sol":
        print(".codex/config.toml must keep Sol as the root orchestrator model.")
        return 1

    agents_config = codex_config.get("agents")
    if not isinstance(agents_config, dict):
        print(".codex/config.toml must define an [agents] table.")
        return 1
    concurrency = agents_config.get("max_concurrent_threads_per_session")
    if (
        not isinstance(concurrency, int)
        or isinstance(concurrency, bool)
        or not MIN_AGENT_CONCURRENCY <= concurrency <= MAX_AGENT_CONCURRENCY
    ):
        print(
            "Codex subagent concurrency must be a safety ceiling between "
            f"{MIN_AGENT_CONCURRENCY} and {MAX_AGENT_CONCURRENCY}."
        )
        return 1

    status_error = validate_harness_status(read_toml("harness/status.toml"))
    if status_error:
        print(status_error)
        return 1

    for filename in AGENT_CONFIGS:
        role_name = Path(filename).stem
        role = agents_config.get(role_name)
        if not isinstance(role, dict):
            print(f".codex/config.toml must declare [agents.{role_name}].")
            return 1
        expected_config_file = f"agents/{filename}"
        if role.get("config_file") != expected_config_file:
            print(f"agents.{role_name}.config_file must be {expected_config_file!r}.")
            return 1
        if (
            not isinstance(role.get("description"), str)
            or not role["description"].strip()
        ):
            print(f"agents.{role_name}.description must be non-empty.")
            return 1

        agent = read_toml(f".codex/agents/{filename}")
        if agent.get("name") != role_name:
            print(f"{filename} must declare name = {role_name!r}.")
            return 1
        agent_description = agent.get("description")
        if not isinstance(agent_description, str) or not agent_description.strip():
            print(f"{filename} is missing required field: description")
            return 1
        instructions = agent.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            print(f"{filename} is missing required field: developer_instructions")
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
        if filename == "explorer.toml":
            missing_markers = [
                marker
                for marker in REQUIRED_EXPLORER_MARKERS
                if marker not in instructions
            ]
            if missing_markers:
                print(
                    "explorer.toml is missing required evidence-card guidance: "
                    f"{missing_markers}."
                )
                return 1

    print("Repository foundation and Codex harness are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
