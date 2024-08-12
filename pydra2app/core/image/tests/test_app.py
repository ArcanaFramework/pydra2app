from traceback import format_exc
import docker
from pydra2app.core.image import App


def test_native_python_install(tmp_path):

    test_spec = {
        "name": "native_python_test",
        "title": "a test image spec",
        "command": {
            "task": "common:shell",
            "inputs": {
                "dummy": {
                    "datatype": "field/text",
                    "field": "dummy",
                    "help": "a dummy field",
                    "configuration": {
                        "position": 0,
                    },
                },
            },
            "outputs": {
                "concatenated": {
                    "datatype": "field/text",
                    "field": "print_out",
                    "help": "the print to stdout",
                    "configuration": {
                        "callable": "common:value_from_stdout",
                    },
                }
            },
            "parameters": {
                "duplicates": {
                    "field": "duplicates",
                    "default": 2,
                    "datatype": "field/integer",
                    "required": True,
                    "help": "a parameter",
                }
            },
            "row_frequency": "common:Samples[sample]",
            "configuration": {
                "executable": [
                    "pydra2app",
                    "--version",
                ]
            },
        },
        "version": {"package": "1.0", "build": "1"},
        "packages": {
            "system": ["vim"],  # just to test it out
            "pip": {"pydra2app": None},  # just to test out the
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

    app.make(build_dir=tmp_path, use_local_packages=True)

    dc = docker.from_env()
    result = dc.containers.run(
        app.reference, command=["/", "--input", "dummy", "foo"], stderr=True
    )

    stdout = result.decode("utf-8")

    assert stdout.startswith("Python 3.12"), f"Expected 'Python 3.12', got {stdout}"
