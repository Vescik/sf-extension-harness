"""Pure validation for the ADO scope used by onboarding and the safety hook.

Keep the dependency-free Node launcher's validation in sync. Neither validator reads
environment variables, resolves credentials, or contacts Azure DevOps.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


PLACEHOLDERS = frozenset({
    "todo", "tbd", "changeme", "replace_me", "your-org-slug", "your-project-name",
})
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def ado_config_error(config: Any) -> str | None:
    """Return a safe actionable error, without including configured values."""
    def error(key: str, reason: str) -> str:
        return f"ADO configuration error: {key} {reason}. Set it in config/harness.local.json."

    if not isinstance(config, dict) or not isinstance(config.get("ado"), dict):
        return error("ado", "must be an object")
    ado = config["ado"]
    for key in ("organization", "project"):
        value = ado.get(key)
        if not isinstance(value, str) or not value.strip():
            return error(f"ado.{key}", "must be a nonempty string")
        if value != value.strip() or CONTROL.search(value):
            return error(f"ado.{key}", "must not contain edge whitespace or control characters")
        if "<" in value or ">" in value or value.lower() in PLACEHOLDERS:
            return error(f"ado.{key}", "must not be a placeholder")
    org = ado["organization"]
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", org) is None:
        return error("ado.organization", "must be an organization slug")
    if any(char in ado["project"] for char in "/\\"):
        return error("ado.project", "must be a project name or ID, not a URL or path")

    origins = ado.get("allowedHttpsOrigins")
    expected = f"https://dev.azure.com/{org}"
    if not isinstance(origins, list) or not origins:
        return error("ado.allowedHttpsOrigins", "must be a nonempty array")
    if any(not isinstance(origin, str) for origin in origins):
        return error("ado.allowedHttpsOrigins", "must contain HTTPS strings")
    if len(set(origins)) != len(origins) or expected not in origins:
        return error("ado.allowedHttpsOrigins", "must include the configured organization without duplicates")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            valid = (origin == origin.strip() and not CONTROL.search(origin)
                     and origin.startswith("https://") and not parsed.netloc.endswith(":")
                     and not any(c in origin for c in "\\<>?#")
                     and not any(c.isspace() for c in origin)
                     and parsed.scheme == "https" and parsed.hostname
                     and parsed.username is None and parsed.password is None
                     and parsed.port is None and not parsed.query and not parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            return error("ado.allowedHttpsOrigins", "must contain valid HTTPS prefixes without credentials, ports, queries or fragments")
        if ((parsed.hostname == "dev.azure.com" and origin != expected)
                or parsed.hostname.endswith(".dev.azure.com")
                or parsed.hostname == "visualstudio.com"
                or parsed.hostname.endswith(".visualstudio.com")):
            return error("ado.allowedHttpsOrigins", "contains an unconfigured ADO organization or alias")
    return None
