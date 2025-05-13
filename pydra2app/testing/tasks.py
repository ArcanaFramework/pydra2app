import shutil
from pathlib import Path
import typing as ty
from copy import deepcopy
import attrs
from pydra.compose import python
import fileformats.core
from fileformats.generic import File
from fileformats.text import TextFile
from fileformats.testing import EncodedText
import fileformats.text
from frametree.core.row import DataRow
from pydra2app.testing.constants import LICENSE_OUTPUT_FIELD


@python.define
def add(a: float, b: float) -> float:
    return a + b


@python.define(outputs=["path", "suffix"])
def path_manip(dpath: Path, fname: str) -> ty.Tuple[str, str]:
    path = dpath / fname
    return str(path), path.suffix


@attrs.define(auto_attribs=True)
class A:
    x: int
    y: int


@attrs.define(auto_attribs=True)
class B:
    u: float
    v: float


@attrs.define(auto_attribs=True)
class C:
    z: float


@python.define(outputs=["c"])
def AttrsFunc(a: A, b: B) -> C:
    return C(z=a.x * b.u + a.y * b.v)


@python.define
def Plus10ToFileNumbers(filenumber_row: DataRow) -> None:
    """Alters the item paths within the data row, by converting them to
    an int and adding 10. Used in the test_run_pipeline_on_row_cli test.

    Parameters
    ----------
    row : DataRow
        the data row to modify
    """

    # Make a deep copy so the hash of the original isn't modified
    filenumber_row = deepcopy(filenumber_row)
    for entry in filenumber_row.entries:
        item = fileformats.text.TextFile(ty.cast(fileformats.core.FileSet, entry.item))
        new_item_stem = str(int(item.stem) + 10)
        shutil.move(item.fspath, item.fspath.parent / (new_item_stem + item.actual_ext))


@python.define(outputs=["out_file"])
def IdentityFile(in_file: File) -> File:
    return in_file


@python.define(outputs=["out_file"])
def IdentityTextFile(in_file: TextFile) -> TextFile:
    """
    Parameters
    ----------
    in_file : TextFile
        the input text file

    Returns
    -------
    out_file: TextFile
        the output text file
    """
    return in_file


@python.define(outputs=["out_file"])
def IdentityEncodedText(in_file: EncodedText) -> EncodedText:
    return in_file


@python.define
def identity(in_: ty.Any) -> ty.Any:
    return in_


@python.define
def MultiplyContents(
    in_file: File,
    multiplier: ty.Union[int, float],
    out_file: ty.Optional[Path] = None,
    dtype: type = float,
) -> File:
    """Multiplies the contents of the file, assuming that it contains numeric
    values on separate lines

    Parameters
    ----------
    in_file : Path
        path to input file to multiply the contents of
    multiplier : int or float
        the multiplier to apply to the file values
    out_file : Path
        the path to write the output file to
    dtype : type
        the type to cast the file contents to"""

    if out_file is None:
        out_file = Path("out_file.txt").absolute()

    with open(in_file) as f:
        contents = f.read()

    multiplied = []
    for line in contents.splitlines():
        multiplied.append(str(dtype(line.strip()) * multiplier))

    with open(out_file, "w") as f:
        f.write("\n".join(multiplied))

    return File(out_file)


@python.define
def ContentsAreNumeric(in_file: File) -> bool:
    """Checks the contents of a file to see whether each line can be cast to a numeric
    value

    Parameters
    ----------
    in_file : Path
        the path to a text file

    Returns
    -------
    bool
        if all the lines are numeric return True
    """
    with open(in_file) as f:
        contents = f.read()
    try:
        float(contents.strip())
    except ValueError:
        return False
    return True


@python.define(outputs=[LICENSE_OUTPUT_FIELD])
def CheckLicence(
    expected_license_path: File,
    expected_license_contents: File,
) -> File:
    """Checks the `expected_license_path` to see if there is a file with the same contents
    as that of `expected_license_contents`

    Parameters
    ----------
    expected_license_path : File
        path to the expected license file
    expected_license_contents : File
        path containing the contents expected in the expected license file

    Returns
    -------
    File
        passes through the expected license file so the task can be connected back to the
        dataset
    """
    with open(expected_license_contents) as f:
        expected_contents = f.read()
    with open(expected_license_path) as f:
        actual_contents = f.read()
    if expected_contents != actual_contents:
        raise Exception(
            f'License contents "{actual_contents}" did not match '
            f'expected "{expected_contents}"'
        )
    return expected_license_contents


TEST_TASKS = {
    "add": (add, {"a": 4, "b": 5}, {"out": 9}),
    "path_manip": (
        path_manip,
        {"dpath": Path("/home/foo/Desktop"), "fname": "bar.txt"},
        {"path": "/home/foo/Desktop/bar.txt", "suffix": ".txt"},
    ),
    "attrs_func": (
        AttrsFunc,
        {"a": A(x=2, y=4), "b": B(u=2.5, v=1.25)},
        {"c": C(z=10)},
    ),
}

BASIC_TASKS = ["add", "path_manip", "attrs_func"]

FILE_TASKS = ["concatenate"]
