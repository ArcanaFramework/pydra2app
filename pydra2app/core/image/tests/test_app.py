import os
import docker
from pathlib import Path
from copy import deepcopy
from pydra.utils import get_fields
from frametree.common import FileSystem, Samples
from pydra2app.core.image import App, P2AImage
from pydra2app.core import PACKAGE_NAME
from conftest import TestDatasetBlueprint


def test_native_python_install(tmp_path):

    SAMPLE_INDEX = "1"
    OUTPUT_COL_NAME = "printed_version"

    dataset_dir = tmp_path / "dataset"
    sample_dir = dataset_dir / SAMPLE_INDEX
    sample_dir.mkdir(parents=True)
    sample_file = sample_dir / "sample.txt"
    sample_file.write_text("sample")

    dataset = FileSystem().define_frameset(dataset_dir, axes=Samples)
    dataset.save()

    test_spec = {
        "name": "native_python_test",
        "title": "a test image spec",
        "commands": {
            "python-test-command": {
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
                "row_frequency": "common:Samples[sample]",
            },
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

    app = App.load(test_spec)

    app.make(build_dir=tmp_path / "build-dir", use_local_packages=True)

    volume_mount = str(dataset_dir) + ":/dataset:rw"
    args = [
        "/dataset",
        "--parameter",
        "dummy",
        "1",
        "--parameter",
        "print_version",
        "True",
        "--output",
        "stdout",
        OUTPUT_COL_NAME,
    ]

    dc = docker.from_env()
    try:
        dc.containers.run(
            app.reference,
            command=args,
            stderr=True,
            volumes=[volume_mount],
            user=f"{os.getuid()}:{os.getgid()}",
        )
    except docker.errors.ContainerError as e:
        raise RuntimeError(
            f"'docker run -v {volume_mount} {app.reference} {' '.join(args)}' errored:\n"
            + e.stderr.decode("utf-8")
        )

    dataset = FileSystem().load_frameset(dataset_dir)

    def strip_ver_timestamp(ver_str):
        parts = str(ver_str).split("+")
        try:
            parts[1] = parts[1].split(".")[0]
        except IndexError:
            pass
        return "+".join(parts).strip()

    assert str(dataset[OUTPUT_COL_NAME][SAMPLE_INDEX]).split(",")[0] == PACKAGE_NAME


def test_add_resources(tmp_path):

    img = P2AImage(
        name="test-resource-add-image",
        version="1.0",
        packages={
            "system": ["vim", "git"],  # just to test it out
            "pip": {
                "pydra2app": None,
            },  # just to test out the
        },
        base_image={
            "name": "python",
            "tag": "3.12.5-slim-bookworm",
            "python": "python3",
            "package_manager": "apt",
            "conda_env": None,
        },
        resources={
            "a-resource": "/internal/path/to/a/resource.txt",
            "another-resource": "/internal/path/to/another/resource",
        },
    )

    foo_file = tmp_path / "resources" / "foo.txt"
    foo_file.parent.mkdir(parents=True)
    foo_file.write_text("foo")

    resources_dir = tmp_path / "resources"
    another_resource_sub_dir = resources_dir / "another-resource"
    another_resource_sub_dir.mkdir(parents=True)
    (another_resource_sub_dir / "bar.txt").write_text("bar")

    img.make(
        build_dir=tmp_path / "build-dir",
        use_local_packages=True,
        resources={
            "a-resource": foo_file,
        },
        resources_dir=resources_dir,
    )

    dc = docker.from_env()
    args = ["cat", "/internal/path/to/a/resource.txt"]
    try:
        result = dc.containers.run(
            img.reference,
            command=args,
            stderr=True,
        )
    except docker.errors.ContainerError as e:
        raise RuntimeError(
            f"'docker run {img.reference} {' '.join(args)}' errored:\n"
            + e.stderr.decode("utf-8")
        )

    assert result == b"foo"

    args = ["cat", "/internal/path/to/another/resource/bar.txt"]
    try:
        result = dc.containers.run(
            img.reference,
            command=args,
            stderr=True,
        )
    except docker.errors.ContainerError as e:
        raise RuntimeError(
            f"'docker run {img.reference} {' '.join(args)}' errored:\n"
            + e.stderr.decode("utf-8")
        )
    assert result == b"bar"


def test_multi_command(
    simple_dataset_blueprint: TestDatasetBlueprint, tmp_path: Path
) -> None:

    dataset = simple_dataset_blueprint.make_dataset(
        FileSystem(), tmp_path / "dataset", name=""
    )

    two_dup_spec = {
        "name": "concatenate",
        "task": "frametree.testing.tasks:Concatenate",
        "row_frequency": simple_dataset_blueprint.axes.default().tostr(),
        "configuration": {"duplicates": 2},
    }

    three_dup_spec = deepcopy(two_dup_spec)
    three_dup_spec["configuration"]["duplicates"] = 3

    test_spec = {
        "name": "test_multi_commands",
        "title": "a test image for multi-image commands",
        "commands": {
            "two_duplicates": two_dup_spec,
            "three_duplicates": three_dup_spec,
        },
        "version": "1.0",
        "packages": {
            "system": ["vim", "git"],  # just to test it out
            "pip": {
                "fileformats": None,
                "pydra": None,
                "pydra2app": None,
                "frametree": None,
            },
        },
        "authors": [{"name": "Some One", "email": "some.one@an.email.org"}],
        "docs": {
            "info_url": "http://concatenate.readthefakedocs.io",
        },
    }

    app = App.load(test_spec)

    app.make(build_dir=tmp_path / "build-dir", use_local_packages=True)

    volume_mount = str(dataset.id) + ":/dataset:rw"
    base_args = [
        "/dataset",
        "--input",
        "in_file1",
        "file1",
        "--input",
        "in_file2",
        "file2",
        "--output",
        "out_file",
    ]

    fnames = ["file1.txt", "file2.txt"]

    for command in ["two_duplicates", "three_duplicates"]:

        # Name the output column based on the command and set the command
        args = base_args + [command + "_sink", "--command", command]

        dc = docker.from_env()
        try:
            dc.containers.run(
                app.reference,
                command=args,
                stderr=True,
                volumes=[volume_mount],
                user=f"{os.getuid()}:{os.getgid()}",
            )
        except docker.errors.ContainerError as e:
            raise RuntimeError(
                f"'docker run -v {volume_mount} {app.reference} {' '.join(args)}' errored:\n"
                + e.stderr.decode("utf-8")
            )

        # Add source column to saved dataset
        reloaded = dataset.reload()
        sink = reloaded[command + "_sink"]
        duplicates = 2 if command == "two_duplicates" else 3
        expected_contents = "\n".join(fnames * duplicates)
        for item in sink:
            with open(item) as f:
                contents = f.read()
            assert contents == expected_contents


def test_serialization_roundtrip(tmp_path: Path) -> None:

    test_spec = {
        "name": "native_python_test",
        "title": "a test image spec",
        "commands": {
            "python-test-command": {
                "task": {
                    "type": "shell",
                    "executable": [
                        "pydra2app",
                        "--version<version>",
                    ],
                    "inputs": {
                        "dummy": {
                            "type": int | None,
                            "help": "not actually used",
                            "argstr": None,  # won't be printed to the command line
                        }
                    },
                },
                "row_frequency": "common:Samples[sample]",
            },
        },
        "version": "1.0",
        "packages": {
            "system": ["git"],  # just to test it out
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

    app = App.load(test_spec)

    # Serialize the app to a file
    save_path = tmp_path / (app.name + ".json")
    app.save(save_path)
    reloaded_app = App.load(save_path)
    assert app.commands[0] == reloaded_app.commands[0]
    assert app == reloaded_app
