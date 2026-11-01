from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci_test_shard import (
    REPO_ROOT,
    TEST_ROOTS,
    discover_test_files,
    load_durations,
    partition_test_files,
)


def test_shard_roots_match_the_pytest_testpaths_contract() -> None:
    """漏一个 root 的分片看起来跟通过的分片一模一样——不报错、不变红、只是少跑。

    本 fork 的 `market_data/tests` 是台股 DB 覆盖，上游没有；上游的分片脚本把
    `tests` 写死在 discover_test_files 里，合上游时会静默把它丢掉。
    """
    import configparser

    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "setup.cfg")
    testpaths = parser["tool:pytest"]["testpaths"].split()

    assert sorted(TEST_ROOTS) == sorted(testpaths)
    discovered = discover_test_files()
    for root in testpaths:
        assert any(f.startswith(f"{root}/") for f in discovered), f"{root} 一个档案都没被分片收到"


def test_real_ci_shards_are_complete_disjoint_and_balanced() -> None:
    test_files = discover_test_files()
    durations = load_durations()
    # fork：片數要和 ci.yml 的 PYTEST_SPLITS 一致（4，跑在自架 runner，見 docs/ci-self-hosted-runner.md）。
    groups, totals = partition_test_files(test_files, durations, 4)

    flattened = [test_file for group in groups for test_file in group]
    assert sorted(flattened) == test_files
    assert len(flattened) == len(set(flattened))
    assert all(group == sorted(group) for group in groups)
    # 分片以整個檔為單位：單一檔比平均每片還長時（test_agent_active_stock_integration
    # 約 360 秒、全部約 1018 秒），它只能獨占一片。這是唯一允許的不平衡，其餘各片仍要齊平。
    largest = max(durations[test_file] for test_file in test_files if test_file in durations)
    oversized = [
        index
        for index, group in enumerate(groups)
        if len(group) == 1 and durations.get(group[0]) == largest
    ]
    balanced = [total for index, total in enumerate(totals) if index not in oversized]
    assert len(oversized) <= 1
    assert max(balanced) - min(balanced) < 1.0
    assert max(totals) == pytest.approx(max(largest, max(balanced)))


def test_new_test_file_uses_fallback_without_being_dropped() -> None:
    groups, totals = partition_test_files(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_new.py"],
        {"tests/test_a.py": 3.0, "tests/test_b.py": 1.0},
        2,
    )

    assert sorted(test_file for group in groups for test_file in group) == [
        "tests/test_a.py",
        "tests/test_b.py",
        "tests/test_new.py",
    ]
    assert totals == pytest.approx([3.0, 3.0])


def test_partition_accounts_for_first_shard_preflight_cost() -> None:
    groups, totals = partition_test_files(
        ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"],
        {
            "tests/test_a.py": 4.0,
            "tests/test_b.py": 4.0,
            "tests/test_c.py": 2.0,
            "tests/test_d.py": 2.0,
        },
        2,
        initial_totals=[4.0, 0.0],
    )

    assert groups == [
        ["tests/test_b.py"],
        ["tests/test_a.py", "tests/test_c.py", "tests/test_d.py"],
    ]
    assert totals == pytest.approx([8.0, 8.0])


@pytest.mark.parametrize("splits", [0, -1])
def test_invalid_split_count_is_rejected(splits: int) -> None:
    with pytest.raises(ValueError, match="splits must be positive"):
        partition_test_files(["tests/test_a.py"], {}, splits)


def test_invalid_initial_totals_are_rejected() -> None:
    with pytest.raises(ValueError, match="initial_totals"):
        partition_test_files(["tests/test_a.py"], {}, 2, initial_totals=[0.0])


def test_duration_file_tracks_current_baseline_and_valid_paths() -> None:
    duration_path = REPO_ROOT / ".github" / "ci-test-durations.json"
    assert duration_path.is_file()
    durations = load_durations(duration_path)

    assert len(durations) >= 250
    assert all((REPO_ROOT / Path(test_file)).is_file() for test_file in durations)
    assert max(durations.values()) >= 30
