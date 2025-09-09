from __future__ import annotations
import shutil
import re
import os
from copy import copy
import tempfile
import json
import inspect
import logging
from pathlib import Path
import typing as ty
from functools import cached_property
import sys
from collections import defaultdict
import attrs
from attrs.converters import default_if_none
import pydra.compose.base
from fileformats.core import DataType, Field, from_mime
import fileformats.field as ffield
from pydra.utils import get_fields, structure, unstructure
import pydra.utils.general
from pydra.compose.base import Arg, Out
from frametree.core.exceptions import FrametreeCannotSerializeDynamicDefinitionError
from pydra.utils.typing import (
    is_union,
    is_optional,
    optional_type,
    is_container,
    is_fileset_or_union,
)  # , is_subclass_or_union
from frametree.core.serialize import ClassResolver
from frametree.core.utils import show_workflow_errors, path2label
from frametree.core.row import DataRow
from frametree.core.frameset.base import FrameSet
from frametree.core.store import Store
from frametree.core.axes import Axes
from pydra2app.core.exceptions import Pydra2AppUsageError
from frametree.core.serialize import ObjectListConverter
from pydra2app.core import PACKAGE_NAME


if ty.TYPE_CHECKING:
    from ..image import App


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
        if self.type is not convert_to_datatype(self._field_object.type):
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
        type_ = convert_to_datatype(type_)
        return cls(
            name=name,
            row_frequency=delta.get("row_frequency", command.operates_on),
            type=type_,
            field=delta.get("field", name),
            help=delta.get("help", obj.help),
            field_object=obj,
            operates_on=command.operates_on,
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
            if isinstance(src, str):
                src = {"field": src}
            elif src is None:
                src = {}
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
) -> dict[str, ContainerCommandSource]:
    return {s.name: s.asdict(**kwargs) for s in sources}


@attrs.define(kw_only=True, auto_attribs=False)
class ContainerCommandSink:
    """Define a sink for a container command."""

    name: str = attrs.field()
    type: type[DataType] = attrs.field()
    field: str = attrs.field()
    help: str = attrs.field()
    _field_object: Out = attrs.field(repr=False)

    @property
    def field_type(self) -> type[DataType]:
        return self._field_object.type

    def asdict(self, **kwargs: ty.Any) -> dict[str, ty.Any]:
        delta: dict[str, ty.Any] = {}
        if self.field != self.name:
            delta["field"] = self.field
        if self.type is not convert_to_datatype(self._field_object.type):
            delta["type"] = self.type
        if self.help != self._field_object.help:
            delta["help"] = self.help
        return delta

    @classmethod
    def fromdict(cls, name: str, delta: dict[str, ty.Any], command: "ContainerCommand"):
        obj = command._output_fields[delta.get("field", name)]
        type_ = delta.get("type", obj.type)
        if isinstance(type_, str):
            type_ = from_mime(type_)
        type_ = convert_to_datatype(type_)
        return cls(
            name=name,
            type=type_,
            field=delta.get("field", name),
            help=delta.get("help", obj.help),
            field_object=obj,
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
            if isinstance(snk, str):
                snk = {"field": snk}
            elif snk is None:
                snk = {}
            sink = ContainerCommandSink.fromdict(name, snk, self_)
        sink._field_object = self_._output_fields[sink.field]
        sinks.append(sink)
    return sinks


def parameters_serialiser(
    parameters: ty.List[ty.Any], **kwargs: ty.Any
) -> dict[str, ContainerCommandParameter]:
    return {p.name: p.asdict(**kwargs) for p in parameters}


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
