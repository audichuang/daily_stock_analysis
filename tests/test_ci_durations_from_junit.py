from __future__ import annotations

import json
from pathlib import Path

from scripts.ci_durations_from_junit import file_durations
from scripts.ci_test_shard import load_durations


def test_file_durations_sums_cases_per_module_across_reports(tmp_path: Path) -> None:
    (tmp_path / "tests" / "pkg").mkdir(parents=True)
    (tmp_path / "tests" / "test_a.py").write_text("")
    (tmp_path / "tests" / "pkg" / "test_b.py").write_text("")
    shard1 = tmp_path / "s1.xml"
    shard1.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.test_a" name="t1" time="1.5"/>'
        '<testcase classname="tests.test_a.TestX" name="t2" time="2.0"/>'
        '<testcase classname="tests.pkg.test_b.TestY" name="t3" time="0.25"/>'
        '<testcase classname="tests.test_gone" name="t4" time="9"/>'
        '</testsuite></testsuites>'
    )
    shard2 = tmp_path / "s2.xml"
    shard2.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.test_a" name="t5" time="0.5"/>'
        '</testsuite></testsuites>'
    )

    assert file_durations([shard1, shard2], tmp_path) == {
        "tests/pkg/test_b.py": 0.25,
        "tests/test_a.py": 4.0,
    }


def test_near_zero_module_is_floored_so_the_shard_loader_accepts_it(tmp_path: Path) -> None:
    """快機器上整個檔加總 < 0.0005 秒時不能寫成 0.0：分片載入器只收 > 0。"""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fast.py").write_text("")
    (tmp_path / "tests" / "test_slow.py").write_text("")
    report = tmp_path / "s.xml"
    report.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.test_fast" name="t1" time="0.0001"/>'
        '<testcase classname="tests.test_slow" name="t2" time="1.2345"/>'
        '</testsuite></testsuites>'
    )

    durations = file_durations([report], tmp_path)

    assert durations == {"tests/test_fast.py": 0.001, "tests/test_slow.py": 1.234}
    payload = tmp_path / "durations.json"
    payload.write_text(json.dumps({"schema_version": 1, "durations": durations}))
    assert load_durations(payload)["tests/test_fast.py"] == 0.001
