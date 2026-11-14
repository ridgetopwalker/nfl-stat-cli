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
    assert 'Synthetic runner advances…' in actual

def test_narrow_feed_keeps_every_field():
    text = cli.render_game_plays_table([PLAY], cols=80)
    assert 'play_id: 1000' in text and 'away_score: 29' in text
    assert text.count('Synthetic runner') == 24

def test_wide_unicode_and_combining_prose():
    for line in fit('漢字 e\u0301 ⚠️ ' * 100, 20).splitlines():
        assert width(line) <= 20

@pytest.mark.parametrize('cols', [123, 80, 20])
def test_table_preserves_complete_cells(cols):
    value = '123456789.12345679'
    identifier = 'SYNTHETIC_IDENTIFIER_98765432101234567890'
    text = cli.strip_ansi(cli.AsciiArtRenderer.render_table(
        'Synthetic', ['Entity', 'Value'], [[identifier, value]], cols=cols))
    rows = [line.split('│')[1:-1] for line in text.splitlines() if line.startswith('│')][1:]
    assert ''.join(row[0].strip() for row in rows) == identifier
    assert ''.join(row[1].strip() for row in rows) == value
    assert max(map(width, text.splitlines())) <= cols

@pytest.mark.parametrize('cols', [80, 20])
def test_compact_structure_goldens(cols):
    play = dict(play_id=1000, game_id='SYNTHETIC', qtr=1, posteam='AAA', defteam='BBB',
                down=2, ydstogo=4, yardline_100=26, play_type='run', desc='Synthetic description')
    outputs = {
        'card': cli.render_single_play_deep_dive(play, cols=cols),
        'hud': cli.AsciiArtRenderer.render_situation_hud(play, cols=cols),
        'chalkboard': cli.AsciiArtRenderer.render_generic_play_concept_diagram('screen', cols=cols),
        'field': cli.AsciiArtRenderer.render_field_and_play(play, cols=cols),
    }
    for name, text in outputs.items():
        text = cli.strip_ansi(text)
        expected = (Path(__file__).parent / f'fixtures/width_{name}_{cols}.txt').read_text(encoding='utf-8')
        assert text + '\n' == expected
        for line in text.splitlines():
            assert width(line) == cols
            assert (line.startswith('┌') and line.endswith('┐') or
                    line.startswith('│ ') and line.endswith(' │') or
                    line.startswith('└') and line.endswith('┘'))
        assert 'Compact' in outputs['field']
    content = ''.join(line[2:-2].strip() for line in cli.strip_ansi(outputs['card']).splitlines()[1:-1])
    assert 'AAAvsBBB(0-0)' in content.replace(' ', '')
    assert 'SYNTHETIC' in content


def test_highlight_keeps_display_widths(monkeypatch):
    monkeypatch.setattr(cli.C, "BOLD", "\x1b[1m")
    monkeypatch.setattr(cli.C, "GOLD", "\x1b[33m")
    monkeypatch.setattr(cli.C, "RESET", "\x1b[0m")
    plain = cli.render_game_plays_table([PLAY])
    highlighted = cli.render_game_plays_table([PLAY], highlight_play_id=1000)
    assert highlighted != plain
    assert cli.strip_ansi(highlighted) == cli.strip_ansi(plain)
    assert f'{cli.C.BOLD}{cli.C.GOLD}│' in highlighted


def test_feed_marks_shortened_descriptions_and_preserves_large_ids():
    assert '…' in cli.render_game_plays_table([PLAY])
    play = dict(PLAY, play_id=1234567890123456789)
    assert '1234567890123456789' in cli.render_game_plays_table([play])


def test_prose_wrapper_never_slices_finished_frames():
    drawing = '┌' + '─' * 60 + '┐\n│ ' + 'x' * 58 + ' │\n└' + '─' * 60 + '┘'
    assert fit(drawing, 20) == drawing


@pytest.mark.parametrize('cols', [123, 80, 20, 79, 21])
def test_table_keeps_emoji_selectors_and_complete_cells(cols):
    emoji = '\u26a0\ufe0f' * 60
    value = '123456789.12345679'
    text = cli.strip_ansi(cli.AsciiArtRenderer.render_table(
        'Synthetic', ['Name', 'Value'], [[emoji, value]], cols=cols))
    rows = [line.split('\u2502')[1:-1] for line in text.splitlines() if line.startswith('\u2502')][1:]
    if cols == 80:
        assert width(rows[0][0]) % 2 == 1  # Exercise an odd cell interior.
    assert ''.join(row[0].strip() for row in rows) == emoji
    assert ''.join(row[1].strip() for row in rows) == value
    for row in rows:
        cell = row[0].strip()
        assert not cell.startswith('\ufe0f')
        assert cell == '\u26a0\ufe0f' * (len(cell) // 2)
    assert max(map(width, text.splitlines())) <= cols
    assert all(width(line) == cols for line in text.splitlines() if line.startswith('\u2502'))


@pytest.mark.parametrize('cols', [123, 80, 20])
def test_long_chalkboard_title_preserved_in_complete_frame(cols):
    title = 'Synthetic title ' * 12
    text = cli.strip_ansi(cli.AsciiArtRenderer.render_generic_play_concept_diagram(
        'screen', title=title, cols=cols))
    lines = text.splitlines()
    assert lines[0] == '\u250c' + '\u2500' * (cols - 2) + '\u2510'
    assert lines[-1] == '\u2514' + '\u2500' * (cols - 2) + '\u2518'
    assert all(width(line) == cols and line.startswith('\u2502 ') and line.endswith(' \u2502')
               for line in lines[1:-1])
    content = ''.join(line[2:-2].strip() for line in lines[1:-1])
    assert title.replace(' ', '') in content.replace(' ', '')
