"""
Intelligent recommendation engine for map generation.

This module analyzes user descriptions and recommends:
- Optimal web data sources (OSM tags, AGOL layers)
- Best geoprocessing approaches
- Cartographic best practices
- CRS and extent optimization

All recommendations are deterministic and can be executed to generate maps.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

# Map keywords to OSM/AGOL data sources with confidence scores
_DATA_RECOMMENDATIONS = {
    # Healthcare
    ("hospital", "clinic", "health"): {
        "osm": "hospitals",
        "description": "Medical facilities from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["amenity=hospital", "amenity=clinic"],
    },
    ("pharmacy", "pharmacies"): {
        "osm": "pharmacies",
        "description": "Pharmacy locations from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["amenity=pharmacy"],
    },
    
    # Education
    ("school", "schools"): {
        "osm": "schools",
        "description": "School locations from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["amenity=school"],
    },
    ("university", "college", "universities", "colleges"): {
        "osm": "universities",
        "description": "Higher education institutions from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["amenity=university", "amenity=college"],
    },
    
    # Transportation
    ("airport", "airports"): {
        "osm": "airports",
        "description": "Airports from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["aeroway=aerodrome"],
    },
    ("bus", "bus stop", "public transport"): {
        "osm": "bus stops",
        "description": "Public transport stops from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["highway=bus_stop"],
    },
    ("railway", "rail", "station"): {
        "osm": "railway",
        "description": "Railway infrastructure from OpenStreetMap",
        "confidence": 0.85,
        "tags": ["railway=station"],
    },
    
    # Amenities
    ("bank", "banks"): {
        "osm": "banks",
        "description": "Banks from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["amenity=bank"],
    },
    ("atm"): {
        "osm": "atms",
        "description": "ATM locations from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["amenity=atm"],
    },
    ("police", "fire station"): {
        "osm": "fire stations",
        "description": "Emergency services from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["amenity=police", "amenity=fire_station"],
    },
    
    # Leisure & Nature
    ("park", "parks", "green space"): {
        "osm": "parks",
        "description": "Parks from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["leisure=park"],
    },
    ("water", "water body", "lake", "river"): {
        "osm": "water bodies",
        "description": "Water features from OpenStreetMap",
        "confidence": 0.9,
        "tags": ["natural=water"],
    },
    ("forest", "woodland"): {
        "osm": "forest",
        "description": "Forest areas from OpenStreetMap",
        "confidence": 0.85,
        "tags": ["landuse=forest"],
    },
    
    # Infrastructure
    ("building", "buildings"): {
        "osm": "buildings",
        "description": "Building footprints from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["building"],
    },
    ("road", "roads", "highway"): {
        "osm": "roads",
        "description": "Road network from OpenStreetMap",
        "confidence": 0.95,
        "tags": ["highway"],
    },
}

# Map type detection patterns
_MAP_TYPE_PATTERNS = {
    "choropleth": r"\b(?:choropleth|by|classified by|color by|shade by)\b",
    "heatmap": r"\b(?:heatmap|density|heat map|hotspot)\b",
    "buffer": r"\b(?:buffer|distance|proximity|zone)\b",
    "overlay": r"\b(?:overlay|combine|layer|drape|over)\b",
    "terrain": r"\b(?:terrain|elevation|slope|hillshade|dem|digital elevation)\b",
    "change": r"\b(?:change|difference|before and after|temporal|time series)\b",
    "network": r"\b(?:network|connectivity|path|route|catchment)\b",
}

# GIS best practices by map type
_MAP_TYPE_PRACTICES = {
    "choropleth": {
        "color_ramp": "sequential or diverging (colorblind-safe)",
        "classification": "quantile or natural breaks (5-7 classes optimal)",
        "projection": "projected CRS (UTM recommended for local analysis)",
        "tips": ["Use sequential for ordered data", "Center diverging ramps on zero for anomalies", "Normalize by area or population for fair comparison"],
    },
    "heatmap": {
        "color_ramp": "sequential from cool to warm (viridis or inferno)",
        "classification": "continuous (no classification needed)",
        "projection": "projected CRS with appropriate cell size",
        "tips": ["Use Spatial Analyst > Density for vector data", "Consider cell size relative to feature density", "Filter outliers for better visualization"],
    },
    "buffer": {
        "operation": "Buffer analysis followed by Clip",
        "projection": "projected CRS (meters or feet required)",
        "tips": ["Specify buffer distance in ground units", "Use Dissolve to merge overlapping buffers", "Clip result to study area for clean extent"],
    },
    "terrain": {
        "operation": "Slope and Hillshade derivatives from DEM",
        "projection": "projected CRS preserving vertical units",
        "tips": ["Use azimuth 315°, altitude 45° for classic hillshade", "Slope output in degrees or percent slope", "Combine hillshade with draped thematic layer"],
    },
}

# Geoprocessing operation recommendations
_OPERATION_PATTERNS = {
    "buffer": r"\b(?:buffer|proximity zone|within \d+ (?:km|m|miles|feet|meters))\b",
    "clip": r"\b(?:clip|within|boundary|extent|area)\b",
    "dissolve": r"\b(?:dissolve|merge|aggregate|union)\b",
    "select": r"\b(?:select|filter|where|query)\b",
    "join": r"\b(?:join|relate|spatial join|intersect)\b",
    "zonal_stats": r"\b(?:zonal|per (?:zone|ward|district)|statistics)\b",
}

# CRS recommendations by region
_CRS_RECOMMENDATIONS = {
    "india": {"utm_zone": 43, "default_epsg": 32643, "name": "WGS 84 / UTM zone 43N"},
    "visakhapatnam": {"utm_zone": 48, "default_epsg": 32648, "name": "WGS 84 / UTM zone 48N"},
}


def detect_map_types(description: str) -> List[Tuple[str, float]]:
    """
    Detect map types from user description.
    
    Returns:
        List of (map_type, confidence) tuples, sorted by confidence.
    """
    low_desc = description.lower()
    detected: Dict[str, float] = {}
    
    for map_type, pattern in _MAP_TYPE_PATTERNS.items():
        if re.search(pattern, low_desc, re.IGNORECASE):
            # Boost confidence if multiple keywords match
            confidence = 0.8
            match_count = len(re.findall(pattern, low_desc, re.IGNORECASE))
            confidence = min(0.99, 0.8 + match_count * 0.1)
            detected[map_type] = confidence
    
    return sorted(detected.items(), key=lambda x: x[1], reverse=True)


def recommend_data_sources(
    description: str, web_enabled: bool = True
) -> Dict[str, Any]:
    """
    Recommend optimal web data sources based on description.
    
    Returns:
        Dict with:
        - sources: List of {osm, description, confidence, tags}
        - location: Detected place name
        - web_enrichment_available: Boolean
    """
    low_desc = description.lower()
    recommended: Dict[str, Dict[str, Any]] = {}
    
    # Extract place name (for web geo-referencing)
    place_match = re.search(
        r"\b(?:in|from|for|near|around)\s+([A-Z][A-Za-z\s'-]+)",
        description
    )
    location = place_match.group(1).strip() if place_match else None
    
    # Find matching data sources
    for keywords, source_info in _DATA_RECOMMENDATIONS.items():
        for keyword in keywords:
            if keyword in low_desc:
                key = source_info["osm"]
                if key not in recommended:
                    recommended[key] = source_info.copy()
                # Boost confidence if already found
                recommended[key]["confidence"] = min(
                    0.99, recommended[key].get("confidence", 0.8) + 0.05
                )
                break
    
    return {
        "sources": list(recommended.values()),
        "location": location,
        "web_enrichment_available": web_enabled,
        "instructions": _generate_web_instructions(
            list(recommended.values()), location
        ),
    }


def recommend_operations(description: str) -> Dict[str, Any]:
    """
    Recommend geoprocessing operations based on description.
    
    Returns:
        Dict with:
        - operations: List of operation names with rationale
        - sequence: Suggested operation order
        - warnings: Any missing or conflicting operations
    """
    low_desc = description.lower()
    detected_ops: Dict[str, Dict[str, Any]] = {}
    
    for op_name, pattern in _OPERATION_PATTERNS.items():
        matches = re.findall(pattern, low_desc, re.IGNORECASE)
        if matches:
            detected_ops[op_name] = {
                "detected_phrases": matches,
                "confidence": min(0.99, 0.7 + len(matches) * 0.15),
            }
    
    # Suggest operation sequence
    # General order: load -> select -> buffer/clip -> dissolve -> join -> zonal -> output
    suggested_order = [
        "select",
        "buffer",
        "clip",
        "dissolve",
        "join",
        "zonal_stats",
    ]
    sequence = [op for op in suggested_order if op in detected_ops]
    
    warnings = []
    if "buffer" in detected_ops and "clip" in detected_ops:
        # Good combination
        pass
    if "join" in detected_ops and not any(op in detected_ops for op in ["select"]):
        warnings.append(
            "Spatial join recommended after filtering/selecting features"
        )
    
    return {
        "operations": detected_ops,
        "sequence": sequence,
        "warnings": warnings,
    }


def recommend_cartography(description: str) -> Dict[str, Any]:
    """
    Recommend cartographic best practices.
    
    Returns:
        Dict with:
        - detected_types: Map types detected
        - color_ramps: Recommended color schemes
        - classification: Recommended classification methods
        - layout: Page size and DPI recommendations
    """
    map_types = detect_map_types(description)
    
    recommendations = {
        "detected_types": [t[0] for t in map_types],
        "primary_type": map_types[0][0] if map_types else "generic",
        "practices": {},
        "color_recommendations": [],
        "classification_recommendations": [],
    }
    
    for map_type, confidence in map_types:
        if map_type in _MAP_TYPE_PRACTICES:
            practices = _MAP_TYPE_PRACTICES[map_type]
            recommendations["practices"][map_type] = practices
            
            if "color_ramp" in practices:
                recommendations["color_recommendations"].append({
                    "type": map_type,
                    "recommended": practices["color_ramp"],
                })
            
            if "classification" in practices:
                recommendations["classification_recommendations"].append({
                    "type": map_type,
                    "recommended": practices["classification"],
                })
    
    # General layout recommendations based on presence of "large", "regional", etc.
    if re.search(r"\b(?:large|regional|country|state|province)\b", description, re.I):
        recommendations["layout"] = {"page": "A1L", "dpi": 300, "title": True}
    elif re.search(r"\b(?:small|local|detailed|city|ward)\b", description, re.I):
        recommendations["layout"] = {"page": "A3P", "dpi": 300, "title": True}
    else:
        recommendations["layout"] = {"page": "A4L", "dpi": 300, "title": True}
    
    return recommendations


def recommend_crs(description: str, place_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Recommend coordinate reference system based on location and analysis type.
    
    Returns:
        Dict with:
        - recommended_epsg: EPSG code
        - reason: Why this CRS is recommended
        - utm_zone: UTM zone if applicable
    """
    low_desc = description.lower()
    
    # Check for specific locations
    for location, crs_info in _CRS_RECOMMENDATIONS.items():
        if location in low_desc:
            return {
                "recommended_epsg": crs_info["default_epsg"],
                "name": crs_info["name"],
                "utm_zone": crs_info["utm_zone"],
                "reason": f"UTM Zone {crs_info['utm_zone']}N optimal for {location}",
                "confidence": 0.9,
            }
    
    # Check for analysis type requiring projected CRS
    if any(
        term in low_desc
        for term in ["buffer", "distance", "area", "slope", "terrain", "density"]
    ):
        return {
            "recommended_epsg": 32643,  # India default (UTM 43N)
            "name": "WGS 84 / UTM zone 43N (India)",
            "utm_zone": 43,
            "reason": "Projected CRS (UTM) required for accurate distance/area measurements",
            "confidence": 0.8,
        }
    
    # Default to WGS 84
    return {
        "recommended_epsg": 4326,
        "name": "WGS 84",
        "reason": "Geographic CRS suitable for web mapping and display",
        "confidence": 0.5,
    }


def generate_optimized_instructions(description: str, web_enabled: bool = True) -> str:
    """
    Generate optimized map2arcpy instructions from user description.
    
    This intelligently combines data recommendations, operations, and cartography
    into a complete, executable instruction string.
    
    Returns:
        Optimized instruction string ready for map2arcpy.generate()
    """
    # Gather all recommendations
    data_recs = recommend_data_sources(description, web_enabled)
    op_recs = recommend_operations(description)
    cart_recs = recommend_cartography(description)
    crs_recs = recommend_crs(description, data_recs.get("location"))
    
    # Build instruction string
    parts = []
    
    # 1. Data loading
    if data_recs["sources"] and web_enabled:
        source_desc = ", ".join(s["osm"] for s in data_recs["sources"][:2])
        location = data_recs["location"] or "the map area"
        parts.append(f"{source_desc} from osm in {location}")
    
    # 2. Operations in suggested order
    for op in op_recs["sequence"]:
        if op == "buffer":
            # Try to extract buffer distance
            match = re.search(r"(\d+)\s*(?:km|m|miles|feet)", description, re.I)
            dist = match.group(1) if match else "500"
            unit = "m"  # Default to meters
            parts.append(f"buffer by {dist} {unit}")
        elif op == "clip":
            parts.append("clip to study area")
        elif op == "dissolve":
            parts.append("dissolve")
        elif op == "select":
            parts.append("filter by criteria")
        elif op == "join":
            parts.append("spatial join")
    
    # 3. Cartography (if detected)
    primary_type = cart_recs.get("primary_type", "generic")
    if primary_type == "choropleth":
        # Try to detect the field to classify by
        field_match = re.search(r"by\s+(\w+)", description, re.I)
        if field_match:
            field = field_match.group(1)
            parts.append(f"choropleth of {field}, classify=quantile, classes=5")
        else:
            # Fallback for generic choropleth without field detected
            parts.append("choropleth, classify=quantile, classes=5")
    elif primary_type == "heatmap":
        parts.append("density heatmap")
    
    # 4. Layout and export
    layout = cart_recs.get("layout", {})
    page = layout.get("page", "A4L")
    
    # Extract title more intelligently
    title_match = re.search(r"titled?\s+['\"]?([^'\"]+)['\"]?", description, re.I)
    title = title_match.group(1).strip() if title_match else "Untitled Map"
    
    # Extract page size if specified in description
    # Look for patterns like "A3 landscape", "A4L", "LetterP", etc.
    page_patterns = [
        r"\b(A[0-4])([LP]?)\b",  # A0-4 with optional L/P
        r"\b(Letter)([LP]?)\b",  # Letter with optional L/P
    ]
    
    for pattern in page_patterns:
        match = re.search(pattern, description, re.I)
        if match:
            size = match.group(1).upper()  # Get "A3", "A4", etc.
            orientation = (match.group(2) or "").upper()
            
            # Validate page size
            valid_sizes = ["A0", "A1", "A2", "A3", "A4", "LETTER"]
            if size in valid_sizes:
                # Build page code
                if not orientation:
                    orientation = "L"  # Default to landscape
                page = f"{size}{orientation}"
                break
    
    # Check for landscape/portrait orientation override
    if re.search(r"\b(?:landscape|horizontal)\b", description, re.I):
        page = page.replace("P", "L") if page.endswith("P") else page
    elif re.search(r"\b(?:portrait|vertical)\b", description, re.I):
        page = page.replace("L", "P") if page.endswith("L") else page
    
    parts.append(f"titled '{title}', {page}, 300 dpi")
    
    # 5. CRS recommendation
    if crs_recs["recommended_epsg"] != 4326:
        parts.append(f"EPSG:{crs_recs['recommended_epsg']}")
    
    # Join all parts with comma-separated format
    optimized = ", ".join(parts)
    return optimized


def _generate_web_instructions(sources: List[Dict[str, Any]], location: Optional[str]) -> str:
    """Generate map2arcpy web instruction snippet."""
    if not sources:
        return ""
    
    source_names = ", ".join(s["osm"] for s in sources)
    location_str = f" in {location}" if location else ""
    return f"{source_names} from osm{location_str}"


def get_full_recommendations(description: str, web_enabled: bool = True) -> Dict[str, Any]:
    """
    Get comprehensive recommendations for map generation.
    
    Returns all recommendation categories in a single call.
    """
    return {
        "data_sources": recommend_data_sources(description, web_enabled),
        "operations": recommend_operations(description),
        "cartography": recommend_cartography(description),
        "crs": recommend_crs(description),
        "optimized_instructions": generate_optimized_instructions(description, web_enabled),
    }
