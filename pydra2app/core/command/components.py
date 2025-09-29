from __future__ import annotations
import os
import inspect
import logging
import typing as ty
import attrs
import pydra.compose.base
from fileformats.core import DataType, Field
import fileformats.field as ffield
from pydra.utils import get_fields, structure, unstructure
import pydra.utils.general
from pydra.compose.base import Arg, Out
from frametree.core.exceptions import FrametreeCannotSerializeDynamicDefinitionError
from pydra.utils.typing import (
    is_union,
    is_optional,
    is_container,
)  # , is_subclass_or_union
from frametree.core.serialize import ClassResolver
from frametree.core.row import DataRow
from frametree.core.axes import Axes
from pydra2app.core.exceptions import Pydra2AppUsageError
from pydra2app.core import PACKAGE_NAME


if ty.TYPE_CHECKING:
    from ..image import App
    from .base import ContainerCommand


# Just until this gets added to Pydra


def is_subclass_or_union(
    type_: type, reference: type, allow_none: bool | None = None
) -> bool:
    """Check if the type is a subclass of given reference or a Union containing
    that reference type

    Parameters
    ----------
    type_ : type
        the type to check
    reference : type
        the reference type to check whether the type is a sub-class of or not
    allow_none : bool, optional
        whether to allow None as a valid type, by default None. If None, then None
        is not allowed at the outer layer, but is allowed within a Union

    Returns
    -------
    bool
        whether the type is a FileSet or a Union containing a FileSet
    """
    if type_ is None and allow_none:
        return True
    if is_union(type_):
        return any(
            is_subclass_or_union(
                t, reference, allow_none=allow_none or allow_none is None
            )
            for t in ty.get_args(type_)
        )
    elif not inspect.isclass(type_):
        return False
    return issubclass(type_, reference)


logger = logging.getLogger("pydra2app")

DEFAULT_TASK_NAME = "ContainerCommandTask"


def task_converter(
    task_class: str | dict[str, ty.Any],
) -> type[pydra.compose.base.Task]:

    task_cls: type[pydra.compose.base.Task]

    if isinstance(task_class, str):
        task_cls = ClassResolver(  # type: ignore[misc]
            pydra.compose.base.Task,
            package=PACKAGE_NAME,
        )(task_class)
    elif isinstance(task_class, dict):

        if task_class["type"] == "python":
            task_class["function"] = ClassResolver.fromstr(task_class["function"])

        for field_dct in list(task_class.get("inputs", {}).values()) + list(
            task_class.get("outputs", {}).values()
        ):
            if isinstance(field_dct, dict):
                type_ = field_dct.get("type", None)
                if isinstance(type_, str):
                    field_dct["type"] = ClassResolver.fromstr(type_)

        task_cls = structure(task_class)
    elif issubclass(task_class, pydra.compose.base.Task):
        task_cls = task_class
    else:
        raise TypeError(f"Cannot convert {type(task_class)} ({task_class}) to a task")
    return task_cls


def task_equals(
    task_cls: type[pydra.compose.base.Task],
) -> tuple[str, pydra.utils.general._TaskFieldsList]:
    """Used to compare task classes to see if they are equivalent."""
    return task_cls._task_type(), get_fields(task_cls)


def task_serializer(
    task_cls: type[pydra.compose.base.Task],
    **kwargs: ty.Any,
) -> str | dict[str, ty.Any]:
    """Serializes a task to a dictionary

    Parameters
    ----------
    task : type[pydra.compose.base.Task]
        the task to serialize
    **kwargs: Any
        keyword arguments passed to the `unstructure` serializer

    Returns
    -------
    str | dict[str, ty.Any]
        the serialized task, either as a import location, or as a serialised dictionary
        of the task definition if the import location is not available (i.e. the task was
        dynamically created)
    """
    try:
        address: str = ClassResolver.tostr(task_cls, strip_prefix=False)
    except FrametreeCannotSerializeDynamicDefinitionError:
        dct: dict[str, ty.Any] = unstructure(task_cls, **kwargs)
        return dct
    else:
        return address


@attrs.define(kw_only=True, auto_attribs=False)
class ContainerCommandSource:
    """Define a source for a container command."""

    name: str = attrs.field()
    row_frequency: Axes = attrs.field()
    type: type[DataType] = attrs.field()
    field: str = attrs.field()
    help: str = attrs.field()
    _field_object: Arg = attrs.field(repr=False)
    _operates_on: Axes = attrs.field()
    _command: "ContainerCommand" = attrs.field(repr=False, eq=False, default=None)

    @property
    def mandatory(self) -> bool:
        return self._field_object.mandatory

    @property
    def field_type(self) -> type[DataType]:
        return self._field_object.type

    def asdict(self, **kwargs: ty.Any) -> dict[str, ty.Any]:
        delta: dict[str, ty.Any] = {}
        if self.field != self.name:
            delta["field"] = self.field
        if self.type is not self._field_object.type:
            delta["type"] = self.type
        if self.row_frequency is not self._operates_on:
            delta["row_frequency"] = self.row_frequency
        if self.help != self._field_object.help:
            delta["help"] = self.help
        return delta

    @classmethod
    def fromdict(cls, name: str, delta: dict[str, ty.Any], command: "ContainerCommand"):
        obj = command._input_fields[delta.get("field", name)]
        type_ = delta.get("type", obj.type)
        if isinstance(type_, str):
            type_ = ClassResolver.fromstr(type_)
        return cls(
            name=name,
            row_frequency=delta.get("row_frequency", command.operates_on),
            type=convert_to_datatype(type_),
            field=delta.get("field", name),
            help=delta.get("help", obj.help),
            field_object=obj,
            operates_on=command.operates_on,
            command=command,
        )


def sources_converter(
    value: dict[str, ty.Any] | ty.Collection[str],
    self_: "ContainerCommand",
) -> list[ContainerCommandSource]:
    if value is None:
        value = self_._default_sources()
    if isinstance(value, ty.Sequence):
        value = {s: {} for s in value}
    sources: list[ContainerCommandSource] = []
    for name, src in value.items():
        if isinstance(src, ContainerCommandSource):
            source = src
        elif src is not None and not isinstance(src, (dict, str)):
            raise ValueError(f"Invalid source definition for '{name}': {src}")
        else:
            if src is None:
                src = {}
            if isinstance(src, str):
                src = {"field": src}
            source = ContainerCommandSource.fromdict(name, src, self_)
        source._field_object = self_._input_fields[source.field]
        if source.type is DataRow:
            raise ValueError(
                f"DataRow input fields cannot be used as a source type ('{source.field}')"
            )
        sources.append(source)
    return sources


def sources_serialiser(
    sources: ty.List[ty.Any], **kwargs: ty.Any
) -> list[str] | dict[str, ContainerCommandSource] | None:
    if not sources:
        return None
    serialized = {s.name: s.asdict(**kwargs) for s in sources}
    if all(not v for v in serialized.values()):
        serialized = list(serialized)
        command = next(iter(sources))._command
        if set(serialized) == set(command._default_sources()):
            return None
    return serialized


@attrs.define(kw_only=True, auto_attribs=False)
class ContainerCommandSink:
    """Define a sink for a container command."""

    name: str = attrs.field()
    type: type[DataType] = attrs.field()
    field: str = attrs.field()
    help: str = attrs.field()
    _field_object: Out = attrs.field(repr=False)
    _command: "ContainerCommand" = attrs.field(repr=False, eq=False, default=None)

    @property
    def field_type(self) -> type[DataType]:
        return self._field_object.type

    def asdict(self, **kwargs: ty.Any) -> dict[str, ty.Any]:
        delta: dict[str, ty.Any] = {}
        if self.field != self.name:
            delta["field"] = self.field
        if self.type is not self._field_object.type:
            delta["type"] = self.type
        if self.help != self._field_object.help:
            delta["help"] = self.help
        return delta

    @classmethod
    def fromdict(cls, name: str, delta: dict[str, ty.Any], command: "ContainerCommand"):
        obj = command._output_fields[delta.get("field", name)]
        type_ = delta.get("type", obj.type)
        if isinstance(type_, str):
            type_ = ClassResolver.fromstr(type_)
        return cls(
            name=name,
            type=convert_to_datatype(type_),
            field=delta.get("field", name),
            help=delta.get("help", obj.help),
            field_object=obj,
            command=command,
        )


def sinks_converter(
    value: dict[str, Axes] | ty.Collection[str],
    self_: "ContainerCommand",
) -> list[ContainerCommandSink]:
    if value is None:
        value = self_._default_sinks()
    if not isinstance(value, dict):
        value = {s: {} for s in value}
    sinks: list[ContainerCommandSink] = []
    for name, snk in value.items():
        if isinstance(snk, ContainerCommandSink):
            sink = snk
        elif snk is not None and not isinstance(snk, (dict, str)):
            raise ValueError(f"Invalid sink definition for '{name}': {snk}")
        else:
            if snk is None:
                snk = {}
            if isinstance(snk, str):
                snk = {"field": snk}
            sink = ContainerCommandSink.fromdict(name, snk, self_)
        sink._field_object = self_._output_fields[sink.field]
        sinks.append(sink)
    return sinks


def sinks_serialiser(
    sinks: ty.List[ty.Any], **kwargs: ty.Any
) -> list[str] | dict[str, ContainerCommandSink] | None:
    if not sinks:
        return None
    dct = {s.name: s.asdict(**kwargs) for s in sinks}
    if all(not v for v in dct.values()):
        dct = list(dct)
        command = next(iter(sinks))._command
        if set(dct) == set(command._default_sinks()):
            return None
    return dct


@attrs.define(kw_only=True, auto_attribs=False)
class ContainerCommandParameter:
    """Define a parameter for a container command."""

    name: str = attrs.field()
    field: str = attrs.field()
    help: str = attrs.field()
    _field_object: Out = attrs.field(repr=False)
    _command: "ContainerCommand" = attrs.field(repr=False, eq=False, default=None)

    @property
    def field_type(self) -> type[DataType]:
        return self._field_object.type

    @property
    def type(self) -> type[DataType]:
        return convert_to_datatype(self.field_type)

    @property
    def default(self) -> ty.Any:
        return self._field_object.default

    @property
    def mandatory(self) -> bool:
        return self._field_object.mandatory

    def asdict(self, **kwargs: ty.Any) -> dict[str, ty.Any]:
        delta: dict[str, ty.Any] = {}
        if self.field != self.name:
            delta["field"] = self.field
        if self.help != self._field_object.help:
            delta["help"] = self.help
        return delta

    @classmethod
    def fromdict(cls, name: str, delta: dict[str, ty.Any], command: "ContainerCommand"):
        obj = command._input_fields[delta.get("field", name)]
        return cls(
            name=name,
            field=delta.get("field", name),
            help=delta.get("help", obj.help),
            field_object=obj,
            command=command,
        )


def parameters_converter(
    value: dict[str, Axes] | ty.Collection[str],
    self_: "ContainerCommand",
) -> list[ContainerCommandParameter]:
    if value is None:
        value = self_._default_parameters()
    if not isinstance(value, dict):
        value = {s: {} for s in value}
    parameters: list[ContainerCommandParameter] = []
    for name, prm in value.items():
        if isinstance(prm, ContainerCommandParameter):
            parameter = prm
        elif not isinstance(prm, (str, dict)):
            raise ValueError(f"Invalid parameter definition for '{name}': {prm}")
        else:
            if isinstance(prm, str):
                prm = {"field": prm}
            parameter = ContainerCommandParameter.fromdict(name, prm, self_)
        parameter._field_object = self_._input_fields[parameter.field]
        if parameter.type is DataRow:
            raise ValueError(
                f"DataRow input fields cannot be used as a parameter type ('{parameter.field}')"
            )
        parameters.append(parameter)
    return parameters


def parameters_serialiser(
    parameters: ty.List[ty.Any], **kwargs: ty.Any
) -> list[str] | dict[str, ContainerCommandParameter] | None:
    if not parameters:
        return None
    serialized = {p.name: p.asdict(**kwargs) for p in parameters}
    command = next(iter(parameters))._command
    if all(not v for v in serialized.values()):
        serialized = list(serialized)
        if set(serialized) == set(command._default_parameters()):
            return None
    return serialized


def convert_to_datatype(type_: type) -> type[DataType]:
    if is_optional(type_):
        non_none = [a for a in ty.get_args(type_) if a is not type(None)]
        if len(non_none) == 1:
            return convert_to_datatype(non_none[0]) | None  # type: ignore
        return ty.Union[tuple(convert_to_datatype(a) for a in non_none) + (None,)]  # type: ignore
    if is_union(type_):
        return ty.Union[tuple(convert_to_datatype(t) for t in ty.get_args(type_))]  # type: ignore
    if is_container(type_) and type_ is not str:
        return ty.get_origin(type_)[tuple(convert_to_datatype(t) for t in ty.get_args(type_))]  # type: ignore
    if inspect.isclass(type_) and issubclass(type_, DataType):
        return type_
    if issubclass(type_, (str, os.PathLike)):
        return ffield.Text
    try:
        return Field.from_primitive(type_)
    except StopIteration:
        raise Pydra2AppUsageError(f"Cannot convert type '{type_}' to a DataType")
