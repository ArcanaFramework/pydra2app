from __future__ import annotations
import shutil
import re
from copy import copy
import tempfile
import json
import logging
from pathlib import Path
import typing as ty
from functools import cached_property
import sys
from collections import defaultdict
import attrs
from attrs.converters import default_if_none
import pydra.compose.base
from fileformats.core import Field
from pydra.utils import get_fields, unstructure
import pydra.utils.general
from pydra.compose.base import Out
from pydra.utils.typing import (
    optional_type,
    is_fileset_or_union,
)
from frametree.core.utils import show_workflow_errors, path2label
from frametree.core.row import DataRow
from frametree.core.frameset.base import FrameSet
from frametree.core.store import Store
from frametree.core.axes import Axes
from pydra2app.core.exceptions import Pydra2AppUsageError
from pydra2app.core import PACKAGE_NAME
from .components import (
    ContainerCommandSource,
    ContainerCommandSink,
    ContainerCommandParameter,
    sources_converter,
    sinks_converter,
    parameters_converter,
    sources_serialiser,
    sinks_serialiser,
    parameters_serialiser,
    task_converter,
    task_serializer,
    task_equals,
)

if ty.TYPE_CHECKING:
    from ..image import App

logger = logging.getLogger("pydra2app")


@attrs.define(kw_only=True, auto_attribs=False)
class ContainerCommand:
    """A definition of a command to be run within a container. A command wraps up a
    task or workflow to provide/configure a UI for convenient launching.

    Parameters
    ----------
    task : pydra.compose.base.Task or str
        the task to run or the location of the class
    operates_on: Axes, optional
        the frequency that the command operates on
    sources : dict[str, Axes]
        the inputs of the task that are to be sourced from the data store,
        as opposed to those hard-coded in the configuration dict and those
        presented as user-settable parameters.
    sinks : list[str]
        the outputs of the task that are to be stored in the data store, omitted
        outputs are ignored
    configuration: ty.Dict[str, ty.Any]
        constant values used to configure the task/workflow, i.e. not presented to the
        user.
    image: App
        back-reference to the image the command is installed in
    save_frameset : bool
        Whether to save the frameset definition by default (can be overridden by flags passed
        to the command)
    """

    STORE_TYPE = "file_system"
    AXES: type[Axes] | None = None

    task: type[pydra.compose.base.Task] = attrs.field(
        converter=task_converter,
        metadata={"serializer": task_serializer},
        eq=task_equals,
    )
    name: str = attrs.field()
    operates_on: Axes = attrs.field()
    configuration: dict[str, ty.Any] = attrs.field(
        factory=dict, converter=default_if_none(dict)  # type: ignore[misc]
    )
    sources: list[ContainerCommandSource] = attrs.field(
        converter=attrs.Converter(  # type: ignore[call-overload]
            sources_converter, takes_self=True
        ),
        metadata={"serializer": sources_serialiser},
    )
    sinks: list[ContainerCommandSink] = attrs.field(
        converter=attrs.Converter(  # type: ignore[call-overload]
            sinks_converter, takes_self=True
        ),
        metadata={"serializer": sinks_serialiser},
    )
    parameters: list[ContainerCommandParameter] = attrs.field(
        converter=attrs.Converter(  # type: ignore[call-overload]
            parameters_converter, takes_self=True
        ),
        metadata={"serializer": parameters_serialiser},
    )
    # parameters: list[str] = attrs.field(converter=list)
    image: App = attrs.field(
        default=None, eq=False, hash=False, metadata={"asdict": False}
    )
    save_frameset: bool = False

    @name.default  # pyright: ignore[reportAttributeAccessIssue]
    def _default_name(self) -> str:
        return self.task.__name__

    @operates_on.default  # pyright: ignore[reportAttributeAccessIssue, reportCallIssue]
    def _default_operates_on(self) -> Axes:
        if self.AXES is None:
            raise ValueError(
                f"No default AXES has been defined for ({type(self)}) therefore 'operates_on' must be provided"
            )
        return self.AXES.default()  # type: ignore[union-attr]

    @sources.default  # pyright: ignore[reportAttributeAccessIssue]
    def _default_sources(self) -> list[str]:
        return [  # pyright: ignore[reportReturnType]
            i.name
            for i in self._input_fields
            if (
                is_fileset_or_union(i.type)
                and i.name not in self.configuration
                and not isinstance(i, Out)
            )
        ]

    @sinks.default  # pyright: ignore[reportAttributeAccessIssue]
    def _default_sinks(self) -> list[str]:
        return [  # pyright: ignore[reportReturnType]
            o.name for o in self._output_fields if is_fileset_or_union(o.type)
        ]

    @parameters.default  # pyright: ignore[reportAttributeAccessIssue]
    def _default_parameters(self) -> list[str]:
        non_parameters = (
            self.source_names + list(self.configuration) + [self.task._executor_name]
        )
        return [  # pyright: ignore[reportReturnType]
            i.name
            for i in self._input_fields
            if not (i.name in non_parameters or i.type is DataRow or isinstance(i, Out))
        ]

    @sources.validator  # pyright: ignore[reportAttributeAccessIssue]
    def _validate_sources(
        self, _: attrs.Attribute[ty.Any], sources: ty.List[ContainerCommandSource]
    ) -> None:
        """Validates that the sources are valid task inputs"""
        for source in sources:
            if source.name in self.configuration:
                raise ValueError(
                    f"Source '{source}' cannot be both a source and a configuration "
                    "argument"
                )

    @parameters.validator  # pyright: ignore[reportAttributeAccessIssue]
    def _validate_parameters(
        self, _: attrs.Attribute[ty.Any], parameters: ty.List[ContainerCommandParameter]
    ) -> None:
        """Validates that the parameters are valid task inputs"""
        for param in parameters:
            if param.name in self.configuration:
                raise ValueError(
                    f"Parameter '{param}' cannot be both a parameter and a configuration "
                    "argument"
                )
            if param.name in self.source_names:
                raise ValueError(
                    f"Parameter '{param}' cannot be both a parameter and a source "
                    "argument"
                )

    @configuration.validator  # pyright: ignore[reportAttributeAccessIssue]
    def _validate_configuration(
        self, attribute: attrs.Attribute[ty.Any], configuration: ty.Dict[str, ty.Any]
    ) -> None:
        """Validates that the configuration arguments are valid task inputs"""
        task_inputs = [i.name for i in self._input_fields]
        for param in configuration:
            if param not in task_inputs:
                raise ValueError(
                    f"Configuration argument '{param}' is not a valid input to task "
                    f"{self.task}"
                )

    @cached_property
    def _input_fields(self) -> pydra.utils.general._TaskFieldsList:
        return get_fields(self.task)

    @cached_property
    def _output_fields(self) -> pydra.utils.general._TaskFieldsList:
        return get_fields(self.task.Outputs)

    def __attrs_post_init__(self) -> None:
        if isinstance(self.operates_on, Axes):
            pass
        elif isinstance(self.operates_on, str):
            try:
                self.operates_on = Axes.fromstr(self.operates_on)
            except ValueError:
                if self.AXES:
                    self.operates_on = self.AXES[self.operates_on]
                else:
                    raise ValueError(
                        f"'{self.operates_on}' row frequency cannot be resolved to a axes, "
                        "needs to be of form <axes>[<row-frequency>]"
                    )
        elif self.AXES:
            self.operates_on = self.AXES.default()
        else:
            raise ValueError(
                f"Value for row_frequency must be provided to {type(self).__name__}.__init__ "
                "because it doesn't have a defined AXES class attribute"
            )

    @property
    def source_names(self) -> list[str]:
        return [s.name for s in self.sources]

    @property
    def sink_names(self) -> list[str]:
        return [s.name for s in self.sinks]

    @property
    def parameter_names(self) -> list[str]:
        return [p.name for p in self.parameters]

    def source(self, name: str) -> ContainerCommandSource:
        try:
            return next(s for s in self.sources if s.name == name)
        except StopIteration:
            raise ValueError(
                f"Input field '{name}' is not a source name of {self}"
                f"(available: {self.source_names})"
            )

    def sink(self, name: str) -> ContainerCommandSink:
        try:
            return next(s for s in self.sinks if s.name == name)
        except StopIteration:
            raise ValueError(
                f"Input field '{name}' is not a sink name of {self}"
                f"(available: {self.sink_names})"
            )

    def parameter(self, name: str) -> ContainerCommandParameter:
        try:
            return next(p for p in self.parameters if p.name == name)
        except StopIteration:
            raise ValueError(
                f"Input field '{name}' is not a valid output of task {self.task} "
                f"(available: {self.parameter_names})"
            )

    @property
    def axes(self) -> ty.Type[Axes]:
        return type(self.operates_on)

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
        save_frameset: bool = False,
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
        address : str
            the address of the dataset/frameset, i.e. <store-nickname>//<dataset-id>:<dataset-name>
        input_values : dict[str, str]
            values passed to the inputs of the command
        output_values : dict[str, str]
            values passed to the outputs of the command
        parameter_values : dict[str, ty.Any]
            values passed to the parameters of the command
        work_dir : Path, optional
            the working directory for the command
        store_cache_dir : Path
            cache path used to download data from the store to the working node (if necessary)
        pipeline_cache_dir : Path
            cache path created when running the pipelines
        plugin : str
            Pydra plugin used to execute the pipeline
        ids : list[str] | None
            IDs of the dataset rows to run the pipeline over,
        overwrite : bool, optional
            overwrite existing outputs
        export_work : Path
            export work directory to an alternate location after the workflow is run
            (e.g. for forensics)
        raise_errors : bool
            raise errors instead of capturing and logging (for debugging)
        pipeline_name : str
            the name to give to the pipeline, defaults to the name of the command image
        save_frameset : bool
            Save the frameset definition that is used to run the pipeline
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
        if isinstance(ids, str):
            ids = ids.split(",")
        # Check whether save_frameset is set at the command specification level
        save_frameset |= self.save_frameset

        if unrecognised := set(input_values) - set(self.source_names):
            raise ValueError(
                f"Unrecognised input values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={self.source_names}\n"
            )
        if unrecognised := set(output_values) - set(self.sink_names):
            raise ValueError(
                f"Unrecognised output values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={self.sink_names}\n"
            )

        if unrecognised := set(parameter_values) - set(self.parameter_names):
            raise ValueError(
                f"Unrecognised parameter values passed to command {self.name}:\n"
                f"unrecognised={unrecognised}\n"
                f"available={self.parameter_names}\n"
            )

        if missing := set(s.name for s in self.sources if s.mandatory) - set(
            n
            for n, v in input_values.items()
            if v or (v == "" and self.source(n).type is str)
        ):
            raise ValueError(
                f"Missing mandatory input values passed to command {self.name}:\n"
                f"missing={missing}\n"
            )

        if missing := set(p.name for p in self.parameters if p.mandatory) - set(
            n
            for n, v in parameter_values.items()
            if v or (v == "" and self.parameter(n).type is str)
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

        load_kwargs = copy(store_kwargs)

        # If the frameset isn't being saved and all the sources are at the same
        # frequency as the command operates on, only load those rows that are to be
        # processed
        if (
            all(Axes.fromstr(s.row_frequency) is self.operates_on for s in self.sources)
            and not save_frameset
            and ids is not None
        ):
            logger.info(
                "Defining emphemeral frameset restricted to %s of %s to avoid loading project",
                ids,
                self.operates_on,
            )
            store_cache_dir.mkdir(parents=True, exist_ok=True)
            store_name, dataset_id, _ = FrameSet.parse_id_str(address)
            store = Store.load(store_name, cache_dir=store_cache_dir)
            if dataset_hierarchy is None:
                hierarchy = self.axes.default().span()
            else:
                hierarchy = dataset_hierarchy.split(",")
            frameset = store.define_frameset(
                id=dataset_id,
                axes=self.axes,
                hierarchy=hierarchy,
                include={self.operates_on: ids},
            )
        else:
            logger.info(
                "Loading frameset without restrictions, save_frameset=%s, row_frequencies=%s",
                save_frameset,
                list(set(s.row_frequency for s in self.sources)),
            )

            frameset = self.load_frameset(
                address, store_cache_dir, dataset_hierarchy, dataset_name, **load_kwargs
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
        # Add inputs for data row objects if present
        for inpt in self._input_fields:
            if inpt.type is DataRow:
                pipeline_inputs.append(("frametree_data_row__", inpt.name, inpt.type))
        # Add inputs for sources
        for source in self.sources:
            input_path = input_values.get(source.name, None)
            if not input_path:
                assert not source.mandatory, "missing " + source.name
                logger.info("No value provided for input '%s', skipping", source.name)
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
                default_column_name = f"{path2label(self.name)}_{source.name}"
                try:
                    column = frameset[default_column_name]
                except KeyError:
                    logger.info(f"Adding new source column '{default_column_name}'")
                    column = frameset.add_source(
                        name=default_column_name,
                        datatype=source.type,
                        path=path,
                        is_regex=True,
                        **source_kwargs,
                    )
                else:
                    logger.info("Found existing source column %s", default_column_name)

            pipeline_inputs.append((column.name, source.field, source.field_type))
            converter_args[column.name] = qualifiers.pop("converter", {})
            if qualifiers:
                raise Pydra2AppUsageError(
                    "Unrecognised qualifier namespaces extracted from path for "
                    f"{source.name} (expected ['criteria', 'converter']): {qualifiers}"
                )

        pipeline_outputs = []
        for sink in self.sinks:
            output_path = output_values.get(sink.name, None)
            if not output_path:
                logger.info("No value provided for output '%s', skipping", sink.name)
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
                frameset.add_sink(
                    name=sink_name,
                    datatype=sink.type,
                    path=path,
                )
            pipeline_outputs.append((sink_name, sink.field, sink.field_type))
            converter_args[sink_name] = qualifiers.pop("converter", {})
            if qualifiers:
                raise Pydra2AppUsageError(
                    "Unrecognised qualifier namespaces extracted from path for "
                    f"{sink.name} (expected ['criteria', 'converter']): {qualifiers}"
                )

        # if not pipeline_outputs and task_outputs:
        #     raise ValueError(
        #         f"No output values provided to command {self} "
        #         f"(available: {list(task_outputs.keys())})"
        #     )

        if save_frameset:
            frameset.save()  # Save definitions of the newly added columns

        task_kwargs = copy(self.configuration)
        for param_name, param_value in parameter_values.items():
            param = self.parameter(param_name)
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
                row_frequency=self.operates_on,
                overwrite=overwrite,
                converter_args=converter_args,
            )

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
