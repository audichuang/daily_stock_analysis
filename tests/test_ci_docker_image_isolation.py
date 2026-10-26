"""fork：共用 Docker daemon 上各次 CI 的映像與清理必須互相隔離。"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

from tests.test_ci_workflow_contract import _workflow


def _expand(value: str, context: dict[str, str]) -> str:
    return re.sub(r"\$\{\{\s*(.*?)\s*\}\}", lambda match: context[match[1]], value)


def _image_context(job: dict, run_id: int, attempt: int) -> tuple[str, dict, dict]:
    context = {"github.run_id": str(run_id), "github.run_attempt": str(attempt)}
    env = {key: _expand(value, context) for key, value in job.get("env", {}).items()}
    context.update({f"env.{key}": value for key, value in env.items()})
    build = next(step for step in job["steps"] if step.get("uses", "").startswith("docker/build-push-action@"))
    assert build["with"]["load"] == "true"
    return _expand(build["with"]["tags"], context), env, context


def test_image_tags_isolate_concurrent_runs_and_reruns():
    job = _workflow(".github/workflows/ci.yml")["jobs"]["docker-build"]
    tags = [_image_context(job, run_id, attempt)[0] for run_id, attempt in ((101, 1), (102, 1), (101, 2))]
    assert len(set(tags)) == 3, f"不同 run 或 attempt 共用了映像標籤：{tags}"


@pytest.mark.parametrize("failed_smoke", [None, 0, 1], ids=["success", "first-smoke-fails", "import-smoke-fails"])
def test_smokes_and_always_cleanup_only_use_the_current_image(tmp_path, failed_smoke):
    job = _workflow(".github/workflows/ci.yml")["jobs"]["docker-build"]
    steps = job["steps"]
    build_index = next(i for i, step in enumerate(steps) if step.get("uses", "").startswith("docker/build-push-action@"))
    smokes = [step for step in steps if "Docker smoke" in step.get("name", "")]
    assert len(smokes) == 2
    cleanups = [step for step in steps if step.get("if") == "always()"]
    assert len(cleanups) == 1, "映像清理必須在 smoke 失敗時也執行"
    cleanup = cleanups[0]
    assert all(build_index < steps.index(smoke) < steps.index(cleanup) for smoke in smokes)
    assert steps[-1] == cleanup

    images = tmp_path / "images"
    images.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "images = Path(os.environ['FAKE_DOCKER_IMAGES'])\n"
        "if args[:2] == ['run', '--rm']:\n"
        "    print((images / args[2]).read_text())\n"
        "    sys.exit(int(os.environ.get('FAKE_SMOKE_EXIT_CODE', '0')))\n"
        "elif args[:2] == ['image', 'rm'] and len(args) == 3:\n"
        "    (images / args[2]).unlink()\n"
        "elif args[:2] == ['image', 'prune']:\n"
        "    for image in images.iterdir():\n"
        "        image.unlink()\n"
        "else:\n"
        "    sys.exit('測試不支援的 Docker 指令')\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    # 先交錯完成兩個 run 與一次重跑的建置，再驗證各自的 smoke 與清理。
    runs = []
    for run_id, attempt in ((101, 1), (102, 1), (101, 2)):
        image, env, context = _image_context(job, run_id, attempt)
        identity = f"{run_id}/{attempt}"
        (images / image).write_text(identity, encoding="utf-8")
        runs.append((image, env, context, identity))
    unrelated = images / "unrelated:keep"
    unrelated.write_text("保留其他工作建立的映像", encoding="utf-8")

    for run_index, (image, env, context, identity) in enumerate(runs):
        shell_env = {
            **os.environ,
            **env,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_IMAGES": str(images),
        }

        def run_step(step):
            return subprocess.run(
                ["bash", "-e", "-o", "pipefail", "-c", _expand(step["run"], context)],
                env=shell_env,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )

        for index, smoke in enumerate(smokes):
            shell_env["FAKE_SMOKE_EXIT_CODE"] = "23" if index == failed_smoke else "0"
            result = run_step(smoke)
            assert result.stdout.strip() == identity, result.stderr
            assert result.returncode == (23 if index == failed_smoke else 0), result.stderr
            if result.returncode:
                break

        result = run_step(cleanup)
        assert result.returncode == 0, result.stderr
        assert not (images / image).exists(), "本次映像沒有清掉"
        assert unrelated.read_text(encoding="utf-8") == "保留其他工作建立的映像"
        for other_image, _, _, other_identity in runs[run_index + 1:]:
            assert (images / other_image).read_text(encoding="utf-8") == other_identity


def test_cleanup_tolerates_missing_image_and_keeps_other_runs(tmp_path):
    # build 失敗時本次映像不存在：清理步驟不能再多報一個紅，也不能動到別的 run 的映像。
    job = _workflow(".github/workflows/ci.yml")["jobs"]["docker-build"]
    cleanup = next(step for step in job["steps"] if step.get("if") == "always()")
    _, env, context = _image_context(job, 201, 1)
    other_image, _, _ = _image_context(job, 202, 1)

    images = tmp_path / "images"
    images.mkdir()
    (images / other_image).write_text("202/1", encoding="utf-8")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "images = Path(os.environ['FAKE_DOCKER_IMAGES'])\n"
        "if args[:2] == ['image', 'rm'] and len(args) == 3:\n"
        "    target = images / args[2]\n"
        "    if not target.exists():\n"
        "        sys.exit('Error: No such image: ' + args[2])\n"
        "    target.unlink()\n"
        "elif args[:2] == ['image', 'prune']:\n"
        "    for image in images.iterdir():\n"
        "        image.unlink()\n"
        "else:\n"
        "    sys.exit('測試不支援的 Docker 指令')\n",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", _expand(cleanup["run"], context)],
        env={
            **os.environ,
            **env,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
            "FAKE_DOCKER_IMAGES": str(images),
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (images / other_image).read_text(encoding="utf-8") == "202/1"
