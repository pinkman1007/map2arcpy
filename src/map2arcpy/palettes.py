"""Colour vocabulary shared by the parsers and the generator.

Ramps are ColorBrewer-derived (colorbrewer2.org, Apache-2.0 palette values),
chosen to be print-safe at 300 dpi.
"""

NAMED_COLORS = {
    "red": "#D7191C", "orange": "#ED7D31", "yellow": "#FFC000",
    "green": "#1A9641", "dark green": "#006837", "light green": "#A6D96A",
    "blue": "#2C7BB6", "dark blue": "#1F3864", "light blue": "#92C5DE",
    "teal": "#2E6B7E", "cyan": "#4C9AA8", "purple": "#7B3294",
    "magenta": "#C51B7D", "pink": "#F1B6DA", "brown": "#8C510A",
    "grey": "#808080", "gray": "#808080", "black": "#1A1A1A",
    "white": "#FFFFFF", "beige": "#FEE08B",
}

RAMPS = {
    # sequential
    "greens":  ["#FFFFCC", "#C2E699", "#78C679", "#31A354", "#006837"],
    "blues":   ["#EFF3FF", "#BDD7E7", "#6BAED6", "#3182BD", "#08519C"],
    "reds":    ["#FEE5D9", "#FCAE91", "#FB6A4A", "#DE2D26", "#A50F15"],
    "oranges": ["#FEEDDE", "#FDBE85", "#FD8D3C", "#E6550D", "#A63603"],
    "viridis": ["#440154", "#3B528B", "#21918C", "#5EC962", "#FDE725"],
    # diverging
    "red_blue":   ["#CA0020", "#F4A582", "#F7F7F7", "#92C5DE", "#0571B0"],
    "brown_teal": ["#A6611A", "#DFC27D", "#F5F5F5", "#80CDC1", "#018571"],
}

DEFAULT_RAMP = "viridis"

#: sensible single-colour defaults per geometry when nothing is specified
GEOMETRY_DEFAULTS = {
    "point":   "#D7191C",
    "line":    "#2C7BB6",
    "polygon": "#A9CCD4",
    "raster":  None,
}

#: ArcGIS Pro basemap display names the NL parser can recognise
BASEMAPS = {
    "imagery": "Imagery",
    "satellite": "Imagery",
    "imagery hybrid": "Imagery Hybrid",
    "topographic": "Topographic",
    "topo": "Topographic",
    "streets": "Streets",
    "osm": "OpenStreetMap",
    "openstreetmap": "OpenStreetMap",
    "dark gray": "Dark Gray Canvas",
    "dark grey": "Dark Gray Canvas",
    "light gray": "Light Gray Canvas",
    "light grey": "Light Gray Canvas",
    "terrain": "Terrain with Labels",
    "oceans": "Oceans",
    "navigation": "Navigation",
}


def categorical_palette(n: int):
    """n distinct print-safe colours (cycles past 12)."""
    base = ["#1A9641", "#2C7BB6", "#D7191C", "#FFC000", "#7B3294", "#ED7D31",
            "#4C9AA8", "#C51B7D", "#8C510A", "#A6D96A", "#92C5DE", "#808080"]
    return [base[i % len(base)] for i in range(max(0, n))]
