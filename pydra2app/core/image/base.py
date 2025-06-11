from __future__ import annotations
import typing as ty
from pathlib import PurePath, Path, PosixPath
import json
import re
import tempfile
import requests
import itertools
from enum import Enum
from functools import cached_property
import logging
from copy import copy
import shutil
from inspect import isclass, isfunction
from build import ProjectBuilder
import attrs
import yaml
import docker.errors
from deepdiff import DeepDiff
from typing_extensions import Self
from neurodocker.reproenv import DockerRenderer
from pydra2app.core import __version__
from pydra2app.core import PACKAGE_NAME
from frametree.core.serialize import (
    ClassResolver,
    ObjectConverter,
    ObjectListConverter,
)
from frametree.core.axes import Axes
from pydra2app.core.utils import (
    DOCKER_HUB,
    GITHUB_CONTAINER_REGISTRY,
    extract_file_from_docker_image,
)
from pydra2app.core.exceptions import Pydra2AppBuildError
from .components import Packages, BaseImage, PipPackage, Resource, Version

logger = logging.getLogger("pydra2app")


@attrs.define(kw_only=True, auto_attribs=False)
class P2AImage:
    """
    Base class with Pydra2App installed within it from which all container image
    specifications can inherit from

    name : str
        name of the package/pipeline
    version : Version
        version of the package/pipeline
    org : str
        the organisation the image will be tagged within
    base_image : pydra2app.core.image.components.BaseImage, optional
        the base image to build from
    packages : Packages
        System (OS), PyPI, Conda and Neurodocker packages/templates to be installed
        in the image
    registry : str, optional
        the container registry the image is to be installed at
    readme : str, optional
        text to include in the image README file
    labels : dict[str, str]
        labels to add into the built image
    schema_version : str
        the version of the specification language used to define the image (i.e. this)
    """

    IN_DOCKER_FRAMETREE_HOME_DIR = "/frametree-home"
    IN_DOCKER_SPEC_PATH = "/pydra2app-spec.yaml"
    SCHEMA_VERSION = "2.0"
    PIP_DEPENDENCIES: ty.Tuple[str, ...] = ()
    DEFAULT_PYTHON_VERSION = "3.11"

    name: str = attrs.field()
    version: Version = attrs.field(
        converter=Version.parse, metadata={"serializer": Version.tostr}  # type: ignore[misc]
    )
    base_image: BaseImage = attrs.field(
        default=BaseImage(), converter=ObjectConverter(BaseImage)  # type: ignore[misc]
    )
    packages: Packages = attrs.field(
        default=Packages(), converter=ObjectConverter(Packages)  # type: ignore[misc]
    )
    resources: ty.List[Resource] = attrs.field(
        factory=list,
        converter=ObjectListConverter(Resource),  # type: ignore[misc]
        metadata={"serializer": ObjectListConverter.asdict},
    )
    org: ty.Optional[str] = attrs.field(default=None)
    registry: str = attrs.field(default=DOCKER_HUB)
    readme: ty.Optional[str] = attrs.field(default=None)
    labels: ty.Optional[ty.Dict[str, str]] = attrs.field(default=None)
    schema_version: str = attrs.field(default=SCHEMA_VERSION)
    access_token: ty.Optional[str] = attrs.field(default=None, repr=False)

    @property
    def reference(self) -> str:
        return f"{self.path}:{self.tag}"

    @property
    def tag(self) -> str:
        return str(self.version)

    @property
    def path(self) -> str:
        prefix = self.registry + "/" if self.registry != DOCKER_HUB else ""
        org_str = self.org + "/" if self.org else ""
        return (prefix + org_str + self.name).lower()

    def make(
        self,
        build_dir: ty.Optional[Path] = None,
        generate_only: bool = False,
        no_cache: bool = False,
        stream_output: ty.Optional[bool] = None,
        reference: ty.Optional[str] = None,
        **kwargs: ty.Any,
    ) -> None:
        """Makes the container image from the spec: generates the Dockerfile and then
        builds it.

        Parameters
        ----------
        build_dir : Path, optional
            _description_, by default None
        generate_only: bool, optional
            whether to only generate the Dockerfile and not build the image, by default
            False
        no_cache : bool, optional
            whether to cache the build layers or not, by default False
        stream_output : bool, optional
            whether to stream the output of the build process to stdout as it is being
            built. If None, the output will be streamed if the logger level is set to
            INFO or lower, by default None
        reference : str, optional
            the tag to assign to the built image, by default the one constructed from
            the image spec will be used
        **kwargs : Any
            additional keyword arguments to pass to the Dockerfile constructor
        """

        if build_dir is None:
            build_dir = Path(tempfile.mkdtemp())
        elif not isinstance(build_dir, Path):
            build_dir = Path(build_dir)
        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir()

        dockerfile = self.construct_dockerfile(build_dir, **kwargs)

        image_reference = reference if reference is not None else self.reference

        if generate_only:
            self.write_dockerfile(dockerfile, build_dir, image_reference)
        else:
            self.build(
                dockerfile,
                build_dir,
                image_reference=image_reference,
                no_cache=no_cache,
                stream_output=stream_output,
            )

    def registry_tags(self) -> ty.List[str]:
        """List all the tags for the given docker image reference within the registry"""
        tags: ty.List[str]
        if self.registry == DOCKER_HUB:
            url = f"https://hub.docker.com/v2/repositories/{self.org}/{self.name}/tags/"
            tags = []
            while url:
                response = requests.get(url)
                if response.status_code == 404:
                    return []
                elif response.status_code != 200:
                    response.raise_for_status()
                data = response.json()
                tags.extend(tag["name"] for tag in data["results"])
                url = data["next"]  # Get the URL for the next page of results
        elif self.registry == GITHUB_CONTAINER_REGISTRY:
            url = f"https://api.github.com/orgs/{self.org}/packages/container/{self.name}/versions"
            headers = {
                "Accept": "application/vnd.github.v3+json",
                "Authorization": f"Bearer {self.access_token}",
            }
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                response.raise_for_status()
            tags = [p["metadata"]["container"]["tags"][0] for p in response.json()]
        else:
            protocol = "http" if self.registry.startswith("localhost") else "https"
            url = f"{protocol}://{self.registry}/v2/{self.org}/{self.name}/tags/list"
            response = requests.get(url)
            if response.status_code == 404:
                return []
            elif response.status_code != 200:
                response.raise_for_status()
            tags = response.json().get("tags", [])
        return tags

    @cached_property
    def latest_published(self) -> ty.Optional[Version]:
        """Get the latest published version of the image from the registry"""
        published_tags = self.registry_tags()
        logger.info(
            "Found the following versions in the registry for '%s': %s",
            self.path,
            published_tags,
        )
        versions = sorted(Version.parse(t) for t in published_tags)
        return versions[-1] if versions else None

    def matches_image(self, image_reference: str) -> bool:
        """Check if the specifications of two images match"""
        try:
            extracted_specs_file = extract_file_from_docker_image(
                image_reference, PosixPath(self.IN_DOCKER_SPEC_PATH)
            )
        except docker.errors.NotFound:
            extracted_specs_file = None
        if extracted_specs_file is None:
            logger.warning(
                "Could not extract spec from existing image '%s' to check for changes "
                "assuming it is different",
                image_reference,
            )
            return False
        logger.info(
            "Comparing build spec with that of existing image %s",
            image_reference,
        )
        built_spec = self.load(extracted_specs_file)

        changelog = self.compare_specs(built_spec, check_versions=False)

        if changelog:
            logger.debug(
                "'%s' differs from existing image '%s':\n%s",
                self.reference,
                image_reference,
                changelog,
            )
            return False
        return True

    def construct_dockerfile(
        self,
        build_dir: Path,
        use_local_packages: bool = False,
        pypi_fallback: bool = False,
        pydra2app_install_extras: ty.Sequence[str] = (),
        resources: ty.Optional[ty.Dict[str, Path]] = None,
        resources_dir: ty.Optional[Path] = None,
        **kwargs: ty.Any,
    ) -> DockerRenderer:
        """Constructs a dockerfile that wraps a with dependencies

        Parameters
        ----------
        build_dir : Path
            Path to the directory the Dockerfile will be written into copy any local
            files to
        use_local_packages: bool, optional
            Use the python package versions that are installed within the
            current environment, i.e. instead of pulling from PyPI. Useful during
            development and testing
        pypi_fallback : bool, optional
            whether to fallback to packages installed on PyPI when versions of
            local packages don't match installed
        pydra2app_install_extras : Iterable[str], optional
            Extras for the Pydra2App package that need to be installed into the
            dockerfile (e.g. tests)
        resources : dict[str, Path], optional
            Resources to be copied into the docker image, keys of the dictionary should
            match resource names defined in the pipeline specification, values of the
            dictionary should be paths to the resources on the local filesystem to be
            copied into the docker image
        resources_dir : Path, optional
            Alternative to supplying the resources separately, a directory containing
            the resources to be copied into the docker image as named subdirectories
            can be provided

        Returns
        -------
        DockerRenderer
            Neurodocker Docker renderer to construct dockerfile from
        """

        if not build_dir.is_dir():
            raise Pydra2AppBuildError(
                f"Build dir '{str(build_dir)}' is not a valid directory"
            )

        build_dir = build_dir.absolute()

        dockerfile = self.init_dockerfile()

        dockerfile.user("root")

        self.install_system_packages(dockerfile)

        self.install_package_templates(dockerfile)

        self.install_python(
            dockerfile,
            build_dir,
            use_local_packages=use_local_packages,
            pypi_fallback=pypi_fallback,
            pydra2app_install_extras=pydra2app_install_extras,
        )

        self.add_resources(dockerfile, build_dir, resources, resources_dir)

        self.write_readme(dockerfile, build_dir)

        self.add_labels(dockerfile)

        self.insert_spec(dockerfile, build_dir)

        # Create writable directories
        for dpath in (self.IN_DOCKER_FRAMETREE_HOME_DIR, "/.cache"):
            dockerfile.run(f"mkdir {dpath}")
            dockerfile.run(f"chmod 777 {dpath}")
        dockerfile.env(FRAMETREE_HOME=self.IN_DOCKER_FRAMETREE_HOME_DIR)

        return dockerfile

    @classmethod
    def write_dockerfile(
        cls,
        dockerfile: DockerRenderer,
        build_dir: Path,
        image_reference: str,
    ) -> None:
        """Writes the dockerfile to the specified build directory

        Parameters
        ----------
        dockerfile : DockerRenderer
            Neurodocker renderer to build
        build_dir : Path
            path of the build directory
        image_reference : str
            Docker image tag to assign to the built image
        """
        # Save generated dockerfile to file
        out_file = build_dir / "Dockerfile"
        out_file.parent.mkdir(exist_ok=True, parents=True)
        with open(str(out_file), "w") as f:
            f.write(dockerfile.render())
        logger.info(
            "Dockerfile for '%s' generated at %s", image_reference, str(out_file)
        )

    @classmethod
    def build(
        cls,
        dockerfile: DockerRenderer,
        build_dir: Path,
        image_reference: str,
        no_cache: bool = False,
        stream_output: ty.Optional[bool] = None,
    ) -> str:
        """Builds the dockerfile in the specified build directory

        Parameters
        ----------
        dockerfile : DockerRenderer
            Neurodocker renderer to build
        build_dir : Path
            path of the build directory
        image_reference : str
            Docker image tag to assign to the built image
        no_cache : bool, optional
            whether to cache the build layers or not, by default False
        stream_output : bool, optional
            whether to stream the output of the build process to stdout as it is being
            built. If None, the output will be streamed if the logger level is set to
            INFO or lower, by default None

        Returns
        -------
        str
            the image ID of the built image

        Raises
        ------
        docker.errors.BuildError
            If the build process fails
        """
        if stream_output is None:
            stream_output = logger.level <= logging.INFO

        cls.write_dockerfile(dockerfile, build_dir, image_reference)
        dc = docker.from_env()

        response = dc.api.build(
            path=str(build_dir.absolute()), tag=image_reference, rm=True, decode=True
        )
        last_event = None
        result_stream, progress_stream = itertools.tee(response)
        for chunk in progress_stream:
            if "stream" in chunk:
                if stream_output:
                    print(chunk["stream"], end="")
                match = re.search(
                    r"(^Successfully built |sha256:)([0-9a-f]+)$", chunk["stream"]
                )
                if match:
                    logging.info("Successfully built docker image %s", image_reference)
                    return match.group(2)
            if "error" in chunk:
                raise docker.errors.BuildError(
                    chunk["error"],
                    (
                        f"Building '{image_reference}' from '{str(build_dir)}/Dockerfile': "
                        + str(result_stream)
                    ),
                )
            last_event = chunk
        raise docker.errors.BuildError(last_event or "Unknown", result_stream)

    def init_dockerfile(self) -> DockerRenderer:
        dockerfile = DockerRenderer(self.base_image.package_manager).from_(
            self.base_image.reference
        )
        return dockerfile

    def save(self, yml_path: Path) -> None:
        """Saves the specification to a YAML file that can be loaded again

        Parameters
        ----------
        yml_path : Path
            path to file to save the spec to
        """
        yml_dct = self.asdict()
        yml_dct["type"] = ClassResolver.tostr(self, strip_prefix=False)
        with open(yml_path, "w") as f:
            yaml.dump(yml_dct, f)

    def insert_spec(self, dockerfile: DockerRenderer, build_dir: Path) -> None:
        """Generate Neurodocker instructions to save the specification inside the built
        image to be used when running the command and comparing against future builds

        Parameters
        ----------
        dockerfile : DockerRenderer
            the neurodocker renderer to append the install instructions to
        spec : dict
            the specification used to build the image
        build_dir : Path
            path to build dir
        """
        self.save(build_dir / "pydra2app-spec.yaml")
        dockerfile.copy(
            source=["./pydra2app-spec.yaml"], destination=self.IN_DOCKER_SPEC_PATH
        )

    @classmethod
    def load(
        cls,
        yml: ty.Union[Path, ty.Dict[str, ty.Any]],
        name: ty.Optional[str] = None,
        **kwargs: ty.Any,
    ) -> Self:
        """Loads a deploy-build specification from a YAML file

        Parameters
        ----------
        yml : Path or dict
            path to the YAML file to load or loaded dictionary
        name: str, optional
            name of the pipeline, by default None

        Returns
        -------
        Self
            The loaded spec object
        """

        if isinstance(yml, str):
            yml = Path(yml)
        if isinstance(yml, Path):
            yml_dict = cls._load_yaml(yml)
            if not isinstance(yml_dict, dict):
                raise ValueError(f"{yml!r} didn't contain a dict!")
            if name is None:
                name = yml.stem
            yml_dict["loaded_from"] = yml.absolute()
        else:
            yml_dict = yml
        if yml_dict.get("name") is None:
            yml_dict["name"] = name

        yml_dict.pop("type", None)  # Remove "type" from dict if present

        # Override/augment loaded values from spec
        yml_dict.update(kwargs)

        return cls(**yml_dict)

    def add_resources(
        self,
        dockerfile: DockerRenderer,
        build_dir: Path,
        resources: ty.Optional[ty.Dict[str, Path]],
        resources_dir: ty.Optional[Path],
    ) -> None:
        """Add static resources to the docker image"""
        if resources_dir is not None:
            all_resources = {
                p.name: p
                for p in resources_dir.iterdir()
                if p.is_dir() and not p.name.startswith(".")
            }
        else:
            all_resources = {}
        if resources:
            all_resources.update(resources)
        resources_dir_context = build_dir / "resources"
        resources_dir_context.mkdir(exist_ok=True)
        for resource in self.resources:
            try:
                local_path = all_resources[resource.name]
            except KeyError:
                resource_dir_str = (
                    str(resources_dir) if resources_dir is not None else None
                )
                raise RuntimeError(
                    f"Resource '{resource.name}' specified in the pipeline specification "
                    "but not provided in the 'resources' argument or a sub-directory "
                    f"of 'resources_dir' ({resource_dir_str!r})\n"
                    + "\n".join(all_resources)
                )
            # copy local path into Docker build dir so it is included in context
            build_context_path = resources_dir_context / resource.name
            if local_path.is_dir():
                shutil.copytree(local_path, build_context_path)
            else:
                shutil.copy(local_path, build_context_path)
            dockerfile.copy(
                source=[str(build_context_path.relative_to(build_dir))],
                destination=resource.path,
            )

    def add_labels(
        self, dockerfile: DockerRenderer, labels: ty.Optional[ty.Dict[str, str]] = None
    ) -> None:
        if labels is None:
            labels = self.labels
        if labels:
            dockerfile.labels({k: json.dumps(v).strip('"') for k, v in labels.items()})

    def install_python(
        self,
        dockerfile: DockerRenderer,
        build_dir: Path,
        use_local_packages: bool = False,
        pydra2app_install_extras: ty.Sequence[str] = (),
        pypi_fallback: bool = False,
    ) -> None:
        """Generate Neurodocker instructions to install an appropriate version of
        Python and the required Python packages

        Parameters
        ----------
        dockerfile : DockerRenderer
            the neurodocker renderer to append the install instructions to
        build_dir : Path
            the path to the build directory
        pydra2app_install_extras : Iterable[str]
            Optional extras (i.e. as defined in "extras_require" in setup.py) required
            for the pydra2app package
        use_local_packages: bool, optional
            Use the python package versions that are installed within the
            current environment, i.e. instead of defaulting to the release from PyPI.
            Useful during development and testing
        pydra2app_install_extras : list[str]
            list of "install extras" (options) to specify when installing Pydra2App
            (e.g. 'test')
        pypi_fallback : bool, optional
            Whether to fall back to PyPI version when local version doesn't match
            requested

        Returns
        -------
        ty.List[ty.List[str, ty.List[str, str]]]
            neurodocker instructions to install python and required packages
        """

        pip_specs = PipPackage.unique(
            self.packages.pip
            + [PipPackage(PACKAGE_NAME, extras=pydra2app_install_extras)]
            + [PipPackage(d) for d in self.PIP_DEPENDENCIES]
        )

        pip_strs = []
        local_pip_specs = []
        for pip_spec in pip_specs:
            if use_local_packages:
                pip_spec = pip_spec.local_package_location(pypi_fallback=pypi_fallback)
            if pip_spec.file_path:
                local_pip_specs.append(pip_spec)
            else:
                pip_strs.append(self.pip_spec2str(pip_spec, dockerfile, build_dir))

        conda_pkg_names = set(p.name for p in self.packages.conda)
        conda_strs: ty.List[str] = []
        # for pkg_name in CondaPackage.REQUIRED:
        #     if pkg_name not in conda_pkg_names:
        #         conda_strs.append(pkg_name)

        conda_strs.extend(
            f"{p.name}={p.version}" if p.version is not None else p.name
            for p in self.packages.conda
        )

        if not self.base_image.python:
            if "python" not in conda_pkg_names:
                conda_strs.append(f"python=={self.DEFAULT_PYTHON_VERSION}")
            conda_pip_strs = pip_strs
        else:
            conda_pip_strs = []

        if conda_strs:
            dockerfile.add_registered_template(
                "miniconda",
                version="latest",
                env_name=self.base_image.conda_env,
                env_exists=False,
                conda_install=" ".join(conda_strs),
                pip_install=" ".join(conda_pip_strs),
            )
        activate_conda = self.activate_conda() if self.base_image.conda_env else []
        if pip_strs and self.base_image.python:
            dockerfile.run(
                " ".join(
                    activate_conda
                    + [self.base_image.python, "-m", "pip", "install"]
                    + pip_strs
                )
            )
        # Local pip packages in a separate layer to avoid having to re-install
        # everything if a local package changes (e.g. during development)
        if local_pip_specs:
            python_cmd = self.base_image.python if self.base_image.python else "python3"
            dockerfile.run(
                " ".join(
                    activate_conda
                    + [python_cmd, "-m", "pip", "install"]
                    + [
                        self.pip_spec2str(s, dockerfile, build_dir)
                        for s in local_pip_specs
                    ]
                )
            )

    def install_system_packages(self, dockerfile: DockerRenderer) -> None:
        """Generate Neurodocker instructions to install systems packages in dockerfile

        Parameters
        ----------
        dockerfile : DockerRenderer
            the neurodocker renderer to append the install instructions to
        system_packages : Iterable[str]
            the packages to install on the operating system
        """
        pkg_strs = [
            f"{p.name}={p.version}" if p.version else p.name
            for p in self.packages.system
        ]
        if pkg_strs:
            dockerfile.install(pkg_strs)

    def install_package_templates(
        self,
        dockerfile: DockerRenderer,
    ) -> None:
        """Install custom packages from Neurodocker package_templates

        Parameters
        ----------
        dockerfile : DockerRenderer
            the neurodocker renderer to append the install instructions to
        package_templates : Iterable[ty.Dict[str, str]]
            Neurodocker installation package_templates to be installed inside the image. A
            dictionary containing the 'name' and 'version' of the template along
            with any additional keyword arguments required by the template
        """
        for template in self.packages.neurodocker:
            kwds = attrs.asdict(template)
            # so we can pop the name and opt args and leave the original dictionary intact
            kwds = copy(kwds)
            kwds.update(kwds.pop("args", {}))
            dockerfile.add_registered_template(kwds.pop("name"), **kwds)

    @classmethod
    def pip_spec2str(
        cls,
        pip_spec: PipPackage,
        dockerfile: DockerRenderer,
        build_dir: Path,
    ) -> str:
        """Generates a string to be passed to `pip` in order to install a package
        from a "pip specification" object

        Parameters
        ----------
        pip_spec : PipPackage
            specification of the package to install
        dockerfile : DockerRenderer
            Neurodocker Docker renderer object used to generate the Dockerfile
        build_dir : Path
            path to the directory the Docker image will be built in

        Returns
        -------
        str
            string to be passed to `pip` installer
        """
        # Copy the local development versions of Python dependencies into the
        # docker image if present, instead of relying on the PyPI version,
        # which might be missing local changes and bugfixes (particularly in testing)
        # if use_local_packages:
        #     pip_spec = pip_spec.local_package_location(pypi_fallback=pypi_fallback)
        if pip_spec.file_path:
            if pip_spec.version or pip_spec.url:
                raise Pydra2AppBuildError(
                    "Cannot specify a package by `file_path`, `version` and/or " "`url`"
                )
            # pkg_build_path = cls.copy_sdist_into_build_dir(
            #     pip_spec.file_path, build_dir
            # )
            # Create a source distribution tarball to be installed within the docker
            # image
            sdist_dir = build_dir / cls.PYTHON_PACKAGE_DIR
            builder = ProjectBuilder(pip_spec.file_path)
            pkg_build_path = Path(builder.build("sdist", sdist_dir))
            pip_str = "/" + cls.PYTHON_PACKAGE_DIR + "/" + pkg_build_path.name
            dockerfile.copy(
                source=[str(pkg_build_path.relative_to(build_dir))], destination=pip_str
            )
        elif pip_spec.url:
            if pip_spec.version:
                raise Pydra2AppBuildError(
                    "Cannot specify a package by `url` and `version`"
                )
            pip_str = pip_spec.url
        else:
            pip_str = pip_spec.name
        if pip_spec.extras:
            pip_str += "[" + ",".join(pip_spec.extras) + "]"
        if pip_spec.version:
            pip_str += "==" + pip_spec.version
        return pip_str

    # @classmethod
    # def copy_sdist_into_build_dir(cls, local_installation: Path, build_dir: Path):
    #     """Create a source distribution from a locally installed "editable" python package
    #     and copy it into the build dir so it can be installed in the Docker image

    #     Parameters
    #     ----------
    #     package_name : str
    #         the name of the package (how it will be called in the docker image)
    #     local_installation : Path
    #         path to the local installation
    #     build_dir : Path
    #         path to the build directory

    #     Returns
    #     -------
    #     Path
    #         the path to the source distribution within the build directory
    #     """
    #     sdist_dir = build_dir / cls.PYTHON_PACKAGE_DIR
    #     built = build_package(local_installation, sdist_dir, ["sdist"])
    #     return sdist_dir / built[0]

    def write_readme(self, dockerfile: DockerRenderer, build_dir: Path) -> None:
        """Generate Neurodocker instructions to install README file inside the docker
        image

        Parameters
        ----------
        dockerfile : DockerRenderer
            the neurodocker renderer to append the install instructions to
        description : str
            a description of what the pipeline does, to be inserted in a README file
            in the Docker image
        build_dir : Path
            path to build dir
        """
        with open(build_dir / "README.md", "w") as f:
            f.write(self.DOCKERFILE_README_TEMPLATE.format(__version__, self.readme))
        dockerfile.copy(source=["./README.md"], destination="/README.md")

    def asdict(self) -> ty.Dict[str, ty.Any]:
        """Return a serialized version of the pipeline image specification that can be
        written to file"""

        def filter(attr: attrs.Attribute[ty.Any], value: ty.Any) -> bool:
            if isinstance(value, type(self)):
                return False  # filter-out back-references to self
            if not attr.metadata.get("asdict", True):
                return False  # filter out explicitly excluded attributes
            try:
                if value == attr.default:
                    return False  # filter out default values
            except (AttributeError, TypeError):
                return True
            return True

        def listify_containers(value: ty.Any) -> ty.Any:
            if isinstance(value, ty.Mapping):
                return {k: listify_containers(v) for k, v in value.items()}
            elif isinstance(value, (ty.Sequence, set, frozenset)) and not isinstance(
                value, (str, bytes)
            ):
                return [listify_containers(v) for v in value]
            return value

        def serializer(
            _: ty.Any, attr: attrs.Attribute[ty.Any], value: ty.Any
        ) -> ty.Any:
            if attr is not None and "serializer" in attr.metadata:
                return attr.metadata["serializer"](
                    value,
                    value_serializer=serializer,
                    filter=filter,
                )
            elif isinstance(value, Axes):
                if hasattr(self, "commands") and self.commands[0].AXES:
                    return str(value)
                else:
                    return value.tostr()
            elif isinstance(value, Enum):
                return value.value
            elif isinstance(value, PurePath):
                return str(value)
            # elif isinstance(value, pydra.compose.base.Task):
            #     return unstructure(value)
            elif isclass(value) or isfunction(value) or ty.get_origin(value):
                return ClassResolver.tostr(value, strip_prefix=False)
            return listify_containers(value)

        return attrs.asdict(self, value_serializer=serializer, filter=filter)

    def activate_conda(self) -> ty.List[str]:
        """Generate the preamble to a command line that activates the conda environment

        Returns
        -------
        str
            part of a command line, which activates the conda environment
        """
        if not self.base_image.conda_env:
            return []
        return ["conda", "run", "--no-capture-output", "-n", self.base_image.conda_env]

    def compare_specs(self, other: Self, check_versions: bool = True) -> DeepDiff:
        """Compares two build specs against each other and returns the difference

        Parameters
        ----------
        s1 : dict
            first spec
        s2 : dict
            second spec
        check_version : bool
            check the pydra2app version used to generate the specs

        Returns
        -------
        DeepDiff
            the difference between the specs
        """

        sdict = self.asdict()
        odict = other.asdict()

        def prep(s: ty.Dict[str, ty.Any]) -> ty.Dict[str, ty.Any]:
            dct = {
                k: v
                for k, v in s.items()
                if (not k.startswith("_") and (v or isinstance(v, bool)))
            }
            if check_versions:
                if "pydra2app_version" not in dct:
                    dct["pydra2app_version"] = __version__
            else:
                dct.pop("pydra2app_version", None)
                dct.pop("version", None)
            return dct

        diff = DeepDiff(prep(sdict), prep(odict), ignore_order=True)
        return diff

    @classmethod
    def _load_yaml(cls, yaml_file: ty.Union[Path, str]) -> ty.Dict[str, ty.Any]:
        def yaml_join(loader: yaml.Loader, node: yaml.SequenceNode) -> str:
            seq = loader.construct_sequence(node)
            return "".join([str(i) for i in seq])

        # Add special constructors to handle joins and concatenations within the YAML
        yaml.SafeLoader.add_constructor(tag="!join", constructor=yaml_join)
        with open(yaml_file, "r") as f:
            dct = yaml.load(f, Loader=yaml.SafeLoader)
        return dct  # type: ignore[no-any-return]

    DOCKERFILE_README_TEMPLATE = """
        The following Docker image was generated by Pydra2App v{} (https://pydra2app.readthedocs.io)

        {}

        """  # noqa: E501

    PYTHON_PACKAGE_DIR = "python-packages"
