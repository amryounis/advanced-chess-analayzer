"""Stepping back and forth through the game."""

import chess

from uciboard.api import Api
from test_api_evolution import SCHOLARS, settings  # noqa: F401  (same helpers)


def loaded(tmp_path):
    api = Api(settings(tmp_path))
    api.load_pgn(SCHOLARS)
    return api


def test_stepping_back_shows_the_earlier_position_and_keeps_the_game(tmp_path):
    api = loaded(tmp_path)
    st = api.step(-1)
    assert st["ply"] == 6 and len(st["moves"]) == 7 and st["over"] == ""
    assert st["fen"] != st["game_fen"] and st["last"] == ["g8", "f6"]
    assert st["turn"] == "white" and st["dests"]                       # and it is playable from there
    st = api.goto_ply(0)
    assert st["ply"] == 0 and st["fen"] == chess.STARTING_FEN and st["last"] is None
    assert api.step(-1)["ply"] == 0                                    # no further back than the start
    assert api.goto_ply(10_000)["ply"] == 7 and api.state()["over"].startswith("Checkmate")
    assert api.step(1)["ply"] == 7                                     # nor past the end


def test_playing_the_games_next_move_just_steps_on(tmp_path):
    api = loaded(tmp_path)
    api.goto_ply(2)
    st = api.move("f1", "c4")                                          # Bc4, as in the game
    assert st["ply"] == 3 and len(st["moves"]) == 7


def test_a_different_move_replaces_the_rest_of_the_game(tmp_path):
    api = loaded(tmp_path)
    api.goto_ply(2)
    st = api.move("g1", "f3")
    assert st["moves"] == ["e4", "e5", "Nf3"] and st["ply"] == 3


def test_undo_takes_back_the_move_on_the_board(tmp_path):
    api = loaded(tmp_path)
    assert api.undo()["moves"][-1] == "Nf6"                            # at the end: the last move goes
    api = loaded(tmp_path)
    api.goto_ply(3)
    st = api.undo()
    assert st["moves"] == ["e4", "e5"] and st["ply"] == 2              # stepped back: the moves after go too


def test_looking_at_a_graph_position_gives_way_to_stepping(tmp_path):
    api = loaded(tmp_path)
    api.view_position("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1")
    st = api.step(-1)
    assert not st["viewing"] and st["ply"] == 6


def test_new_and_pgn_loading_reset_the_cursor(tmp_path):
    api = loaded(tmp_path)
    api.goto_ply(3)
    assert api.load_pgn(SCHOLARS)["ply"] == 7
    api.goto_ply(3)
    assert api.reset()["ply"] == 0


def test_the_buttons_keys_and_move_list_step_through_the_game(make_page, stockfish, tmp_path):
    import pytest  # noqa: F401
    from uciboard import config
    s = config.load_settings(stockfish=stockfish)
    api = Api(s)
    api.load_pgn(SCHOLARS)
    api.start()                      # so the page's own start() answers at once and cannot land after a click
    page, errors = make_page(api)
    fen = "document.getElementById('board').dataset.fen"
    page.wait_for_function(f"{fen}.startsWith('r1bqkb1r/pppp1Qpp')")        # the final position
    assert page.is_disabled("#nav-next") and page.is_disabled("#nav-end") and page.is_enabled("#nav-prev")
    assert page.inner_text("#nav-pos") == "move 7 of 7"
    page.click("#nav-prev")
    page.wait_for_function(f"{fen}.startsWith('r1bqkb1r/pppp1ppp/2n2n2/4p2Q')")
    assert page.inner_text("#nav-pos") == "move 6 of 7"
    assert page.locator("#moves .mv.later").count() == 1                     # Qxf7# is greyed, not gone
    page.keyboard.press("Home")
    page.wait_for_function(f"{fen}.startsWith('rnbqkbnr/pppppppp')")
    assert page.is_disabled("#nav-start") and page.is_disabled("#nav-prev")
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.wait_for_function(f"{fen}.startsWith('rnbqkbnr/pppp1ppp/8/4p3/4P3')")
    page.locator("#moves .mv", has_text="Qh5").click()
    page.wait_for_function(f"{fen}.startsWith('r1bqkbnr/pppp1ppp/2n5/4p2Q')")
    page.keyboard.press("End")
    page.wait_for_function(f"{fen}.startsWith('r1bqkb1r/pppp1Qpp')")
    assert not errors, errors
