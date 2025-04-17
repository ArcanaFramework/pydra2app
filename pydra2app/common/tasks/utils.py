import typing as ty
import json
from pydra.compose import python
from fileformats.generic import File
from fileformats.core import FileSet


def define_identity(field_names: ty.List[str]) -> python.Task:
    """Define a function task that returns the input fields as output.

    Parameters
    ----------
    fields : list of str
        List of field names to be used in the task.

    Returns
    -------
    FunctionTask
        A function task that takes the input fields and returns them as output.
    """

    @python.define(inputs=field_names, outputs=field_names)
    def Identity(**kwargs: ty.Any) -> ty.Tuple[ty.Any, ...]:
        """Identity function that returns the input fields as output."""
        return tuple(kwargs[n] for n in field_names)

    return Identity


@python.define(outputs=["out_file"])
def IdentityConverter(in_file: FileSet) -> FileSet:
    return in_file


@python.define
def ExtractFromJson(in_file: File, field_name: str) -> ty.Any:
    with open(in_file) as f:
        dct = json.load(f)
    return dct[field_name]  # FIXME: Should use JSONpath syntax
