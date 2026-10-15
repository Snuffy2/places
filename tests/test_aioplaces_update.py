"""Tests for the aioplaces dependency update workflow."""

from importlib import util
from io import StringIO
import json
from pathlib import Path
import sys
import tomllib
from types import ModuleType
from typing import Never

import pytest

SCRIPT_PATH = Path(".github/scripts/update_aioplaces_pins.py")
RELEASE_NOTES_SCRIPT_PATH = Path(".github/scripts/build_aioplaces_release_notes.py")
CLEANUP_SCRIPT_PATH = Path(".github/scripts/cleanup_aioplaces_update_branches.py")


class FakeCleanupClient:
    """Fake GitHub cleanup client that records mutating calls."""

    def __init__(
        self,
        *,
        open_pulls: list[dict[str, object]],
        closed_pulls: list[dict[str, object]],
        ref_shas: dict[str, str] | None = None,
        fail_on_close: bool = False,
        fail_on_ref_lookup: bool = False,
    ) -> None:
        """Initialize fake pull request state.

        Args:
            open_pulls (list[dict[str, object]]): Pull requests to return for open PR lookups.
            closed_pulls (list[dict[str, object]]): Pull requests to return for closed PR lookups.
            ref_shas (dict[str, str] | None): Current branch SHAs returned by the fake.
            fail_on_close (bool): Whether closing a PR should fail the test.
            fail_on_ref_lookup (bool): Whether looking up a branch SHA should fail.
        """
        self.open_pulls = open_pulls
        self.closed_pulls = closed_pulls
        self.ref_shas = ref_shas or {}
        self.fail_on_close = fail_on_close
        self.fail_on_ref_lookup = fail_on_ref_lookup
        self.closed_prs: list[int] = []
        self.deleted_refs: list[str] = []

    def list_pulls(self, *, state: str) -> list[dict[str, object]]:
        """Return fake pull requests by state.

        Returns:
            list[dict[str, object]]: Pull request records stored by the fake GitHub client.

        Args:
            state (str): Pull request state recorded by the fake GitHub client.
        """
        return self.open_pulls if state == "open" else self.closed_pulls

    def close_pull(self, pull_number: int) -> None:
        """Record or reject a closed pull request.

        Args:
            pull_number (int): Pull request number queried by the fake GitHub client.

        Raises:
            AssertionError: The fake was configured to reject close requests.
        """
        if self.fail_on_close:
            raise AssertionError(f"Unexpected close for PR {pull_number}")
        self.closed_prs.append(pull_number)

    def delete_ref(self, ref: str) -> None:
        """Record a deleted git ref.

        Args:
            ref (str): Git reference queried by the fake GitHub client.
        """
        self.deleted_refs.append(ref)

    def get_ref_sha(self, branch: str) -> str | None:
        """Return the fake current branch SHA.

        Args:
            branch (str): Branch name requested by the cleanup routine.

        Returns:
            str | None: Current branch SHA, or ``None`` if the fake branch is missing.

        Raises:
            OSError: The fake was configured to fail ref lookups.
        """
        if self.fail_on_ref_lookup:
            raise OSError("GitHub ref lookup failed")
        return self.ref_shas.get(branch)


def _workflow_pull(
    *,
    number: int,
    ref: str = "chore/update-aioplaces-manifest",
    label: str = "dependencies",
    merged_at: str | None = None,
    sha: str = "commit-sha",
    author: str = "github-actions[bot]",
    repository: str = "o/r",
) -> dict[str, object]:
    """Return a fake workflow pull request object.

    Args:
        number (int): Pull request number.
        ref (str): Pull request head ref.
        label (str): Pull request label name.
        merged_at (str | None): Optional merge timestamp for closed PRs.
        sha (str): Commit SHA at the pull request head.
        author (str): Login of the pull request author.
        repository (str): Repository containing the pull request head branch.

    Returns:
        dict[str, object]: Fake pull request object shaped like the GitHub REST API response.
    """
    return {
        "number": number,
        "merged_at": merged_at,
        "head": {"ref": ref, "sha": sha, "repo": {"full_name": repository}},
        "labels": [{"name": label}],
        "user": {"login": author},
    }


def _write_pin_files(
    tmp_path: Path,
    *,
    manifest_version: str,
    pyproject_version: str | None = None,
    pyproject_text: str | None = None,
) -> tuple[Path, Path]:
    """Write temporary manifest and pyproject files with aioplaces pins.

    Returns:
        tuple[Path, Path]: Paths to the generated manifest and pyproject files.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        manifest_version (str): aioplaces version written to the test manifest.
        pyproject_version (str | None): aioplaces version written to the test pyproject.
        pyproject_text (str | None): Optional complete pyproject content for the fixture.
    """
    manifest_path = tmp_path / "manifest.json"
    pyproject_path = tmp_path / "pyproject.toml"
    manifest_path.write_text(
        json.dumps(
            {
                "requirements": [
                    "xmltodict==0.14.2",
                    f"aioplaces=={manifest_version}",
                ],
            },
        ),
    )

    if pyproject_text is None:
        pyproject_text = f"""[project]
dependencies = [
    "aioplaces=={pyproject_version or manifest_version}",
]
"""
    pyproject_path.write_text(pyproject_text)
    return manifest_path, pyproject_path


@pytest.fixture
def updater_script() -> ModuleType:
    """Load the aioplaces pin updater script as a test module.

    Returns:
        ModuleType: Imported workflow helper module.
    """
    return _load_script("update_aioplaces_pins", SCRIPT_PATH)


@pytest.fixture
def release_notes_script() -> ModuleType:
    """Load the aioplaces release-note builder script as a test module.

    Returns:
        ModuleType: Imported workflow helper module.
    """
    return _load_script("build_aioplaces_release_notes", RELEASE_NOTES_SCRIPT_PATH)


@pytest.fixture
def cleanup_script() -> ModuleType:
    """Load the aioplaces cleanup script as a test module.

    Returns:
        ModuleType: Imported workflow helper module.
    """
    return _load_script("cleanup_aioplaces_update_branches", CLEANUP_SCRIPT_PATH)


def _load_script(module_name: str, script_path: Path) -> ModuleType:
    """Load a checked-in workflow helper script as a test module.

    Returns:
        ModuleType: Imported workflow helper module.

    Args:
        module_name (str): Import name assigned to the loaded workflow helper.
        script_path (Path): Filesystem path of the workflow helper to load.
    """
    spec = util.spec_from_file_location(module_name, script_path)
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    (
        "manifest_version",
        "pyproject_version",
        "latest_version",
        "expected_update_needed",
        "expected_target",
    ),
    [
        ("1.0.8", "1.0.8", "1.0.9", True, "1.0.9"),
        ("1.0.0", "1.0.0", "1.0.1rc1", False, "1.0.0"),
        ("1.0.1rc1", "1.0.1rc1", "1.0.1", True, "1.0.1"),
        ("1.0.10", "1.0.9", "1.0.9", True, "1.0.10"),
    ],
)
def test_updater_script_pin_update_scenarios(
    tmp_path: Path,
    updater_script: ModuleType,
    manifest_version: str,
    pyproject_version: str,
    latest_version: str,
    expected_update_needed: bool,
    expected_target: str,
) -> None:
    """Updater script should handle stable, prerelease, and drift pin scenarios.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        updater_script (ModuleType): Loaded aioplaces pin-updater helper module.
        manifest_version (str): aioplaces version written to the test manifest.
        pyproject_version (str): aioplaces version written to the test pyproject.
        latest_version (str): Release version reported by the mocked package index.
        expected_update_needed (bool): Whether pin evaluation should request an update.
        expected_target (str): Version target expected from pin evaluation.
    """
    manifest_path, pyproject_path = _write_pin_files(
        tmp_path,
        manifest_version=manifest_version,
        pyproject_version=pyproject_version,
    )

    result = updater_script.update_pins(
        manifest_path=manifest_path,
        pyproject_path=pyproject_path,
        latest_version=latest_version,
    )

    assert result.current == manifest_version
    assert result.pyproject_current == pyproject_version
    assert result.latest == expected_target
    assert result.update_needed is expected_update_needed
    manifest = json.loads(manifest_path.read_text())
    pyproject = tomllib.loads(pyproject_path.read_text())
    expected_pin = f"aioplaces=={expected_target}"
    assert expected_pin in manifest["requirements"]
    assert expected_pin in pyproject["project"]["dependencies"]


def test_updater_script_updates_pyproject_pin_without_trailing_comma(
    tmp_path: Path, updater_script: ModuleType
) -> None:
    """Updater script should preserve valid TOML dependency-list formatting.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        updater_script (ModuleType): Loaded aioplaces pin-updater helper module.
    """
    manifest_path, pyproject_path = _write_pin_files(
        tmp_path,
        manifest_version="1.0.8",
        pyproject_text="""[project]
dependencies = [
    "homeassistant",
    "aioplaces==1.0.8"
]
""",
    )

    result = updater_script.update_pins(
        manifest_path=manifest_path,
        pyproject_path=pyproject_path,
        latest_version="1.0.9",
    )

    assert result.update_needed is True
    pyproject = tomllib.loads(pyproject_path.read_text())
    assert "aioplaces==1.0.9" in pyproject["project"]["dependencies"]


@pytest.mark.parametrize(
    ("payload", "expected_latest"),
    [
        (
            {
                "info": {"version": "1.1.0rc1"},
                "releases": {
                    "1.0.8": [{"filename": "aioplaces-1.0.8.tar.gz"}],
                    "1.0.9": [{"filename": "aioplaces-1.0.9.tar.gz"}],
                    "1.1.0rc1": [{"filename": "aioplaces-1.1.0rc1.tar.gz"}],
                },
            },
            "1.0.9",
        ),
        (
            {
                "releases": {
                    "1.0.8": [{"filename": "aioplaces-1.0.8.tar.gz"}],
                    "1.0.9": [],
                    "1.0.10": [{"filename": "aioplaces-1.0.10.tar.gz", "yanked": True}],
                },
            },
            "1.0.8",
        ),
    ],
)
def test_updater_script_selects_latest_stable_from_pypi_payload(
    updater_script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    expected_latest: str,
) -> None:
    """Updater script should select the latest installable stable PyPI release.

    Args:
        updater_script (ModuleType): Loaded aioplaces pin-updater helper module.
        monkeypatch (pytest.MonkeyPatch): pytest fixture used to replace dependencies.
        payload (dict[str, object]): Synthetic API response payload.
        expected_latest (str): Latest release version expected from the response.
    """

    def open_pypi_response(url: str, *, timeout: int) -> StringIO:
        """Return the fake PyPI response as a readable context manager.

        Args:
            url (str): PyPI URL passed to ``urlopen``.
            timeout (int): Timeout value passed to ``urlopen``.

        Returns:
            StringIO: In-memory stream containing the mocked HTTP response.
        """
        return StringIO(json.dumps(payload))

    monkeypatch.setattr(updater_script, "urlopen", open_pypi_response)

    assert updater_script.fetch_latest_version() == expected_latest


def test_updater_script_rejects_duplicate_pyproject_pins(
    tmp_path: Path,
    updater_script: ModuleType,
) -> None:
    """Updater script should fail clearly when pyproject has ambiguous pins.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        updater_script (ModuleType): Loaded aioplaces pin-updater helper module.
    """
    manifest_path, pyproject_path = _write_pin_files(
        tmp_path,
        manifest_version="1.0.8",
        pyproject_text="""[project]
dependencies = [
    "aioplaces==1.0.8",
    "aioplaces==1.0.9",
]
""",
    )

    with pytest.raises(ValueError, match="Expected exactly one pinned aioplaces dependency"):
        updater_script.update_pins(
            manifest_path=manifest_path,
            pyproject_path=pyproject_path,
            latest_version="1.0.10",
        )


def test_release_note_script_builds_sanitized_pr_body(
    tmp_path: Path,
    release_notes_script: ModuleType,
) -> None:
    """Release-note script should build a mention-safe PR body file.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        release_notes_script (ModuleType): Loaded release-notes workflow helper module.
    """
    releases = [
        {
            "tag_name": "1.0.8",
            "name": "Ignored current",
            "body": "old",
            "html_url": "https://example.test/1.0.8",
        },
        {
            "tag_name": "1.0.9",
            "name": "Fixes @someone",
            "body": "fixes #123 and thanks [@helper](https://github.com/helper)",
            "html_url": "https://example.test/1.0.9",
        },
        {
            "tag_name": "1.1.0rc1",
            "name": "Ignored prerelease",
            "body": "future",
            "html_url": "https://example.test/1.1.0rc1",
        },
    ]
    body_path = tmp_path / "body.md"

    release_notes_script.write_pr_body(
        body_path=body_path,
        releases=releases,
        current_version="1.0.8",
        pyproject_current_version="1.0.8",
        latest_version="1.0.9",
    )

    body = body_path.read_text()
    assert "Automated update of aioplaces dependency pins." in body
    assert "Updated pinned version: `aioplaces==1.0.9`" in body
    assert "### Fixes @<!-- -->someone (1.0.9)" in body
    assert "fixes \\#123 and thanks helper" in body
    assert "Ignored current" not in body
    assert "Ignored prerelease" not in body


def test_release_note_script_handles_url_errors(
    tmp_path: Path,
    release_notes_script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release-note script should report network failures without a traceback.

    Args:
        tmp_path (Path): pytest temporary directory containing test configuration files.
        release_notes_script (ModuleType): Loaded release-notes workflow helper module.
        monkeypatch (pytest.MonkeyPatch): pytest fixture used to replace dependencies.
    """

    def raise_url_error(*, owner: str, repo: str, token: str | None = None) -> Never:
        """Raise a urlopen-style network failure.

        Args:
            owner (str): Release repository owner passed to the function.
            repo (str): Release repository name passed to the function.
            token (str | None): Optional GitHub token passed to the function.

        Returns:
            Never: Never returns normally because ``URLError`` is always raised.

        Raises:
            release_notes_script.URLError: Always raised to simulate a network failure.
        """
        raise release_notes_script.URLError("DNS failure")

    monkeypatch.setattr(release_notes_script, "fetch_releases", raise_url_error)

    result = release_notes_script.main(
        [
            "--current-version",
            "1.0.8",
            "--pyproject-current-version",
            "1.0.8",
            "--latest-version",
            "1.0.9",
            "--release-owner",
            "Snuffy2",
            "--release-repo",
            "aioplaces",
            "--body-path",
            str(tmp_path / "body.md"),
        ],
    )

    assert result == 1


def test_cleanup_script_preserves_human_same_prefix_and_same_name_prs(
    cleanup_script: ModuleType,
) -> None:
    """Cleanup should preserve human PRs, even when names match or share a prefix.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[
            _workflow_pull(number=10, sha="human-sha", author="alice"),
            _workflow_pull(
                number=11,
                ref="chore/update-aioplaces-parser",
                sha="parser-sha",
                author="bob",
            ),
            _workflow_pull(number=12, label="bugfix"),
            _workflow_pull(number=13, repository="fork-owner/places"),
        ],
        closed_pulls=[
            _workflow_pull(number=8, merged_at="2026-05-28T00:00:00Z", sha="old-sha"),
        ],
        ref_shas={branch: "old-sha"},
    )

    result = cleanup_script.cleanup_update_branches(
        client=client,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=None,
        close_stale_prs=True,
        delete_merged_branches=True,
    )

    assert client.closed_prs == []
    assert client.deleted_refs == []
    assert result.closed_prs == []
    assert result.deleted_branches == []


def test_cleanup_script_does_not_delete_unowned_or_orphan_branch(
    cleanup_script: ModuleType,
) -> None:
    """Unowned PRs and branches without a matching workflow PR stay untouched.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[_workflow_pull(number=10, author="alice")],
        closed_pulls=[],
        ref_shas={branch: "human-sha"},
    )

    result = cleanup_script.cleanup_update_branches(
        client=client,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=None,
        close_stale_prs=True,
        delete_merged_branches=True,
    )

    assert client.closed_prs == []
    assert client.deleted_refs == []
    assert result.closed_prs == []
    assert result.deleted_branches == []

    orphan = FakeCleanupClient(open_pulls=[], closed_pulls=[], ref_shas={branch: "orphan-sha"})
    orphan_result = cleanup_script.cleanup_update_branches(
        client=orphan,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=None,
        close_stale_prs=True,
        delete_merged_branches=True,
    )

    assert orphan.deleted_refs == []
    assert orphan_result.deleted_branches == []


def test_cleanup_script_does_not_delete_recreated_branch_with_new_sha(
    cleanup_script: ModuleType,
) -> None:
    """A merged bot PR cannot delete a branch recreated at a different commit.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[],
        closed_pulls=[
            _workflow_pull(number=8, merged_at="2026-05-28T00:00:00Z", sha="old-sha"),
        ],
        ref_shas={branch: "recreated-sha"},
    )

    result = cleanup_script.cleanup_update_branches(
        client=client,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=None,
        close_stale_prs=True,
        delete_merged_branches=True,
    )

    assert client.deleted_refs == []
    assert result.deleted_branches == []


def test_cleanup_script_does_not_delete_when_ref_lookup_fails(
    cleanup_script: ModuleType,
) -> None:
    """A failed current-ref lookup cannot authorize deleting a branch.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[],
        closed_pulls=[
            _workflow_pull(number=8, merged_at="2026-05-28T00:00:00Z", sha="old-sha"),
        ],
        fail_on_ref_lookup=True,
    )

    with pytest.raises(OSError, match="GitHub ref lookup failed"):
        cleanup_script.cleanup_update_branches(
            client=client,
            repository="o/r",
            branch=branch,
            label_name="dependencies",
            keep_pr_number=None,
            close_stale_prs=True,
            delete_merged_branches=True,
        )

    assert client.deleted_refs == []


def test_cleanup_script_closes_and_deletes_valid_stale_bot_pr(
    cleanup_script: ModuleType,
) -> None:
    """A stale workflow bot PR closes and deletes only its unchanged branch.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[_workflow_pull(number=10, sha="workflow-sha")],
        closed_pulls=[],
        ref_shas={branch: "workflow-sha"},
    )

    result = cleanup_script.cleanup_update_branches(
        client=client,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=None,
        close_stale_prs=True,
        delete_merged_branches=False,
    )

    assert client.closed_prs == [10]
    assert client.deleted_refs == [f"heads/{branch}"]
    assert result.closed_prs == [10]
    assert result.deleted_branches == [branch]


def test_cleanup_script_keeps_active_update_branch_despite_merged_history(
    cleanup_script: ModuleType,
) -> None:
    """The active update PR protects its branch from historical merged PRs.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
    """
    branch = "chore/update-aioplaces-manifest"
    client = FakeCleanupClient(
        open_pulls=[_workflow_pull(number=12, sha="active-sha")],
        closed_pulls=[
            _workflow_pull(number=8, merged_at="2026-05-28T00:00:00Z", sha="old-sha"),
        ],
        ref_shas={branch: "active-sha"},
        fail_on_close=True,
    )

    result = cleanup_script.cleanup_update_branches(
        client=client,
        repository="o/r",
        branch=branch,
        label_name="dependencies",
        keep_pr_number=12,
        close_stale_prs=True,
        delete_merged_branches=True,
    )

    assert client.closed_prs == []
    assert client.deleted_refs == []
    assert result.closed_prs == []
    assert result.deleted_branches == []


def test_cleanup_github_client_returns_none_for_missing_ref(
    cleanup_script: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GitHub's missing-ref response is represented as no branch SHA.

    Args:
        cleanup_script (ModuleType): Loaded branch-cleanup workflow helper module.
        monkeypatch (pytest.MonkeyPatch): Fixture used to replace the HTTP request.
    """

    def raise_not_found(request: object, *, timeout: int) -> Never:
        """Raise an HTTP 404 response for a missing branch ref.

        Args:
            request (object): HTTP request passed by the GitHub client.
            timeout (int): Request timeout passed by the GitHub client.

        Returns:
            Never: Never returns normally because the 404 is always raised.

        Raises:
            cleanup_script.HTTPError: Always raised to simulate a missing ref.
        """
        raise cleanup_script.HTTPError(
            "https://api.github.com/repos/o/r/git/ref/heads/example",
            404,
            "Not Found",
            None,
            None,
        )

    monkeypatch.setattr(cleanup_script, "urlopen", raise_not_found)
    client = cleanup_script.GithubClient(repository="o/r", token="")

    assert client.get_ref_sha("example") is None
