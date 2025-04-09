from __future__ import annotations
import shutil
import re
from copy import copy
import tempfile
import json
import logging
from pathlib import Path
from importlib import import_module
import typing as ty
import sys
from collections import defaultdict
import attrs
from attrs.converters import default_if_none
import pydra.compose.base
from fileformats.core import DataType, Field
from pydra.utils import task_fields
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


def task_converter(task_def: str | dict[str, ty.Any]) -> type[pydra.compose.base.Task]:

    task_cls: type[pydra.compose.base.Task]

    if isinstance(task_def, str):
        task_cls = ClassResolver(  # type: ignore[misc]
            pydra.compose.base.Task,
            alternative_types=[ty.Callable],
            package=PACKAGE_NAME,
        )(task_def)
    elif isinstance(task_def, dict):
        task_def = copy(task_def)
        task_type = task_def.pop("type")
        define = import_module(f"pydra.compose.{task_type}").define
        if task_type == "python":
            executor = task_def.pop("function")
        elif task_type == "shell":
            executor = task_def.pop("executable")
        elif task_type == "workflow":
            executor = task_def.pop("constructor")
        else:
            raise ValueError(f"Unreognised task type '{task_type}'")
        task_cls = define(executor, **task_def, name=DEFAULT_TASK_NAME)
    elif isinstance(task_def, pydra.compose.base.Task):
        task_cls = task_def
    else:
        raise TypeError(f"Cannot convert {type(task_def)} ({task_def}) to a task")
    return task_cls


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
    inputs: ty.List[CommandInput]
        inputs of the command
    outputs: ty.List[CommandOutput]
        outputs of the command
    parameters: ty.List[CommandParameter]
        parameters of the command
    configuration: ty.Dict[str, ty.Any]
        constant values used to configure the task/workflow
    image: App
        back-reference to the image the command is installed in
    """

    STORE_TYPE = "file_system"
    AXES: ty.Optional[ty.Type[Axes]] = None

    name: str = attrs.field()
    task: type[pydra.compose.base.Task] = attrs.field(converter=task_converter)
    row_frequency: ty.Optional[Axes] = attrs.field(default=None)
    inputs: ty.List[str] = attrs.field()
    parameters: ty.List[str] = attrs.field()
    configuration: ty.Dict[str, ty.Any] = attrs.field(
        factory=dict, converter=default_if_none(dict)  # type: ignore[misc]
    )
    image: App = attrs.field(default=None)

    @inputs.default
    def _default_inputs(self) -> ty.List[str]:
        return [
            i.name
            for i in task_fields(self.task)
            if is_fileset_or_union(i.type) or i.type is DataRow
        ]

    @parameters.default
    def _default_parameters(self) -> ty.List[str]:
        return [i.name for i in task_fields(self.task) if i.name not in self.inputs]

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
        plugin: ty.Optional[str] = None,
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
        task_inputs = task_fields(self.task)
        for input_name, input_path in input_values.items():
            if not input_path:
                logger.info("No value provided for input '%s', skipping", input_name)
                continue
            inpt = task_inputs[input_name]
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
                        if not issubclass(inpt.type, DataType)
                        else inpt.type
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

        pipeline_inputs.extend(
            ("frametree_data_row__", i.name, i.type)
            for i in task_inputs
            if i.type is DataRow
        )

        if not pipeline_inputs:
            raise ValueError(
                f"No input values provided to command {self.name} "
                f"(available: {list(task_inputs.keys())})"
            )

        pipeline_outputs = []
        task_outputs = task_fields(self.task.Outputs)
        for output_name, output_path in output_values.items():
            output = task_outputs[output_name]
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
            param = task_inputs[param_name]
            logger.info(
                "Parameter %s (type %s) passed value %s",
                param_name,
                param.type,
                param_value,
            )
            if param.type is not str:
                if param_value == "":
                    param_value = None
                    logger.info(
                        "Non-string parameter '%s' passed empty string, setting to None",
                        param_name,
                    )
                else:
                    # Convert field from string if necessary
                    param_value = Field.from_primitive(param.type)(param_value)

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
            outputs = wf(cache_root=pipeline_cache_dir, worker=plugin)
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
