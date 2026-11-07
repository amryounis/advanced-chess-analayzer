"""The defender, king-safety and safe-square overlays in the real page. They come from the geometry
of the position, so none of these needs an engine."""

from uciboard import config
from uciboard.api import Api

RUY = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"


SHOWN = "[...document.querySelectorAll('#board .%s')].filter(e => !e.hidden).length"


def click_knight(page):
    """Click the white knight once the board has stopped moving (the layout settles after start-up)."""
    box = None
    for _ in range(50):
        now = page.locator("#board piece.white.knight:not(.ghost)").bounding_box()
        if now == box:
            break
        box = now
        page.wait_for_timeout(100)
    page.mouse.click(now["x"] + now["width"] / 2, now["y"] + now["height"] / 2)


def page_at(make_page, fen):
    api = Api(config.Settings())
    api.set_position(fen)
    page, errors = make_page(api)
    page.wait_for_selector(f"#board[data-fen='{fen}']")
    page.wait_for_function("document.getElementById('engine-text').textContent !== 'starting…'")   # init is done
    return page, errors


def test_the_only_defender_is_listed_ringed_and_pointed_at_what_it_guards(make_page):
    page, errors = page_at(make_page, RUY)
    page.wait_for_selector("#tactics li.t-removable")
    text = page.inner_text("#tactics")
    assert "black knight c6 is the only defender of pawn e5" in text and "can trade it off" in text
    assert "skewers" not in text                                  # d7 is defended: nothing is won there
    page.wait_for_function("document.querySelectorAll('.cg-shapes circle').length >= 1 "
                           "&& document.querySelectorAll('.cg-shapes line').length >= 1")
    page.uncheck("#show-defenders")
    page.wait_for_function("document.querySelectorAll('#tactics li.t-removable').length === 0 "
                           "&& document.querySelectorAll('.cg-shapes line').length === 0")
    assert not errors, errors


def test_an_overloaded_defender_is_listed(make_page):
    page, errors = page_at(make_page, "1n1r2k1/8/8/3p4/5B2/8/8/K2R4 w - - 0 1")
    page.wait_for_selector("#tactics li.t-overload")
    assert "black rook d8 is the only defender of" in page.inner_text("#tactics li.t-overload")
    assert not errors, errors


def test_king_safety_marks_the_squares_round_the_kings(make_page):
    page, errors = page_at(make_page, "R5k1/5ppp/8/8/8/8/8/4K3 b - - 0 1")
    assert not page.is_checked("#show-king")
    assert page.evaluate(SHOWN % "zones") == 0
    page.check("#show-king")
    page.wait_for_function("document.querySelectorAll('#board .zones i.danger').length === 2")
    assert "black king g8: has no square to step to (in check)" in page.inner_text("#tactics")
    assert page.locator("#board .zones i.escape").count() >= 1    # the white king has room
    page.uncheck("#show-king")
    page.wait_for_function(SHOWN % "zones" + " === 0")
    assert not errors, errors


def test_picking_up_a_piece_shows_which_squares_are_safe(make_page):
    page, errors = page_at(make_page, "4k3/8/8/3p4/8/2N5/8/4K3 w - - 0 1")
    click_knight(page)
    page.wait_for_function("document.querySelectorAll('#board .safe i.bad').length === 1")   # e4: the pawn takes it
    assert page.locator("#board .safe i.ok").count() >= 5
    click_knight(page)                       # put it down again
    page.wait_for_function(SHOWN % "safe" + " === 0")
    click_knight(page)
    page.wait_for_selector("#board .safe i.bad")
    page.uncheck("#show-safe")
    page.wait_for_function(SHOWN % "safe" + " === 0")
    assert not errors, errors
