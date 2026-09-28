from __future__ import annotations

from pathlib import Path

import pytest

from opencounsel.briefs.sources import SourceResolutionError, load_source_overrides


def _manifest(path: Path, url: str) -> Path:
    path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                "",
                "[[authority]]",
                'citation = "550 U.S. 544"',
                f'url = "{url}"',
            )
        ),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "url",
    (
        "https://www.courtlistener.com/?q=550+U.S.+544&type=o",
        "https://www.courtlistener.com/api/rest/v4/search/?q=550+U.S.+544",
    ),
)
def test_rejects_courtlistener_search_url_as_final_authority_target(
    tmp_path: Path,
    url: str,
) -> None:
    manifest = _manifest(tmp_path / "search.toml", url)

    with pytest.raises(SourceResolutionError, match="stable"):
        load_source_overrides(manifest)


def test_accepts_canonical_courtlistener_opinion_url(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path / "opinion.toml",
        "https://www.courtlistener.com/opinion/1444/bell-atlantic-corp-v-twombly/",
    )

    overrides = load_source_overrides(manifest)

    assert overrides[0].url.endswith("/opinion/1444/bell-atlantic-corp-v-twombly/")
