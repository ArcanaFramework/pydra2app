import os
import typing as ty
from functools import reduce
from operator import mul
from pathlib import Path
import re
import pytest
from frametree.testing.blueprint import (
    TestDatasetBlueprint,
    FileSetEntryBlueprint as FileBP,
)
from pydra.compose import python
from fileformats.text import TextFile, Plain as PlainText
from fileformats.testing import EncodedText
from fileformats.core import converter
from fileformats.image import Png
import fileformats.field as ffield
from fileformats.generic import File
from frametree.core.frameset import FrameSet
from frametree.file_system import FileSystem
from frametree.testing import TestAxes
from pydra2app.core.command.base import ContainerCommand
from pydra2app.core import App
from frametree.core.exceptions import FrameTreeDataMatchError


# Set up converter between text and encoded-text and back again
@pytest.fixture(scope="session")
def encoded_text_converter():
    @converter(
        source_format=EncodedText, target_format=TextFile, out_filename="out_file.txt"
    )
    @converter(
        source_format=TextFile, target_format=EncodedText, out_filename="out_file.enc"
    )
    @python.define(outputs=["out_file"])
    def EncoderTask(
        in_file: ty.Union[str, bytes, os.PathLike],
        out_filename: str,
        shift: int = 0,
    ) -> Path:
        def encode_text(text: str, shift: int) -> str:
            encoded = []
            for c in text:
                encoded.append(chr(ord(c) + shift))
            return "".join(encoded)

        with open(in_file) as f:
            contents = f.read()
        encoded = encode_text(contents, shift)
        with open(out_filename, "w") as f:
            f.write(encoded)
        return Path(out_filename).absolute()

    return None


def test_command_execute(
    ConcatenateTask: ty.Callable[..., ty.Any], saved_dataset: FrameSet, work_dir: Path
) -> None:
    # Get CLI name for dataset (i.e. file system path prepended by 'file_system//')
    bp = saved_dataset.__annotations__["blueprint"]
    duplicates = 1

    command_spec = ContainerCommand(
        name="concatenate",
        task="frametree.testing.tasks:" + ConcatenateTask.__name__,
        operates_on=bp.axes.default(),
    )
    # Start generating the arguments for the CLI
    # Add source to loaded dataset
    command_spec.execute(
        address=saved_dataset.locator,
        input_values=[
            ("in_file1", "file1"),
            ("in_file2", "file2"),
        ],
        output_values=[
            ("out_file", "sink_1"),
        ],
        parameter_values=[
            ("duplicates", str(duplicates)),
        ],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
        save_frameset=True,
    )
    # Add source column to saved dataset
    reloaded = saved_dataset.reload()
    sink = reloaded["sink_1"]
    assert len(sink) == reduce(mul, bp.dim_lengths)
    fnames = ["file1.txt", "file2.txt"]
    if ConcatenateTask.__name__.endswith("Reverse"):
        fnames = [f[::-1] for f in fnames]
    expected_contents = "\n".join(fnames * duplicates)
    for item in sink:
        with open(item) as f:
            contents = f.read()
        assert contents == expected_contents


def test_command_execute_fail(
    ConcatenateTask: ty.Callable[..., ty.Any], saved_dataset: FrameSet, work_dir: Path
) -> None:
    # Get CLI name for dataset (i.e. file system path prepended by 'file_system//')
    bp = saved_dataset.__annotations__["blueprint"]
    duplicates = 1

    command_spec = ContainerCommand(
        name="concatenate",
        task="frametree.testing.tasks:" + ConcatenateTask.__name__,
        operates_on=bp.axes.default(),
    )

    # Start generating the arguments for the CLI
    # Add source to loaded dataset
    with pytest.raises(FrameTreeDataMatchError):
        command_spec.execute(
            address=saved_dataset.locator,
            input_values=[
                ("in_file1", "bad-file-path"),
                ("in_file2", "file1"),
            ],
            output_values=[
                ("out_file", "sink1"),
            ],
            parameter_values=[
                ("duplicates", duplicates),
            ],
            raise_errors=True,
            worker="debug",
            work_dir=str(work_dir),
            loglevel="debug",
            dataset_hierarchy=",".join(bp.hierarchy),
            pipeline_name="test_pipeline",
        )


def test_command_execute_on_row(
    cli_runner: ty.Callable[..., ty.Any], work_dir: Path
) -> None:

    # Create test dataset consisting of a single row with a range of filenames
    # from 0 to 4
    filenumbers = list(range(5))
    bp = TestDatasetBlueprint(
        axes=TestAxes,
        hierarchy=[
            "abcd"
        ],  # e.g. XNAT where session ID is unique in project but final layer is organised by visit
        dim_lengths=[1, 1, 1, 1],
        entries=[
            FileBP(path=str(i), datatype=TextFile, filenames=[f"{i}.txt"])
            for i in filenumbers
        ],
    )
    dataset_path = work_dir / "numbered_dataset"
    dataset = bp.make_dataset(FileSystem(), dataset_path)
    dataset.save()

    def get_dataset_filenumbers():
        row = next(iter(dataset.rows()))
        return sorted(int(i.path.split(".")[0]) for i in row.entries)

    assert get_dataset_filenumbers() == filenumbers

    command_spec = ContainerCommand(
        name="plus-10",
        task="pydra2app.testing.tasks:Plus10ToFileNumbers",
        operates_on=bp.axes.default(),
        # inputs=[
        #     {
        #         "name": "a_row",
        #         "datatype": "frametree.core.row:DataRow",
        #         "field": "filenumber_row",
        #         "help": "dummy",
        #     },
        # ],
    )

    # Start generating the arguments for the CLI
    # Add source to loaded dataset
    command_spec.execute(
        address=dataset.locator,
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )

    assert get_dataset_filenumbers() == [i + 10 for i in filenumbers]


def test_command_execute_with_converter_args(
    saved_dataset: FrameSet, work_dir: Path, encoded_text_converter
):
    """Test passing arguments to file format converter tasks via input/output
    "qualifiers", e.g. 'converter.shift=3' using the pydra2app-run-pipeline CLI
    tool (as used in the XNAT CS commands)
    """
    # Get CLI name for dataset (i.e. file system path prepended by 'file_system//')
    bp = saved_dataset.__annotations__["blueprint"]

    # Add source and sink columns to the dataset
    saved_dataset.add_source("file1", datatype=TextFile, path="file1")
    saved_dataset.add_sink("sink1", datatype=TextFile)
    saved_dataset.add_sink("sink2", datatype=TextFile)

    # Save the column definitions in the dataset
    saved_dataset.save()
    # Start generating the arguments for the CLI
    # Add source to loaded dataset
    command_spec = ContainerCommand(
        name="identity",
        task="pydra2app.testing.tasks:IdentityEncodedText",
        operates_on=bp.axes.default(),
    )

    command_spec.execute(
        address=saved_dataset.locator,
        input_values=[
            ("in_file", "<file1> converter.shift=3"),
        ],
        output_values=[
            ("out_file", "sink1"),
        ],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )
    command_spec.execute(
        address=saved_dataset.locator,
        input_values=[
            ("in_file", "<file1> converter.shift=3"),
        ],
        output_values=[
            ("out_file", "sink2 converter.shift=-3"),
        ],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )

    # Add sink column to saved dataset to access data created by the executed command spec
    reloaded = saved_dataset.reload()
    unencoded_contents = "file1.txt"
    encoded_contents = (
        "iloh41w{w"  # 'file1.txt' characters shifted up by 3 in ASCII code
    )
    for row in reloaded.rows(frequency="abcd"):
        enc_cell = row.cell("sink1", allow_empty=False)
        dec_cell = row.cell("sink2", allow_empty=False)
        enc_item = enc_cell.item
        dec_item = dec_cell.item
        with open(enc_item) as f:
            enc_contents = f.read()
        with open(dec_item) as f:
            dec_contents = f.read()
        assert enc_contents == encoded_contents
        assert dec_contents == unencoded_contents


@pytest.mark.xfail(
    reason="'>' operator isn't supported by shell-command task any more (it perhaps should be)"
)
def test_shell_command_execute(saved_dataset, work_dir):
    # Get CLI name for dataset (i.e. file system path prepended by 'file_system//')
    bp = saved_dataset.__annotations__["blueprint"]
    duplicates = 1

    command_spec = ContainerCommand(
        name="shell-test",
        task="shell",
        operates_on=bp.axes.default(),
        sources=[
            {
                "name": "source1",
                "datatype": "text/text-file",
                "help": "dummy",
                "configuration": {
                    "argstr": "",
                    "position": 0,
                },
            },
            {
                "name": "source2",
                "datatype": "text/text-file",
                "help": "dummy",
                "configuration": {
                    "argstr": "",
                    "position": 2,
                },
            },
        ],
        sinks=[
            {
                "name": "sink1",
                "datatype": "text/text-file",
                "help": "dummy",
                "configuration": {
                    "argstr": ">{sink1}",
                    "position": 3,
                },
            }
        ],
        configuration={"executable": "cat"},
    )
    # Start generating the arguments for the CLI
    # Add source to loaded dataset
    command_spec.execute(
        address=saved_dataset.locator,
        input_values=[
            ("source1", "file1"),
            ("source2", "file2"),
        ],
        output_values=[
            ("sink1", "concatenated"),
        ],
        parameter_values=[
            ("duplicates", str(duplicates)),
        ],
        raise_errors=True,
        worker="debug",
        work_dir=str(work_dir),
        loglevel="debug",
        dataset_hierarchy=",".join(bp.hierarchy),
        pipeline_name="test_pipeline",
    )
    # Add source column to saved dataset
    sink = saved_dataset.add_sink("concatenated", TextFile)
    assert len(sink) == reduce(mul, bp.dim_lengths)
    fnames = ["file1.txt", "file2.txt"]
    expected_contents = "\n".join(fnames * duplicates)
    for item in sink:
        with open(item) as f:
            contents = f.read()
        assert contents == expected_contents


@pytest.mark.parametrize(
    ["cmd_spec", "expected_attrs"],
    [
        (
            {
                "task": {
                    "type": "shell",
                    "executable": [
                        "pydra2app",
                        "--version<print_version>",
                    ],
                    "inputs": {
                        "dummy": {
                            "type": int | None,
                            "help": "not actually used",
                            "argstr": None,  # won't be printed to the command line
                        }
                    },
                },
                "operates_on": "samples/sample",
                "sinks": {"pydra2app_version": "stdout"},
            },
            {
                "source_names": [],
                "sink_names": ["pydra2app_version"],
                "sinks[0].name": "pydra2app_version",
                "sinks[0].field": "stdout",
                "sinks[0].type": ffield.Text,
                "parameter_names": ["dummy", "print_version", "append_args"],
                "parameters[0].name": "dummy",
                "parameters[0].type": ffield.Integer | None,
                "parameters[0].help": "not actually used",
                "parameters[1].name": "print_version",
                "parameters[1].type": ffield.Boolean,
                "parameters[1].help": "",
                "parameters[2].name": "append_args",
                "parameters[2].type": list[ffield.Text | File],
                "parameters[2].help": "Additional free-form arguments to append to the end of the command.",
            },
        ),
        (
            {
                "task": {
                    "type": "shell",
                    "executable": [
                        "my-app",
                        "<in_file:generic/file>",
                        "<out|out_file:image/png>",
                        "--optional-file",
                        "<optional_file:generic/file?>",
                        "--template",
                        "<template:image/png?>",
                        "--flag<flag>",
                        "--param",
                        "<param:int?>",
                        # "--file-pair",
                        # "<file_pair:text/plain,text/plain?>",
                        "--not-needed-file",
                        "<out|not_needed:generic/file>",
                    ],
                },
                "operates_on": "samples/sample",
                "sources": {
                    "an_image": "in_file",
                    "optional_file": None,
                    # "file_pair": None,
                },
                "sinks": {"my_app_out_file": "out_file", "my_app_stdout": "stdout"},
                "parameters": ["template", "param"],
            },
            {
                "source_names": ["an_image", "optional_file"],  # , "file_pair"
                "sink_names": ["my_app_out_file", "my_app_stdout"],
                "parameter_names": ["template", "param"],
                "sources[0].name": "an_image",
                "sources[0].field": "in_file",
                "sources[0].type": File,
                "sources[0].help": "",
                # "sources[1].name": "file_pair",
                # "sources[1].field": "file_pair",
                # "sources[1].type": tuple[PlainText, PlainText] | None,
                "sources[1].name": "optional_file",
                "sources[1].field": "optional_file",
                "sources[1].type": File | None,
                "sinks[0].name": "my_app_out_file",
                "sinks[0].field": "out_file",
                "sinks[0].type": Png,
                "sinks[1].name": "my_app_stdout",
                "sinks[1].field": "stdout",
                "sinks[1].type": ffield.Text,
                "parameters[0].name": "template",
                "parameters[0].type": Png | None,
                "parameters[0].help": "",
                "parameters[1].name": "param",
                "parameters[1].type": ffield.Integer | None,
                "parameters[1].help": "",
            },
        ),
    ],
)
def test_command_serialization(
    cmd_spec: dict[str, ty.Any], expected_attrs: dict[str, ty.Any], tmp_path: Path
) -> None:

    app = App(
        **{
            "name": "native_python_test",
            "title": "a test image spec",
            "commands": {
                "a-command": cmd_spec,
            },
            "version": "1.0",
            "packages": {
                "system": ["vim", "git"],  # just to test it out
                "pip": {
                    "pydra2app": None,
                    "frametree": None,
                    "pydra": None,
                },  # just to test out the
            },
            "base_image": {
                "name": "python",
                "tag": "3.12.5-slim-bookworm",
                "python": "python3",
                "package_manager": "apt",
                "conda_env": None,
            },
            "authors": [{"name": "Some One", "email": "some.one@an.email.org"}],
            "docs": {
                "info_url": "http://concatenate.readthefakedocs.io",
            },
        }
    )

    # Round trip to file and back again
    app.save(tmp_path / "app_spec.yaml")
    app = App.load(tmp_path / "app_spec.yaml")

    cmd = app.commands[0]

    for attr_path, expected in expected_attrs.items():
        match = re.match(r"^(\w+)(\[.+\])?(\.\w+)?$", attr_path)
        actual = getattr(cmd, match.group(1))
        if match.group(2):
            actual = actual[int(match.group(2)[1:-1])]
        if match.group(3):
            actual = getattr(actual, match.group(3)[1:])
        assert (
            actual == expected
        ), f"Attribute '{attr_path}' expected {expected} but got {actual}"
