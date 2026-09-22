"""Cross-platform, credential-free Phase 1 verification."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: Sequence[str]) -> None:
    print(f"> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603


def format_check() -> None:
    run(["ruff", "format", "--check", "."])


def lint() -> None:
    run(["ruff", "check", "."])


def type_check() -> None:
    run(["mypy"])


def test_unit() -> None:
    # Isolated workspace-local temporary paths avoid cross-account Windows temp ACLs.
    artifacts = ROOT / ".test-artifacts"
    artifacts.mkdir(exist_ok=True)
    base = tempfile.mkdtemp(prefix="pytest-", dir=artifacts)
    run(["pytest", "tests/unit", "--basetemp", base, "-p", "no:cacheprovider"])


def test_agent() -> None:
    run(["uv", "run", "--directory", "src/agent", "--frozen", "pytest"])


def test_web() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("Node.js and npm are required for the Control Room checks")
    run([npm, "--prefix", "src/web", "run", "verify"])


def schema_check() -> None:
    run([sys.executable, "scripts/export_schemas.py", "--check"])


def terraform_format_check() -> None:
    run(["terraform", "fmt", "-check", "-recursive", "infra"])


def assert_no_deployment_state(paths: Sequence[str]) -> None:
    for path in paths:
        normalized = path.replace("\\", "/")
        if ".tfstate" in Path(normalized).name or (
            normalized.startswith(".azure/")
            and normalized not in {".azure/.gitignore", ".azure/deployment-plan.md"}
        ):
            raise ValueError("deployment state/environment must never be tracked")


def security_check() -> None:
    # Deployment state contains provider-generated credentials even with key auth disabled.
    # Exclude local state from source scanning, but fail if anyone stages it for commit.
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is required to verify deployment state stays untracked")
    tracked = subprocess.run(  # noqa: S603
        [git, "-c", f"safe.directory={ROOT.as_posix()}", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert_no_deployment_state(tracked.stdout.split("\0"))
    command = [
        "detect-secrets",
        "scan",
        "--all-files",
        "--exclude-files",
        (
            r"(^|[\\/])(\.git|\.venv|\.uv-cache|\.test-artifacts|\.terraform|\.mypy_cache|"
            r"\.pytest_cache|\.ruff_cache|\.publish|node_modules|dist|test-results)([\\/]|$)|uv\.lock$|package-lock\.json$"
            r"|(^|[\\/])\.azure[\\/](?!deployment-plan\.md$|\.gitignore$)"
        ),
    ]
    print(f"> {' '.join(command)}", flush=True)
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    findings = result.get("results", {})
    if findings:
        print(json.dumps(findings, indent=2))
        raise SystemExit("potential secrets detected")
    print("No potential secrets detected")


TASKS = {
    "format-check": format_check,
    "lint": lint,
    "type-check": type_check,
    "test-unit": test_unit,
    "test-agent": test_agent,
    "test-web": test_web,
    "schema-check": schema_check,
    "terraform-format-check": terraform_format_check,
    "security-check": security_check,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=[*TASKS, "verify"])
    args = parser.parse_args()

    if args.task == "verify":
        for task_name in (
            "format-check",
            "lint",
            "type-check",
            "schema-check",
            "terraform-format-check",
            "test-unit",
            "test-agent",
            "test-web",
            "security-check",
        ):
            print(f"\n== {task_name} ==", flush=True)
            TASKS[task_name]()
    else:
        TASKS[args.task]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
