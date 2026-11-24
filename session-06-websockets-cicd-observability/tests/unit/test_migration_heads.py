from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    config = Config()
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_there_is_exactly_one_migration_head() -> None:
    assert len(_script_directory().get_heads()) == 1


def test_every_migration_file_is_reachable_from_the_head() -> None:
    script = _script_directory()
    walked = {revision.revision for revision in script.walk_revisions()}
    on_disk = list((PROJECT_ROOT / "alembic" / "versions").glob("*.py"))

    assert len(walked) == len(on_disk)
