"""Tests that dataset directories, file names and CLI arguments containing spaces are
handled correctly when executing commands (and via the pipeline-entrypoint CLI)"""

import typing as ty
from functools import reduce
from operator import mul
from pathlib import Path
import pytest
import yaml
from fileformats.text import Plain as PlainText, TextFile
from frametree.core.frameset import FrameSet
from frametree.core.store import Store
from frametree.testing import TestAxes
from frametree.testing.blueprint import (
    TestDatasetBlueprint,
    FileSetEntryBlueprint as FileBP,
)
from pydra2app.core.cli import pipeline_entrypoint
from pydra2app.core.command.base import ContainerCommand
from pydra2app.core.image import App
from frametree.file_system import FileSystem


@pytest.fixture
def spaced_dataset_blueprint() -> TestDatasetBlueprint:
    return TestDatasetBlueprint(
        hierarchy=["abcd"],
        axes=TestAxes,
        dim_lengths=[1, 1, 1, 1],
        entries=[
            FileBP(path="file 1", datatype=PlainText, filenames=["file 1.txt"]),
            FileBP(path="file 2", datatype=PlainText, filenames=["file 2.txt"]),
        ],
    )


@pytest.fixture
def spaced_dataset(
    data_store: Store, spaced_dataset_blueprint: TestDatasetBlueprint, work_dir: Path
) -> FrameSet:
    """A saved dataset where the dataset directory (for file-system stores), and the
    paths/filenames of the entries within it, contain spaces"""
    dataset_id: ty.Union[Path, str]
    if isinstance(data_store, FileSystem):
        dataset_id = work_dir / "dir with spaces" / "saved dataset"
        dataset_id.parent.mkdir(parents=True)
    else:
        dataset_id = "saved_dataset"
    return spaced_dataset_blueprint.make_dataset(data_store, dataset_id, name="")


def _check_sink(
    frameset: FrameSet, sink_name: str, bp: TestDatasetBlueprint, expected: str
) -> None:
    sink = frameset.add_sink(sink_name, TextFile)
    assert len(sink) == reduce(mul, bp.dim_lengths)
    for item in sink:
        assert Path(item).read_text() == expected


CONCATENATED = "\n".join(["file 1.txt", "file 2.txt"])

# Shell task that copies the input to the output, so both the input and output
# paths are passed on the command line
SHELL_TASK = {
    "type": "shell",
    "executable": [
        "cp",
        "<in_file:text/text-file>",
        "<out|out_file:text/text-file>",
    ],
}


@pytest.mark.parametrize(
    "user_input,expected_path,expected_qualifiers",
    [
        ("file 1", "file 1", {}),
        (
            '"file 1" criteria.datatype=text/plain',
            "file 1",
            {"criteria": {"datatype": "text/plain"}},
        ),
        (
            '"a dir/file 1" criteria.order=1 foo.bar="a value"',
            "a dir/file 1",
            {"criteria": {"order": 1}, "foo": {"bar": "a value"}},
        ),
    ],
)
def test_extract_qualifiers_from_path_with_spaces(
    user_input: str, expected_path: str, expected_qualifiers: dict[str, ty.Any]
) -> None:
    path, qualifiers = ContainerCommand.extract_qualifiers_from_path(user_input)
    assert path == expected_path
    assert dict(qualifiers) == expected_qualifiers


def test_command_execute_spaces(spaced_dataset: FrameSet, work_dir: Path) -> None:
    """Python task, dataset + input paths + work dir all containing spaces"""
    bp = spaced_dataset.__annotations__["blueprint"]
    command_spec = ContainerCommand(
        name="concatenate",
        task="frametree.testing.tasks:Concatenate",
        operates_on=bp.axes.default(),
    )
    command_spec.execute(
        address=spaced_dataset.address,
        input_values=[
            ("in_file1", "file 1"),
            ("in_file2", "file 2"),
        ],
        output_values=[
            ("out_file", "sink 1"),
        ],
        parameter_values=[
            ("duplicates", "1"),
        ],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir / "work dir"),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )
    _check_sink(spaced_dataset, "sink 1", bp, CONCATENATED)


def test_shell_command_execute_spaces(spaced_dataset: FrameSet, work_dir: Path) -> None:
    """Shell task, dataset + input paths + work dir all containing spaces"""
    bp = spaced_dataset.__annotations__["blueprint"]
    command_spec = ContainerCommand(
        name="shell-test",
        task=SHELL_TASK,
        operates_on=bp.axes.default(),
        sources={"source": "in_file"},
        sinks={"sink": "out_file"},
    )
    command_spec.execute(
        address=spaced_dataset.address,
        input_values=[("source", "file 1")],
        output_values=[("sink", "copied file")],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir / "work dir"),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )
    _check_sink(spaced_dataset, "copied file", bp, "file 1.txt")


@pytest.mark.parametrize("task_type", ["python", "shell"])
def test_pipeline_entrypoint_spaces(
    task_type: str,
    spaced_dataset: FrameSet,
    work_dir: Path,
    cli_runner: ty.Callable[..., ty.Any],
) -> None:
    """Run through the pipeline-entrypoint CLI (i.e. how the command is invoked in
    the container), with spaces in the dataset address, input/output paths, work
    dir and spec path"""
    bp = spaced_dataset.__annotations__["blueprint"]
    operates_on = "frametree.testing.axes:TestAxes[abcd]"
    if task_type == "python":
        command: dict[str, ty.Any] = {
            "task": "frametree.testing.tasks:Concatenate",
            "operates_on": operates_on,
        }
        inputs = [("in_file1", "file 1"), ("in_file2", "file 2")]
        params = [("duplicates", "1")]
        output = ("out_file", "entrypoint sink")
        expected = CONCATENATED
    else:
        command = {
            "task": SHELL_TASK,
            "operates_on": operates_on,
            "sources": {"source": "in_file"},
            "sinks": {"sink": "out_file"},
        }
        inputs = [("source", "file 1")]
        params = []
        output = ("sink", "entrypoint sink")
        expected = "file 1.txt"

    app = App(
        name="spaces-test",
        version="1.0.0",
        title="A pipeline to test spaces in paths",
        commands={"spaces": command},
        authors=[{"name": "Test Author", "email": "test@example.com"}],
        docs={"info_url": "http://spaces.readthefakedocs.io"},
        readme="Test pipeline",
    )
    spec_dir = work_dir / "spec dir"
    spec_dir.mkdir()
    spec_path = spec_dir / "app spec.yaml"
    app.save(spec_path)
    # sanity check that the spec was written out
    assert yaml.safe_load(spec_path.read_text())

    args = [spaced_dataset.address]
    for name, val in inputs:
        args.extend(["--input", name, val])
    args.extend(["--output", *output])
    for name, val in params:
        args.extend(["--parameter", name, val])
    args.extend(
        [
            "--dataset-hierarchy",
            ",".join(bp.hierarchy),
            "--work",
            str(work_dir / "work dir"),
            "--worker",
            "debug",
            "--raise-errors",
            "--spec-path",
            str(spec_path),
        ]
    )
    result = cli_runner(pipeline_entrypoint, args)
    assert result.exit_code == 0, result.output
    _check_sink(spaced_dataset, output[1], bp, expected)
