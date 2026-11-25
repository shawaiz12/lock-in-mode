"""Running the API on a hosting platform (ADR 0028).

The encryption setting is checked for real: a child process with POSTGRES_SSLMODE set
connects to the test Postgres. The child trusts NO certificates (an empty trust store),
so "verify-full" must FAIL against any test Postgres (no TLS, or a certificate it can't
trust), while "disable" works. If a code path forgot the setting, it would connect anyway
and the test would catch it.
"""

import os
import shutil
import ssl
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from lock_in_mode_api.core.config import Settings, settings

BACKEND = Path(__file__).resolve().parents[2]

CONNECT_WITH_THE_APP_ENGINE = """
import asyncio
from sqlalchemy import text
from lock_in_mode_api.core.db import engine

async def main() -> None:
    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))
    await engine.dispose()

asyncio.run(main())
"""


def _run(args: list[str], sslmode: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "POSTGRES_SSLMODE": sslmode,
        # Python reads its trusted certificates from these: point both at nothing.
        "SSL_CERT_FILE": str(tmp_path / "no-certificates.pem"),
        "SSL_CERT_DIR": str(tmp_path),
    }
    return subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60
    )


def _looks_like_a_tls_failure(result: subprocess.CompletedProcess[str]) -> bool:
    output = (result.stdout + result.stderr).lower()
    return result.returncode != 0 and ("ssl" in output or "certificate" in output)


@pytest.mark.parametrize(
    "args",
    [["-c", CONNECT_WITH_THE_APP_ENGINE], ["-m", "alembic", "current"]],
    ids=["app-engine", "migrations"],
)
def test_the_sslmode_setting_reaches_every_connection(args: list[str], tmp_path: Path) -> None:
    assert _run(args, "disable", tmp_path).returncode == 0

    assert _looks_like_a_tls_failure(_run(args, "verify-full", tmp_path))


def test_verify_full_checks_the_certificate_and_the_host_name() -> None:
    ssl_option = Settings(postgres_sslmode="verify-full").database_connect_args["ssl"]

    assert isinstance(ssl_option, ssl.SSLContext)
    assert ssl_option.verify_mode == ssl.CERT_REQUIRED
    assert ssl_option.check_hostname is True


def test_local_defaults_need_no_tls_and_no_proxy() -> None:
    assert settings.database_connect_args == {"timeout": 5, "ssl": "prefer"}
    assert settings.trusted_proxy_hops == 0
    assert settings.app_version == "dev"


@pytest.mark.parametrize(
    "bad",
    [{"postgres_sslmode": "on"}, {"trusted_proxy_hops": -1}, {"trusted_proxy_hops": 6}],
    ids=["unknown-sslmode", "negative-hops", "too-many-hops"],
)
def test_bad_hosting_settings_stop_the_app_from_starting(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)  # type: ignore[arg-type]


# --- A database's own certificate authority (ADR 0030) -----------------------------------
# Supabase signs its certificates with its own CA. POSTGRES_SSL_ROOT_CERT makes
# verify-full trust ONLY that CA. TEST_CA is a CA made for these tests: no real server
# is signed by it, so trusting only it must refuse every server.

TEST_CA = """\
-----BEGIN CERTIFICATE-----
MIIDITCCAgmgAwIBAgIUIzSDMz6h+SnlevTrK/Y7/r+U0LUwDQYJKoZIhvcNAQEL
BQAwHzEdMBsGA1UEAwwUTG9jayBJbiBNb2RlIFRlc3QgQ0EwIBcNMjYxMTI1MDUz
NjI0WhgPMjEyNjExMDEwNTM2MjRaMB8xHTAbBgNVBAMMFExvY2sgSW4gTW9kZSBU
ZXN0IENBMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAyXHn6762Q3vp
KU+jNWkGeV2JrrhjCesPGLuIwwMb1yzIxJZmJL4v74/HWa0VZ3qtx26hKB9L9B80
pIpzbYT3tAtQgtvdUQfJ/kCx0Fy8axLF5owvBbM28hs8SyuMKI/Ovpp0k8Oiwgfp
VLEpYS/51rEVV9dZ+hbKhWZ7dvHuawcn+PBK4qj3i2a4mpAiG7UVtTYD5V2+Wt0p
GKXswOxAY3lZdrv2ZMI3J2B4vhRIf3jgvQLYGkQaZdumTLk+Pcoqd3FKRhdU4gTr
1frKUYRjUjNDaLOwyhtsxvk6uyte+JuYR991lsLg3tIo4kXwDgOEM61R/ZDOkvMH
X9BtrvAUNwIDAQABo1MwUTAdBgNVHQ4EFgQUss4IbjIQIaBmUIwxP3yqlEBphT8w
HwYDVR0jBBgwFoAUss4IbjIQIaBmUIwxP3yqlEBphT8wDwYDVR0TAQH/BAUwAwEB
/zANBgkqhkiG9w0BAQsFAAOCAQEALQzh4dWcPEeGc07GoVfkLrJEgsNdyDVU+JB/
9jtd1fkkjJO0TD0G5ron7IheKCuS1R4r+iyouM5cNI4acuvb+CL1giociuE/kqI0
gMdMZSaUTiELcvPwnfl1E9Mzg8U9fBLxcgki+h4yYH9V2ijUbL2wAW5Ia37q9FcS
zMULb3QTDf4dcKscM9BA9FXraSc+FpEJ/1Jn2NW91GZvBeCw0nhAw2e5naVyBJLb
3kMrZqerwG/jU+usX5GlTebKjmCvum0X551+IDE64UqVNJoBf8c223ZnUsyKg7rQ
ETa8Sw1VO/hnK8695eMsZ3/EKizz+mfrQlAsQNrYWpOGZnQGuQ==
-----END CERTIFICATE-----
"""


def test_a_root_cert_is_the_only_certificate_trusted() -> None:
    context = Settings(
        postgres_sslmode="verify-full", postgres_ssl_root_cert=TEST_CA
    ).database_connect_args["ssl"]

    assert isinstance(context, ssl.SSLContext)
    subjects = [ca["subject"] for ca in context.get_ca_certs()]
    assert subjects == [((("commonName", "Lock In Mode Test CA"),),)]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_a_root_cert_pasted_on_one_line_works_too() -> None:
    # Some dashboards only take one-line values: "-----BEGIN…-----\\nMIIB…\\n-----END…".
    one_line = TEST_CA.strip().replace("\n", "\\n")

    assert (
        Settings(
            postgres_sslmode="verify-full", postgres_ssl_root_cert=one_line
        ).postgres_ssl_root_cert
        == TEST_CA.strip()
    )


def test_a_blank_root_cert_means_the_system_certificates() -> None:
    assert (
        Settings(postgres_sslmode="verify-full", postgres_ssl_root_cert="  ").postgres_ssl_root_cert
        is None
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"postgres_sslmode": "verify-full", "postgres_ssl_root_cert": "not a certificate"},
        # Any other mode would never check it: refuse instead of a false sense of safety.
        {"postgres_sslmode": "require", "postgres_ssl_root_cert": TEST_CA},
        {"postgres_ssl_root_cert": TEST_CA},
    ],
    ids=["not-a-certificate", "with-require", "with-the-default-mode"],
)
def test_a_root_cert_that_cannot_work_stops_the_app_from_starting(
    bad: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Settings(**bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "args",
    [["-c", CONNECT_WITH_THE_APP_ENGINE], ["-m", "alembic", "current"]],
    ids=["app-engine", "migrations"],
)
def test_every_connection_trusts_only_the_root_cert(args: list[str]) -> None:
    # The system's own certificates stay in place here: even a test Postgres that the
    # system trusts must be refused, because it isn't signed by TEST_CA.
    env = {**os.environ, "POSTGRES_SSLMODE": "verify-full", "POSTGRES_SSL_ROOT_CERT": TEST_CA}
    result = subprocess.run(
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60
    )

    assert _looks_like_a_tls_failure(result)


# --- start-production.sh -------------------------------------------------------------
# The real tools are swapped for tiny stand-ins that write their name to a log, so the
# test sees the order of the steps and whether the API starts, without starting it.

needs_sh = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX shell")


def _stand_ins(tmp_path: Path, failing: str | None = None) -> tuple[dict[str, str], Path]:
    bin_dir, log = tmp_path / "bin", tmp_path / "calls.log"
    bin_dir.mkdir()
    for tool in ("alembic", "python", "uvicorn"):
        exit_code = 1 if tool == failing else 0
        script = bin_dir / tool
        script.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit {exit_code}\n')
        script.chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    return env, log


def _start(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(BACKEND / "start-production.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


@needs_sh
def test_start_migrates_then_seeds_then_runs_the_api(tmp_path: Path) -> None:
    env, log = _stand_ins(tmp_path)

    result = _start({**env, "PORT": "9000"})

    assert result.returncode == 0
    assert log.read_text().splitlines() == [
        "alembic upgrade head",
        "python -m lock_in_mode_api.seed",
        "uvicorn lock_in_mode_api.main:app --host 0.0.0.0 --port 9000",
    ]


@needs_sh
def test_start_uses_port_8000_when_the_platform_sets_none(tmp_path: Path) -> None:
    env, log = _stand_ins(tmp_path)

    assert _start(env).returncode == 0
    assert log.read_text().splitlines()[-1].endswith("--port 8000")


@needs_sh
@pytest.mark.parametrize("failing", ["alembic", "python"])
def test_a_failed_step_never_starts_the_api(tmp_path: Path, failing: str) -> None:
    env, log = _stand_ins(tmp_path, failing=failing)

    result = _start(env)

    assert result.returncode != 0
    assert not any(line.startswith("uvicorn") for line in log.read_text().splitlines())
