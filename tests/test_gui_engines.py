"""The engine pickers and the engines dialog, in the real page."""

import pytest

from uciboard import config
from uciboard.api import Api

from conftest import wait_for


def api_with_two(tmp_path, stockfish, analyse=False):
    s = config.load_settings(stockfish=stockfish, own_config=tmp_path / "none.toml", analyse=analyse)
    s.threads = 1
    api = Api(s)
    api.add_engine(stockfish, "Second")
    return api


def options(page, select):
    return page.eval_on_selector_all(f"#{select} option", "els => els.map(e => [e.value, e.textContent])")


@pytest.mark.engine
def test_each_job_has_its_own_picker_listing_the_engines(make_page, stockfish, tmp_path):
    page, errors = make_page(api_with_two(tmp_path, stockfish))
    page.wait_for_function("document.querySelectorAll('#pick-live option').length === 3")
    for select in ("pick-live", "pick-evo"):
        assert options(page, select) == [["default", "Stockfish (auto)"], ["e1", "Second"],
                                         ["__manage__", "Add or edit engines…"]]
        assert page.input_value(f"#{select}") == "default"
    assert not errors, errors


@pytest.mark.engine
def test_choosing_the_live_engine_does_not_change_the_game_analysis_engine(make_page, stockfish, tmp_path):
    api = api_with_two(tmp_path, stockfish, analyse=True)
    page, errors = make_page(api)
    page.wait_for_selector("#engine[data-state=analysing]")
    page.select_option("#pick-live", "e1")
    page.wait_for_function("document.getElementById('pick-live').value === 'e1'")
    page.wait_for_selector("#engine[data-state=analysing]")
    assert api.engines()["live"] == "e1" and api.engines()["evolution"] == "default"
    assert page.input_value("#pick-evo") == "default"
    page.select_option("#pick-evo", "e1")
    wait_for(lambda: api.engines()["evolution"] == "e1")
    assert api.engines()["live"] == "e1" and api.poll(0)["engine"]["id"] == "e1"
    assert not errors, errors


@pytest.mark.engine
def test_the_dialog_adds_edits_and_removes_engines(make_page, stockfish, tmp_path):
    api = api_with_two(tmp_path, stockfish)
    page, errors = make_page(api)
    page.wait_for_function("document.querySelectorAll('#pick-live option').length === 3")
    page.select_option("#pick-live", "__manage__")
    page.wait_for_selector("#engines-dialog[open]")
    assert page.input_value("#pick-live") == "default"                 # the menu does not stay on "Add or edit"
    assert page.locator("#engines-list .eng-row").count() == 2
    assert page.locator("#engines-list .eng-row[data-id=default] .eng-options").count() == 0   # nothing to edit
    # a mistake in the options is explained, not swallowed
    row = page.locator("#engines-list .eng-row[data-id=e1]")
    row.locator(".eng-options").fill("Hash 16")
    row.locator(".eng-save").click()
    page.wait_for_function("document.getElementById('engines-msg').textContent.includes('Name=value')")
    row = page.locator("#engines-list .eng-row[data-id=e1]")
    row.locator(".eng-options").fill("Hash=16")
    row.locator(".eng-name").fill("Renamed")
    row.locator(".eng-save").click()
    page.wait_for_function("document.getElementById('engines-msg').textContent === 'Renamed saved.'")
    assert [e.name for e in api._registry.added] == ["Renamed"]
    assert api._registry.added[0].options == {"Hash": "16"}
    # add by typing a path (the file dialog is the desktop window's)
    page.fill("#eng-path", stockfish)
    page.click("#eng-add")
    page.wait_for_function("document.querySelectorAll('#engines-list .eng-row').length === 3")
    assert page.inner_text("#engines-msg").startswith("Added Stockfish")
    page.fill("#eng-path", "/no/such/engine")
    page.click("#eng-add")
    page.wait_for_function("document.getElementById('engines-msg').textContent.includes('No file at')")
    assert page.locator("#engines-list .eng-row").count() == 3
    # remove
    page.locator("#engines-list .eng-row[data-id=e2] .eng-remove").click()
    page.wait_for_function("document.querySelectorAll('#engines-list .eng-row').length === 2")
    assert [o[0] for o in options(page, "pick-evo")] == ["default", "e1", "__manage__"]
    page.click("#eng-close")
    page.wait_for_function("!document.getElementById('engines-dialog').open")
    assert not errors, errors
