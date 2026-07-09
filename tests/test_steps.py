"""Step-by-step recipes: detection, ordered application, step tagging."""
import ast

from map2arcpy.detect import parse_any
from map2arcpy.generator import generate
from map2arcpy.parsers import steps

RECIPE = """1. load wards.shp
2. clip to district_boundary.shp
3. choropleth of pop_density using greens
4. label by ward_name
5. buffer hospitals.shp by 500 m
6. titled 'Dense Wards', A3 landscape
7. export pdf at 300 dpi"""


# ---- detection --------------------------------------------------------------
def test_numbered_lines_detected():
    assert steps.looks_like_steps(RECIPE)


def test_bullets_and_step_words_detected():
    assert steps.looks_like_steps("- load wards.shp\n- buffer by 1 km")
    assert steps.looks_like_steps("Step 1: load wards.shp\nStep 2. clip to city.shp")


def test_single_sentence_not_steps():
    assert not steps.looks_like_steps("choropleth of pop_density titled 'X'")


def test_plain_prose_not_steps():
    assert not steps.looks_like_steps(
        "a map of the wards\nwith a choropleth of density\nand labels")


def test_parse_any_routes_recipes_to_steps():
    assert parse_any(RECIPE).source_kind == "steps"
    assert parse_any("map of wards.shp in red").source_kind == "natural-language"


# ---- ordered application ----------------------------------------------------
def test_recipe_builds_ordered_spec():
    spec = parse_any(RECIPE)
    names = [l.name for l in spec.layers]
    assert "wards" in names and "district_boundary" in names and "hospitals" in names
    tools = [op.tool for op in spec.operations]
    assert tools == ["clip", "buffer"]          # step order preserved
    # step 3's choropleth lands on step 2's clipped output
    clipped = next(l for l in spec.layers if l.name == "clipped")
    assert clipped.renderer.type == "graduated"
    assert clipped.renderer.field == "pop_density"
    assert clipped.label_field == "ward_name"
    # layout steps applied
    assert spec.layout.title == "Dense Wards"
    assert spec.layout.page == "A3L"
    assert spec.layout.dpi == 300
    assert spec.layout.export.endswith(".pdf")


def test_each_op_carries_its_step_tag():
    spec = parse_any(RECIPE)
    for op in spec.operations:
        assert op.params.get("step", "").startswith("STEP ")


def test_every_step_accounted_for_in_notes():
    spec = parse_any(RECIPE)
    for i in range(1, 8):
        assert any(n.startswith(f"STEP {i} ") for n in spec.notes), f"step {i} missing"


# ---- failure honesty ----------------------------------------------------------
def test_ununderstood_step_becomes_todo_not_dropped():
    spec = parse_any("1. load wards.shp\n2. frobnicate the doohickey\n"
                     "3. choropleth of pop_density")
    assert any("STEP 2 NOT UNDERSTOOD" in n for n in spec.notes)
    code = generate(spec, strict=False)
    assert "# TODO (step): STEP 2 NOT UNDERSTOOD" in code


# ---- generated script ---------------------------------------------------------
def test_script_has_step_banners_and_parses():
    code = generate(parse_any(RECIPE), strict=False)
    ast.parse(code)
    assert "# ==== STEP 2: clip to district_boundary.shp" in code
    assert "# ==== STEP 5: buffer hospitals.shp" in code
    # the recipe account survives in the header
    assert "STEP 3 ok" in code and "STEP 7 ok" in code


def test_unmarked_line_between_marked_ones_still_runs():
    spec = parse_any("1. load wards.shp\nclip to city.shp\n2. label by ward_name")
    assert [op.tool for op in spec.operations] == ["clip"]
    assert any("STEP 2 ok" in n for n in spec.notes)


# ---- "did you mean" suggestions ----------------------------------------------
def test_suggestions_for_synonyms_and_typos():
    from map2arcpy.parsers.steps import suggest_phrasing
    assert suggest_phrasing("crop it to the city area") == ["'clip to boundary.shp'"]
    assert "choropleth" in suggest_phrasing("shade the wards by density")[0]
    assert "buffer" in suggest_phrasing("bufer roads by 500")[0]      # typo
    assert "erase" in suggest_phrasing("remove the water bodies")[0]
    assert suggest_phrasing("frobnicate the doohickey") == []          # honest


def test_suggestion_lands_in_note_and_script():
    spec = parse_any("1. load wards.shp\n2. crop it to the city area\n"
                     "3. choropleth of pop_density")
    bad = next(n for n in spec.notes if "STEP 2 NOT UNDERSTOOD" in n)
    assert "did you mean: 'clip to boundary.shp'" in bad
    assert "GRAMMAR.md" in bad
    code = generate(parse_any("1. load wards.shp\n2. crop it to the city"),
                    strict=False)
    assert "did you mean" in code
