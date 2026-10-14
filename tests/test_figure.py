from bench import figure
from bench.score import RESULTS, read_results


def test_committed_figures_match_a_fresh_run():
    # Catches results rescored without redrawing the README's figure.
    data = figure.bars(read_results(RESULTS))
    for mode, path in figure.FILES.items():
        assert path.read_text(encoding="utf-8") == figure.svg(data, mode)


def test_each_bar_splits_its_markers_into_shares():
    for bar in figure.bars(read_results(RESULTS)):
        assert 0 <= bar.wrong <= 1 - bar.right
        assert 0 < bar.copied <= 1
