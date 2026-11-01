"""CardDemo's COBSWAIT as a JCL step, shaped like its WAITSTEP job: the ACCEPT reads the step's in-stream SYSIN, not another in-stream DD, and MVSWAIT waits that long."""

from __future__ import annotations

from pathlib import Path

from tests.integration.test_cobswait_plain import built_cobswait_package, timed_run


def _env_toml(tmp_path: Path, package: Path, interval: str) -> Path:
    job = tmp_path / f"WAIT{interval}.jcl"
    job.write_text(
        "//WAITSTEP JOB 'WAIT STEP',CLASS=A\n"
        "//WAIT     EXEC PGM=COBSWAIT\n"
        "//SYSOUT   DD SYSOUT=*\n"
        "//CARDS    DD *\n"
        "00000000\n"
        "/*\n"
        "//SYSIN    DD *\n"
        f"{interval}      VALUE IN CENTISECONDS\n"
        "/*\n"
    )
    env = tmp_path / f"env{interval}.toml"
    env.write_text(
        f'package = "{package}"\n[paths]\nsystem = "{tmp_path / "system"}"\n'
        f'[jcl]\njob = "{job}"\n'
    )
    return env


def test_cobswait_step_waits_for_the_interval_its_sysin_supplies(
    tmp_path: Path, carddemo_home: Path
) -> None:
    package = built_cobswait_package(tmp_path, carddemo_home)

    (no_wait, no_wait_secs), (wait, wait_secs) = (
        timed_run(_env_toml(tmp_path, package, "00000000"), ""),
        timed_run(_env_toml(tmp_path, package, "00000300"), ""),
    )

    assert (no_wait, wait, wait_secs - no_wait_secs >= 2.5) == (
        (0, ["WAIT: RC=0"], ""),
        (0, ["WAIT: RC=0"], ""),
        True,
    )
