from __future__ import annotations
import shutil
import re
from copy import copy
import tempfile
import json
import inspect
import logging
from pathlib import Path
import typing as ty
import sys
from collections import defaultdict
import attrs
from attrs.converters import default_if_none
import pydra.compose.base
from fileformats.core import DataType, Field
from pydra.utils import get_fields, structure, unstructure
import pydra.utils.general
from pydra.utils.typing import optional_type
from pydra.compose.base import Arg, Out
from frametree.core.exceptions import FrametreeCannotSerializeDynamicDefinitionError
from pydra.utils.typing import is_fileset_or_union
from frametree.core.serialize import ClassResolver
from frametree.core.utils import show_workflow_errors, path2label
from frametree.core.row import DataRow
from frametree.core.frameset.base import FrameSet
from frametree.core.store import Store
from frametree.core.axes import Axes
from pydra2app.core.exceptions import Pydra2AppUsageError
from pydra2app.core import PACKAGE_NAME


if ty.TYPE_CHECKING:
    from ..image import App


logger = logging.getLogger("pydra2app")

DEFAULT_TASK_NAME = "ContainerCommandTask"


def task_converter(
    task_class: str | dict[str, ty.Any],
) -> type[pydra.compose.base.Task]:

    task_cls: type[pydra.compose.base.Task]

    if isinstance(task_class, str):
        task_cls = ClassResolver(  # type: ignore[misc]
            pydra.compose.base.Task,
            alternative_types=[ty.Callable],
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
) -> tuple[str, pydra.utils.general._TaskFields]:
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
class ContainerCommand:
    """A definition of a command to be run within a container. A command wraps up a
    task or workflow to provide/configure a UI for convenient launching.

    Parameters
    ----------
    task : pydra.compose.base.Task or str
        the task to run or the location of the class
    row_frequency: Axes, optional
        the frequency that the command operates on
    parameters: list[str], optional
        inputs of the task to be treated as fixed parameters entered
        by the user (i.e. rather than drawn from the data store). By default,
        any non-file task input is considered a parameter, however, if a list of
        parameters is provided then only those inputs will be treated as parameters
        and any non-file inputs will be treated as fields to be pulled from metadata.
        File inputs marked as parameters will be treated as paths to local files (i.e.
        outside of the store) or URLs to be downloaded from the web depending on their
        format.
    configuration: ty.Dict[str, ty.Any]
        constant values used to configure the task/workflow, i.e. not presented to the
        user.
    image: App
        back-reference to the image the command is installed in
    """

    STORE_TYPE = "file_system"
    AXES: ty.Optional[ty.Type[Axes]] = None

    task: type[pydra.compose.base.Task] = attrs.field(
        converter=task_converter,
        metadata={"serializer": task_serializer},
        eq=task_equals,
    )
    name: str = attrs.field()
    row_frequency: ty.Optional[Axes] = attrs.field(default=None)
    configuration: ty.Dict[str, ty.Any] = attrs.field(
        factory=dict, converter=default_if_none(dict)  # type: ignore[misc]
    )
    parameters: ty.List[str] = attrs.field(converter=list)
    image: App = attrs.field(
        default=None, eq=False, hash=False, metadata={"asdict": False}
    )

    @name.default
    def _default_name(self) -> str:
        return self.task.__name__

    @parameters.default
    def _default_parameters(self) -> ty.List[str]:
        """By default, any non-file task input is considered a parameter that is not
        fixed in the configuration"""
        return [
            i.name
            for i in get_fields(self.task)
            if not (
                i.name == self.task._executor_name
                or is_fileset_or_union(i.type)
                or i.type is DataRow
                or i.name in self.configuration
                or isinstance(i, Out)
            )
        ]

    @parameters.validator
    def _validate_parameters(
        self, attribute: attrs.Attribute[ty.Any], value: ty.List[str]
    ) -> None:
        """Validates that the parameters are valid task inputs"""
        task_inputs = [i.name for i in get_fields(self.task)]
        for param in value:
            if param not in task_inputs:
                raise ValueError(
                    f"Parameter '{param}' is not a valid input to task {self.task}"
                )
            if param in self.configuration:
                raise ValueError(
                    f"Parameter '{param}' cannot be both a parameter and a configuration "
                    "argument"
                )

    @configuration.validator
    def _validate_configuration(
        self, attribute: attrs.Attribute[ty.Any], value: ty.Dict[str, ty.Any]
    ) -> None:
        """Validates that the configuration arguments are valid task inputs"""
        task_inputs = [i.name for i in get_fields(self.task)]
        for param in value:
            if param not in task_inputs:
                raise ValueError(
                    f"Configuration argument '{param}' is not a valid input to task "
                    f"{self.task}"
                )

    def __attrs_post_init__(self) -> None:
        if isinstance(self.row_frequency, Axes):
            pass
        elif isinstance(self.row_frequency, str):
            try:
                self.row_frequency = Axes.fromstr(self.row_frequency)
            except ValueError:
                if self.AXES:
                    self.row_frequency = self.AXES[self.row_frequency]
                else:
                    raise ValueError(
                        f"'{self.row_frequency}' row frequency cannot be resolved to a axes, "
                        "needs to be of form <axes>[<row-frequency>]"
                    )
        elif self.AXES:
            self.row_frequency = self.AXES.default()
        else:
            raise ValueError(
                f"Value for row_frequency must be provided to {type(self).__name__}.__init__ "
                "because it doesn't have a defined AXES class attribute"
            )

    @property
    def inputs(self) -> ty.List[str]:
        """The inputs to the task"""
        non_inputs = (
            self.parameters + list(self.configuration) + [self.task._executor_name]
        )
        return [
            f.name
            for f in get_fields(self.task)
            if f.name not in non_inputs and not isinstance(f, Out)
        ]

    @property
    def outputs(self) -> ty.List[str]:
        """The outputs of the task"""
        return [o.name for o in get_fields(self.task.Outputs)]

    @property
    def input_fields(self) -> ty.List[Arg]:
        fields = get_fields(self.task)
        return [fields[i] for i in self.inputs if fields[i].type is not DataRow]

    @property
    def output_fields(self) -> ty.List[Out]:
        fields = get_fields(self.task.Outputs)
        return [fields[i] for i in self.outputs]

    @property
    def parameter_fields(self) -> ty.List[Arg]:
        fields = get_fields(self.task)
        return [fields[p] for p in self.parameters]

    def input_field(self, name: str) -> Arg:
        if name not in self.inputs:
            raise ValueError(
                f"Input field '{name}' is not a valid input to task {self.task} "
                f"(available: {self.inputs})"
            )
        return get_fields(self.task)[name]

    def output_field(self, name: str) -> Arg:
        if name not in self.outputs:
            raise ValueError(
                f"Input field '{name}' is not a valid output of task {self.task} "
                f"(available: {self.outputs})"
            )
        return get_fields(self.task.Outputs)[name]

    def parameter_field(self, name: str) -> Arg:
        if name not in self.parameters:
            raise ValueError(
                f"Input field '{name}' is not a valid output of task {self.task} "
                f"(available: {self.parameters})"
            )
        return get_fields(self.task)[name]

    @property
    def axes(self) -> ty.Type[Axes]:
        return type(self.row_frequency)

    def configuration_args(self) -> ty.List[str]:

        # Set up fixed arguments used to configure the workflow at initialisation
        cmd_args = []
        if self.configuration is not None:
            for cname, cvalue in self.configuration.items():
                cvalue_json = json.dumps(cvalue)
                cmd_args.append(f"--configuration {cname} '{cvalue_json}' ")

        return cmd_args

    def license_args(self) -> ty.List[str]:
        cmd_args = []
        if self.image:
            for lic in self.image.licenses:
                if lic.source is None:
                    cmd_args.append(f"--download-license {lic.name} {lic.destination}")
        return cmd_args

    def execute(
        self,
        address: str,
        input_values: ty.Optional[ty.Dict[str, str]] = None,
        output_values: ty.Optional[ty.Dict[str, str]] = None,
        parameter_values: ty.Optional[ty.Dict[str, ty.Any]] = None,
        work_dir: ty.Optional[Path] = None,
        ids: ty.Union[ty.List[str], str, None] = None,
        dataset_hierarchy: ty.Optional[str] = None,
        dataset_name: ty.Optional[str] = None,
        overwrite: bool = False,
        loglevel: str = "warning",
        worker: ty.Optional[str] = None,
        export_work: ty.Optional[Path] = None,
        raise_errors: bool = False,
        keep_running_on_errors: bool = False,
        pipeline_name: ty.Optional[str] = None,
        **store_kwargs: ty.Any,
    ) -> None:
        """Runs the command within the entrypoint of the container image.

        Performs a number of steps in one long pipeline that would typically be done
        in separate command calls when running manually, i.e.:

            * Loads a dataset, creating if it doesn't exist
            * create input and output columns if they don't exist
            * applies the pipeline to the dataset
            * runs the pipeline

        Parameters
        ----------
        dataset : FrameSet
            dataset ID str (<store-nickname>//<dataset-id>:<dataset-name>)
        input_values : dict[str, str]
            values passed to the inputs of the command
        output_values : dict[str, str]
            values passed to the outputs of the command
        parameter_values : dict[str, ty.Any]
            values passed to the parameters of the command
        store_cache_dir : Path
            cache path used to download data from the store to the working node (if necessary)
        pipeline_cache_dir : Path
            cache path created when running the pipelines
        plugin : str
            Pydra plugin used to execute the pipeline
        ids : list[str]
            IDs of the dataset rows to run the pipeline over
        overwrite : bool, optional
            overwrite existing outputs
        export_work : Path
            export work directory to an alternate location after the workflow is run
            (e.g. for forensics)
        raise_errors : bool
            raise errors instead of capturing and logging (for debugging)
        pipeline_name : str
            the name to give to the pipeline, defaults to the name of the command image
        **store_kwargs: Any
            keyword args passed through to Store.load
        """
        if input_values is None:
            input_values = {}
        elif not isinstance(input_values, dict):
            input_values = dict(input_values)
        if output_values is None:
            output_values = {}
        elif not isinstance(output_values, dict):
            output_values = dict(output_values)
        if parameter_values is None:
            parameter_values = {}
        elif not isinstance(parameter_values, dict):
            parameter_values = dict(parameter_values)

        if unrecognised := set(input_values) - set(self.inputs):
            raise ValueError(
                f"Unrecognised input values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={list(self.inputs)}\n"
            )
        if unrecognised := set(output_values) - set(self.outputs):
            raise ValueError(
                f"Unrecognised output values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={list(self.outputs)}\n"
            )

        if unrecognised := set(parameter_values) - set(self.parameters):
            raise ValueError(
                f"Unrecognised parameter values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={list(self.parameters)}\n"
            )

        if missing := set(i.name for i in self.input_fields if i.mandatory) - set(
            n
            for n, v in input_values.items()
            if v or (v == "" and self.input_field(n).type is str)
        ):
            raise ValueError(
                f"Missing mandatory input values passed to command {self.name}:\n"
                f"missing={missing}\n"
            )

        if missing := set(p.name for p in self.parameter_fields if p.mandatory) - set(
            n
            for n, v in parameter_values.items()
            if v or (v == "" and self.parameter_field(n).type is str)
        ):
            raise ValueError(
                f"Missing mandatory parameter values passed to command {self.name}:\n"
                f"missing={missing}\n"
            )

        if isinstance(export_work, bytes):
            export_work = Path(export_work.decode("utf-8"))

        if loglevel != "none":
            logging.basicConfig(
                stream=sys.stdout, level=getattr(logging, loglevel.upper())
            )

        if work_dir is None:
            work_dir = Path(tempfile.mkdtemp())

        if pipeline_name is None:
            pipeline_name = self.name

        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        store_cache_dir = work_dir / "store-cache"
        pipeline_cache_dir = work_dir / "pydra"

        frameset = self.load_frameset(
            address, store_cache_dir, dataset_hierarchy, dataset_name, **store_kwargs
        )

        # Install required software licenses from store into container
        if self.image is not None:
            frameset.download_licenses(
                [lic for lic in self.image.licenses if not lic.store_in_image]
            )

        input_values = dict(input_values) if input_values else {}
        output_values = dict(output_values) if output_values else {}
        parameter_values = dict(parameter_values) if parameter_values else {}

        converter_args = {}  # Arguments passed to converter
        pipeline_inputs = []
        for input_name in self.inputs:
            inpt = self.input_field(input_name)
            if inpt.type is DataRow:
                pipeline_inputs.append(("frametree_data_row__", inpt.name, inpt.type))
                continue
            input_path = input_values.get(input_name, None)
            if not input_path:
                assert not inpt.mandatory, "missing " + input_name
                logger.info("No value provided for input '%s', skipping", input_name)
                continue

            path, qualifiers = self.extract_qualifiers_from_path(input_path)
            source_kwargs = qualifiers.pop("criteria", {})
            if match := re.match(r"<(\w+)(@\w+)?>", path):
                column_name = match.group(1)
                if frameset_qualifier := match.group(2):
                    source_frameset = frameset.store[frameset_qualifier[1:]]
                    column = source_frameset[column_name]
                else:
                    column = frameset[column_name]
                logger.info(f"Found existing source column {column}")
            else:
                default_column_name = f"{path2label(self.name)}_{input_name}"
                try:
                    column = frameset[default_column_name]
                except KeyError:
                    logger.info(f"Adding new source column '{default_column_name}'")
                    datatype = (
                        Field.from_primitive(inpt.type)
                        if inspect.isclass(inpt.type)
                        and not issubclass(inpt.type, DataType)
                        else inpt.type.convertible_from()
                    )  # TODO: Create a union of all the convertible datatypes for FileSet types
                    column = frameset.add_source(
                        name=default_column_name,
                        datatype=datatype,
                        path=path,
                        is_regex=True,
                        **source_kwargs,
                    )
                else:
                    logger.info("Found existing source column %s", default_column_name)

            pipeline_inputs.append((column.name, inpt.name, inpt.type))
            converter_args[column.name] = qualifiers.pop("converter", {})
            if qualifiers:
                raise Pydra2AppUsageError(
                    "Unrecognised qualifier namespaces extracted from path for "
                    f"{inpt.name} (expected ['criteria', 'converter']): {qualifiers}"
                )

        pipeline_outputs = []
        for output_name in self.outputs:
            output = self.output_field(output_name)
            output_path = output_values.get(output_name, None)
            if not output_path:
                logger.info("No value provided for output '%s', skipping", output_name)
                continue
            path, qualifiers = self.extract_qualifiers_from_path(output_path)
            if "@" not in path:
                path = f"{path}@{frameset.name}"  # Add dataset namespace
            sink_name = path2label(path)
            if sink_name in frameset.columns:
                column = frameset[sink_name]
                if not column.is_sink:
                    raise Pydra2AppUsageError(
                        f"Output column name '{sink_name}' shadows existing source column"
                    )
                logger.info(f"Found existing sink column {column}")
            else:
                logger.info(f"Adding new source column '{sink_name}'")
                datatype = (
                    Field.from_primitive(output.type)
                    if not issubclass(output.type, DataType)
                    else output.type
                )
                frameset.add_sink(
                    name=sink_name,
                    datatype=datatype,
                    path=path,
                )
            pipeline_outputs.append((sink_name, output.name, output.type))
            converter_args[sink_name] = qualifiers.pop("converter", {})
            if qualifiers:
                raise Pydra2AppUsageError(
                    "Unrecognised qualifier namespaces extracted from path for "
                    f"{output_name} (expected ['criteria', 'converter']): {qualifiers}"
                )

        # if not pipeline_outputs and task_outputs:
        #     raise ValueError(
        #         f"No output values provided to command {self} "
        #         f"(available: {list(task_outputs.keys())})"
        #     )

        frameset.save()  # Save definitions of the newly added columns

        task_kwargs = copy(self.configuration)
        for param_name, param_value in parameter_values.items():
            param = self.parameter_field(param_name)
            logger.info(
                "Parameter %s (type %s) passed value %s",
                param_name,
                param.type,
                param_value,
            )
            if param.type is not str:
                if param_value == "":
                    assert not param.mandatory
                    param_value = None
                    logger.info(
                        "Non-string parameter '%s' passed empty string, setting to None",
                        param_name,
                    )
                else:
                    # Convert field from string if necessary
                    field_type = optional_type(param.type)
                    try:
                        field_type = Field.from_primitive(field_type)
                    except TypeError:
                        pass
                    param_value = field_type(param_value)

            task_kwargs[param_name] = param_value

        task = self.task(**task_kwargs)

        if pipeline_name in frameset.pipelines and not overwrite:
            pipeline = frameset.pipelines[self.name]
            if task != pipeline.task:
                raise RuntimeError(
                    f"A pipeline named '{self.name}' has already been applied to "
                    "which differs from one specified. Please use '--overwrite' option "
                    "if this is intentional"
                )
        else:
            pipeline = frameset.apply(
                pipeline_name,
                task,
                inputs=pipeline_inputs,
                outputs=pipeline_outputs,
                row_frequency=self.row_frequency,
                overwrite=overwrite,
                converter_args=converter_args,
            )

        if isinstance(ids, str):
            ids = ids.split(",")

        # Instantiate the Pydra workflow
        wf = pipeline(ids=ids)

        # execute the workflow
        try:
            outputs = wf(cache_root=pipeline_cache_dir, worker=worker)
        except RuntimeError:
            msg = show_workflow_errors(
                pipeline_cache_dir, omit_nodes=["per_node", "main"]
            )
            logger.error(
                "Pipeline failed with errors for the following nodes:\n\n%s", msg
            )
            if raise_errors or not msg:
                raise
            else:
                errors = True
        else:
            logger.info(
                "Pipeline '%s' ran successfully for the following data rows:\n%s",
                pipeline_name,
                "\n".join(outputs.processed),
            )
            errors = False
        finally:
            if export_work:
                logger.info("Exporting work directory to '%s'", export_work)
                export_work.mkdir(parents=True, exist_ok=True)
                shutil.copytree(pipeline_cache_dir, export_work / "pydra")

        # Abort at the end after the working directory can be copied back to the
        # host so that XNAT knows there was an error
        if errors:
            if keep_running_on_errors:
                while True:
                    pass
            else:
                sys.exit(1)

    @classmethod
    def extract_qualifiers_from_path(
        cls, user_input: str
    ) -> ty.Tuple[str, ty.Dict[str, ty.Any]]:
        """Extracts out "qualifiers" from the user-inputted paths. These are
        in the form 'path ns1.arg1=val1 ns1.arg2=val2, ns2.arg1=val3...

        Parameters
        ----------
        col_name : str
            name of the column the
        user_input : str
            The path expression + qualifying keyword args to extract

        Returns
        -------
        path : str
            the path expression stripped of qualifiers
        qualifiers : defaultdict[dict]
            the extracted qualifiers
        """
        qualifiers: ty.Dict[str, ty.Any] = defaultdict(dict)
        if "=" in user_input:  # Treat user input as containing qualifiers
            parts = re.findall(r'(?:[^\s"]|"(?:\\.|[^"])*")+', user_input)
            path = parts[0].strip('"')
            for part in parts[1:]:
                try:
                    full_name, val = part.split("=", maxsplit=1)
                except ValueError as e:
                    e.args = ((e.args[0] + f" attempting to split '{part}' by '='"),)
                    raise e
                try:
                    ns, name = full_name.split(".", maxsplit=1)
                except ValueError as e:
                    e.args = (
                        (e.args[0] + f" attempting to split '{full_name}' by '.'"),
                    )
                    raise e
                try:
                    val = json.loads(val)
                except json.JSONDecodeError:
                    pass
                qualifiers[ns][name] = val
        else:
            path = user_input
        return path, qualifiers

    def load_frameset(
        self,
        address: str,
        cache_dir: Path,
        dataset_hierarchy: ty.Optional[str],
        dataset_name: ty.Optional[str],
        **kwargs: ty.Any,
    ) -> FrameSet:
        """Loads a dataset from within an image, to be used in image entrypoints

        Parameters
        ----------
        address : str
            dataset ID str
        cache_dir : Path
            the directory to use for the store cache
        dataset_hierarchy : str, optional
            the hierarchy of the dataset
        dataset_name : str
            overwrite dataset name loaded from ID str
        **kwargs: Any
            passed through to Store.load

        Returns
        -------
        _type_
            _description_
        """
        try:
            dataset = FrameSet.load(address, **kwargs)
        except KeyError:

            store_name, id, name = FrameSet.parse_id_str(address)

            if dataset_name is not None:
                name = dataset_name

            store = Store.load(store_name, cache_dir=cache_dir, **kwargs)

            if dataset_hierarchy is None:
                hierarchy = self.axes.default().span()
            else:
                hierarchy = dataset_hierarchy.split(",")

            try:
                dataset = store.load_frameset(
                    id, name
                )  # FIXME: Does this need to be here or this covered by L253??
            except KeyError:
                dataset = store.define_frameset(id, hierarchy=hierarchy, axes=self.axes)
        return dataset
