from pydra.compose import shell
from fileformats.generic import Directory


def test_shell(work_dir):

    Cp = shell.define(
        "cp",
        inputs={
            "in_dir": {
                "type": "generic/directory",
            },
            "recursive": {
                "type": "field/boolean",
                "argstr": "-R",
                "position": 0,
            },
        },
        outputs={
            "out_dir": {
                "type": "generic/directory",
                "position": -1,
            }
        },
    )

    in_dir = work_dir / "source-dir"
    in_dir.mkdir()
    with open(in_dir / "a-file.txt", "w") as f:
        f.write("abcdefg")

    out_dir = work_dir / "dest-dir"

    cp = Cp(
        in_dir=str(in_dir),
        out_dir=str(out_dir),
        recursive=True,
    )

    outputs = cp()
    assert outputs.out_dir == Directory(out_dir)
    assert list(p.name for p in out_dir.iterdir()) == ["a-file.txt"]
