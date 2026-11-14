"""Synthetic terminal width regression corpus; no network or participation rows."""
from pathlib import Path
import pytest
import pro_football_slm as cli
from pro_football_slm.output_width import width, fit

PLAY = dict(play_id=1000, game_id="2024_01_BAL_KC", season=2024, week=1, qtr=1,
            posteam="KC", defteam="BAL", home_team="KC", away_team="BAL", conf="AFC",
            division="AFC West", down=2, ydstogo=4, yardline_100=26, play_type="run",
            rush_attempt=1, pass_attempt=0, yards_gained=2, epa=-.4, away_score=29,
            home_score=10, qb_name="P.Mahomes", passer_player_name="P.Mahomes",
            rusher_player_name="I.Pacheco", receiver_player_name="T.Kelce",
            desc="Synthetic runner advances two yards. " * 24)
ENGINE = cli.StatEngine()
SCHEMES = ['screen', 'play_action_deep', 'quick_slant', 'intermediate_cross',
           'rush_inside', 'rush_outside', 'power_gap', 'qb_scramble',
           'pass_rush_sack', 'turnover_interception', 'tfl_run_stop', 'field_goal', 'punt']

def corpus(cols):
    yield 'play_feed', cli.render_game_plays_table([PLAY], cols=cols)
    yield 'deep_dive', cli.render_single_play_deep_dive(PLAY, cols=cols)
    yield 'player_card', cli.render_player_drilldown_view(ENGINE, [PLAY], 2024, 'I.Pacheco', interactive=False, cols=cols)
    yield 'team_card', cli.render_team_drilldown_view(ENGINE, [PLAY], 2024, 'KC', interactive=False, cols=cols)
    yield 'leaders', cli.render_general_stat_view(ENGINE, [PLAY], 'rushing_yards', 2024, min_attempts=0, cols=cols)
    yield 'table', cli.AsciiArtRenderer.render_table('Synthetic table', ['Name', 'Description'], [['Example', 'long ' * 100]], cols=cols)
    yield 'hud', cli.AsciiArtRenderer.render_situation_hud(PLAY, cols=cols)
    for scheme in SCHEMES:
        yield 'chalkboard_' + scheme, cli.AsciiArtRenderer.render_generic_play_concept_diagram(scheme, cols=cols)
    for camera in ['behind-offense', 'behind-defense', 'sideline']:
        yield 'diagram_' + camera, cli.AsciiArtRenderer.render_field_and_play(PLAY, camera=camera, cols=cols)

@pytest.mark.parametrize('cols', [123, 80, 20])
def test_all_renderers_fit(cols):
    for name, text in corpus(cols):
        for line in cli.strip_ansi(text).splitlines():
            assert width(line) <= cols, (name, cols, width(line), line)

def test_feed_golden_123():
    actual = cli.strip_ansi(cli.render_game_plays_table([PLAY], title='SYNTHETIC GAME (123 columns)'))
    expected = (Path(__file__).parent / 'fixtures/play_feed_123.txt').read_text().rstrip('\n')
    assert actual == expected
    assert all(width(line) == 123 for line in actual.splitlines())
    assert '│ Play  │ Q  │ Tm  │ Dn&Dist  │ Yard   │' in actual
    assert '#1000' in actual
    assert 'Synthetic runner advances ' in actual

def test_narrow_feed_keeps_every_field():
    text = cli.render_game_plays_table([PLAY], cols=80)
    assert 'play_id: 1000' in text and 'away_score: 29' in text
    assert text.count('Synthetic runner') == 24

def test_wide_unicode_and_combining_prose():
    for line in fit('漢字 e\u0301 ⚠️ ' * 100, 20).splitlines():
        assert width(line) <= 20
