import pytest
from pathlib import Path
import docker
import docker.errors
from frametree.core.utils import show_cli_trace
from pydra2app.core.cli import make
from pydra2app.testing.licenses import (
    get_pipeline_image,
    make_dataset,
)
from pydra2app.testing.constants import (
    ORG,
    REGISTRY,
    IMAGE_VERSION,
    LICENSE_CONTENTS,
    LICENSE_NAME,
    LICENSE_INPUT_FIELD,
    LICENSE_OUTPUT_FIELD,
    LICENSE_PATH_PARAM,
    LICENSE_INPUT_PATH,
    LICENSE_OUTPUT_PATH,
)


def test_buildtime_license(license_file, run_prefix: str, work_dir: Path, cli_runner):

    # Create pipeline
    image_name = f"license-buildtime-{run_prefix}"
    image_tag = f"{REGISTRY}/{ORG}/{image_name}:{IMAGE_VERSION}"

    spec_path = work_dir / ORG
    spec_path.mkdir()
    spec_file = spec_path / (image_name + ".yaml")

    LICENSE_PATH = "/path/to/licence.txt"

    pipeline_image = get_pipeline_image(LICENSE_PATH)
    pipeline_image.name = image_name
    pipeline_image.licenses[0].store_in_image = True
    pipeline_image.save(spec_file)

    build_dir = work_dir / "build"
    dataset_dir = work_dir / "dataset"
    make_dataset(dataset_dir)

    result = cli_runner(
        make,
        args=[
            "common:App",
            str(spec_path),
            "--spec-root",
            str(spec_path.parent),
            "--build-dir",
            str(build_dir),
            "--license",
            LICENSE_NAME,
            str(license_file),
            "--use-local-packages",
            "--install-extras",
            "test",
            "--raise-errors",
            "--registry",
            REGISTRY,
        ],
    )

    assert result.exit_code == 0, show_cli_trace(result)

    assert result.stdout.strip().splitlines()[-1] == image_tag

    args = (
        "file_system///dataset "
        f"--input {LICENSE_INPUT_FIELD} '{LICENSE_INPUT_PATH}' "
        f"--output {LICENSE_OUTPUT_FIELD} '{LICENSE_OUTPUT_PATH}' "
        f"--parameter {LICENSE_PATH_PARAM} '{LICENSE_PATH}' "
        f"--worker debug "
        f"--raise-errors "
    )

    dc = docker.from_env()
    try:
        result = dc.containers.run(
            image_tag,
            args,
            volumes=[
                f"{str(dataset_dir)}:/dataset:rw",
            ],
            remove=False,
            stdout=True,
            stderr=True,
        )
    except docker.errors.ContainerError as e:
        logs = e.container.logs().decode("utf-8")
        raise RuntimeError(
            f"Running {image_tag} failed with args = {args}" f"\n\nlogs:\n{logs}",
        )


@pytest.fixture
def license_file(work_dir) -> Path:
    license_src = work_dir / "license_file.txt"

    with open(license_src, "w") as f:
        f.write(LICENSE_CONTENTS)

    return license_src
