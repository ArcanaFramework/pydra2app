from pydra2app.core.cli import ext
from frametree.core.utils import show_cli_trace


def test_cli_ext(cli_runner):

    result = cli_runner(ext, ["--help"])

    assert result.exit_code == 0, show_cli_trace(result)
