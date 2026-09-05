from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping


Runner = Callable[..., subprocess.CompletedProcess[str]]
RSCRIPT_ENVIRONMENT_VARIABLE = "DATA_LENS_RSCRIPT"


def _version_key(path: Path) -> tuple[int, ...]:
    match = re.search(r"R-(\d+(?:\.\d+)*)", str(path), re.IGNORECASE)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def _candidate(value: str | os.PathLike[str] | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    path = Path(value).expanduser()
    if path.is_dir():
        names = ("Rscript.exe", "Rscript")
        roots = (path, path / "bin")
        for root in roots:
            for name in names:
                executable = root / name
                if executable.is_file():
                    return executable.resolve()
        return None
    return path.resolve() if path.is_file() else None


def discover_rscript(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    env = os.environ if environment is None else environment
    checked: list[dict[str, str]] = []

    for source, raw in (("explicit_argument", explicit), ("environment", env.get(RSCRIPT_ENVIRONMENT_VARIABLE))):
        if raw is None or not str(raw).strip():
            continue
        resolved = _candidate(raw)
        checked.append({"source": source, "value": str(raw), "status": "found" if resolved else "not_found"})
        if resolved:
            return {"available": True, "command": str(resolved), "source": source, "candidates_checked": checked}

    path_command = which("Rscript")
    if path_command:
        resolved = _candidate(path_command)
        checked.append({"source": "path", "value": path_command, "status": "found" if resolved else "not_found"})
        if resolved:
            return {"available": True, "command": str(resolved), "source": "path", "candidates_checked": checked}

    if os.name == "nt":
        roots: list[Path] = []
        for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
            value = env.get(key)
            if value:
                root = Path(value) / "R"
                if root not in roots:
                    roots.append(root)
        common: list[Path] = []
        for root in roots:
            common.extend(root.glob("R-*\\bin\\Rscript.exe"))
        for executable in sorted(common, key=lambda item: (_version_key(item), str(item)), reverse=True):
            checked.append({"source": "windows_common_install", "value": str(executable), "status": "found"})
            return {
                "available": True,
                "command": str(executable.resolve()),
                "source": "windows_common_install",
                "candidates_checked": checked,
            }

    return {
        "available": False,
        "command": str(explicit or env.get(RSCRIPT_ENVIRONMENT_VARIABLE) or "Rscript"),
        "source": "not_found",
        "candidates_checked": checked,
        "diagnostic": f"Set {RSCRIPT_ENVIRONMENT_VARIABLE} to an existing Rscript file or install R in a standard location.",
    }


def r_subprocess_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if environment is None else environment)
    if os.name == "nt":
        # Codex shells commonly export the POSIX locale C.UTF-8. Windows R does
        # not recognize it and silently falls back to the non-UTF-8 C locale.
        for key in ("LANG", "LC_ALL", "LC_CTYPE", "LC_COLLATE", "LC_MONETARY", "LC_TIME"):
            if env.get(key, "").strip().lower().replace("_", "-") in {"c.utf-8", "c.utf8"}:
                env.pop(key, None)
    return env


def probe_r_runtime(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    runner: Runner = subprocess.run,
    timeout: int = 10,
) -> dict[str, Any]:
    discovery = discover_rscript(explicit, environment=environment)
    payload: dict[str, Any] = {
        "contract_version": "data-lens-r-capability/1.0",
        "available": False,
        "command": discovery["command"],
        "discovery_source": discovery["source"],
        "auto_install": False,
        "candidates_checked": discovery["candidates_checked"],
    }
    if not discovery["available"]:
        payload["diagnostic"] = discovery["diagnostic"]
        return payload
    try:
        completed = runner(
            [discovery["command"], "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=r_subprocess_environment(environment),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        payload["diagnostic"] = f"Rscript probe failed: {type(exc).__name__}: {exc}"
        return payload
    if completed.returncode:
        payload["diagnostic"] = f"Rscript probe exited {completed.returncode}: {(completed.stderr or completed.stdout).strip()[:500]}"
        return payload
    payload["available"] = True
    payload["version"] = (completed.stdout or completed.stderr).splitlines()[0].strip()
    payload["utf8_locale_sanitized"] = os.name == "nt"
    return payload
