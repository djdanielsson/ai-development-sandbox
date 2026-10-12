#!/usr/bin/env python3
"""Receive launcher credentials on stdin and store them in the host tmpfs."""

from __future__ import annotations

import os
import sys
from pathlib import Path


NAMES = (
    "cursor_api_key",
    "github_token",
    "ssh_key_b64",
    "gpg_key_b64",
    "git_name",
    "git_email",
)


def main() -> int:
    values = sys.stdin.buffer.read().splitlines()
    if len(values) != len(NAMES):
        print("Expected six newline-delimited credential values.", file=sys.stderr)
        return 2

    directory = Path(os.environ.get("OMNIGENT_CREDENTIALS_DIR", "/run/omnigent-secrets"))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)

    for name, value in zip(NAMES, values, strict=True):
        target = directory / name
        temporary = directory / f".{name}.{os.getpid()}"
        try:
            with temporary.open("wb") as output:
                os.chmod(temporary, 0o600)
                output.write(value)
            os.replace(temporary, target)
            os.chmod(target, 0o600)
        finally:
            temporary.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
