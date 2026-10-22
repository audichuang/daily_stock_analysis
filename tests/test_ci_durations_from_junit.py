from __future__ import annotations

from pathlib import Path

from scripts.ci_durations_from_junit import file_durations


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
