import json
import typing as ty
import tempfile
import attrs
from pathlib import Path
from .base import P2AImage


@attrs.define
class Metapackage(P2AImage):

    manifest: dict

    def construct_dockerfile(
        self,
        build_dir: ty.Optional[Path] = None,
        use_local_packages=False,
    ):

        if build_dir is None:
            build_dir = Path(tempfile.mkdtemp())

        dockerfile = self.init_dockerfile()

        self.install_python(
            dockerfile, build_dir, use_local_packages=use_local_packages
        )

        with open(build_dir / "manifest.json", "w") as f:
            json.dump(self.manifest, f)

        dockerfile.copy(["./manifest.json"], "/manifest.json")

        dockerfile.entrypoint(
            self.activate_conda()
            + [
                "pydra2app",
                "ext",
                "xnat",
                "pull-images",
                "/manifest.json",
            ]
        )

        return dockerfile
