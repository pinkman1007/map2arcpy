"""The shipped recipe library: every recipe must parse 100% clean."""
import ast

from map2arcpy import recipes
from map2arcpy.generator import generate
from map2arcpy.parsers import steps


def test_catalog_lists_recipes():
    names = recipes.list_recipes()
    assert len(names) >= 8
    assert "ward_choropleth" in names and "flood_buffer" in names
    cat = recipes.catalog()
    for n in names:
        assert cat[n]["title"] and cat[n]["text"]


def test_every_shipped_recipe_is_fully_understood():
    for name in recipes.list_recipes():
        spec = steps.parse(recipes.get(name), name_hint=name)
        bad = [n for n in spec.notes if "NOT UNDERSTOOD" in n]
        assert not bad, f"recipe '{name}' has unparsed steps: {bad}"


def test_every_shipped_recipe_generates_valid_scripts():
    from map2arcpy.generator.emit_gpd import generate_gpd
    for name in recipes.list_recipes():
        spec = steps.parse(recipes.get(name), name_hint=name)
        ast.parse(generate(spec, strict=False))          # arcpy backend
        ast.parse(generate_gpd(spec, strict=False))      # open-source backend


def test_comment_lines_are_not_steps():
    text = "# a comment\n1. load wards.shp\n# another\n2. label by NAME"
    assert steps.split_steps(text) == ["load wards.shp", "label by NAME"]


def test_unknown_recipe_is_clean_error():
    import pytest
    with pytest.raises(ValueError):
        recipes.get("does_not_exist")
