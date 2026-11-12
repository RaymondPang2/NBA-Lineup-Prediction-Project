"""The feature dictionary is complete and the documentation covers every feature."""
from nba_lineups.config import PROJECT_ROOT
from nba_lineups.modeling import registry


def test_dictionary_is_complete():
    d = registry.dictionary()
    assert d.name.is_unique and len(d) == len(registry.FEATURE_NAMES)
    assert set(d.group) <= {"team", "player", "lineup"}
    assert (d.window == "pre_asb").all() and (d.available_at == registry.AVAILABLE_AT).all()
    for col in ("description", "source", "fitted", "no_history"):
        assert (d[col].str.len() > 0).all(), col


def test_documentation_mentions_every_feature():
    doc = (PROJECT_ROOT / "docs" / "features_baselines.md").read_text()
    missing = [f for f in registry.FEATURE_NAMES if f"`{f}`" not in doc]
    assert not missing, f"undocumented features: {missing}"
