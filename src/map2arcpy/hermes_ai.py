"""
Hermes AI integration for map2arcpy dashboard.

This module provides AI-powered natural language enhancement and map improvement
suggestions using the Hermes Agent's AIAgent class.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict, List, Optional

# Global agent cache - we reuse one agent per server process
_agent_instance: Optional[Any] = None
_agent_lock = threading.Lock()


def get_hermes_agent() -> Any:
    """Get or create a shared AIAgent instance for the dashboard."""
    global _agent_instance
    if _agent_instance is not None:
        return _agent_instance

    with _agent_lock:
        if _agent_instance is not None:
            return _agent_instance

        # Import here to avoid circular imports and only load when needed
        try:
            # Add Hermes agent to path if not already there
            hermes_root = os.path.expanduser("~/.local/hermes/hermes-agent")
            if os.path.exists(hermes_root):
                import sys
                if hermes_root not in sys.path:
                    sys.path.insert(0, hermes_root)

            from run_agent import AIAgent

            # Determine provider from environment
            # Priority: explicit HERMES_PROVIDER > OPENROUTER_API_KEY/HERMES_API_KEY > NVIDIA_API_KEY
            # We explicitly do NOT fall back to NVIDIA_API_KEY if HERMES_PROVIDER is not set to "nvidia"
            # This prevents the global Hermes config from overriding the map2arcpy dashboard's choice.
            provider = os.getenv("HERMES_PROVIDER", "").lower()
            
            if provider == "nvidia":
                base_url = os.getenv("HERMES_BASE_URL", "https://integrate.api.nvidia.com/v1")
                api_key = os.getenv("NVIDIA_API_KEY")
                model = os.getenv("HERMES_MODEL", "nvidia/nemotron-3-ultra")
            else:
                # Default to OpenRouter
                base_url = os.getenv("HERMES_BASE_URL", "https://openrouter.ai/api/v1")
                api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("HERMES_API_KEY")
                model = os.getenv("HERMES_MODEL", "anthropic/claude-sonnet-4")
                provider = "openrouter"

            if not api_key:
                raise RuntimeError(
                    f"No API key found for {provider}. "
                    f"Set NVIDIA_API_KEY (for NVIDIA) or OPENROUTER_API_KEY/HERMES_API_KEY (for OpenRouter)."
                )

            _agent_instance = AIAgent(
                base_url=base_url,
                api_key=api_key,
                provider=provider,
                model=model,
                max_iterations=3,  # Low iteration limit for quick responses
                enabled_toolsets=None,  # No tools needed for text generation
                verbose_logging=False,
                quiet_mode=True,
            )
            return _agent_instance

        except ImportError as e:
            raise RuntimeError(f"Hermes Agent not available: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Hermes Agent: {e}")


def enhance_description(description: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enhance a natural language map description with GIS best practices using Hermes AI.

    Args:
        description: User's natural language map description
        context: Context dict with web_enabled, target, etc.

    Returns:
        Dict with enhanced_description, suggestions, best_practices_applied, detected_map_types
    """
    agent = get_hermes_agent()

    web_enabled = context.get("web_enabled", False)
    target = context.get("target", "arcpy")

    prompt = f"""You are an expert GIS cartographer. Enhance the following natural language map description with specific GIS best practices, ArcPy implementation details, and cartographic conventions.

User description: "{description}"

Context:
- Web enrichment (OSM/AGOL): {'enabled' if web_enabled else 'disabled'}
- Target: {target} (ArcGIS Pro arcpy or geopandas)

Please provide a JSON response with exactly these fields:
{{
  "enhanced_description": "Enhanced natural language description with specific GIS details added (comma-separated additions)",
  "suggestions": ["Specific actionable suggestions for the map"],
  "best_practices_applied": ["GIS best practices that were applied to the enhancement"],
  "detected_map_types": ["Map types detected from the description (e.g., choropleth, heatmap, network, terrain)"],
  "web_enrichment_available": {str(web_enabled).lower()}
}}

Focus on:
1. Specific classification methods (quantile, natural breaks, equal interval, standard deviation)
2. Color ramp recommendations (sequential/diverging/qualitative, colorblind-safe)
3. Layout standards (page size, DPI, legend, north arrow, scale bar, title)
4. CRS/projection guidance (UTM zones for local analysis)
5. Web enrichment opportunities (OSM tags, AGOL layers)
6. Performance tips for large datasets

Keep enhanced_description concise - add only the most impactful GIS specifics. Each suggestion should be actionable. Limit to 5 suggestions max."""

    try:
        result = agent.run_conversation(
            user_message=prompt,
        )

        # Check if the agent call failed
        if result.get("failed", False):
            raise RuntimeError(f"Agent failed: {result.get('error', 'Unknown error')}")

        response_text = result.get("final_response", "")
        # Try to parse JSON from response
        return _parse_ai_response(response_text, web_enabled)

    except Exception as e:
        # Fallback to rule-based enhancement
        result = _fallback_enhance(description, web_enabled)
        result["fallback"] = True
        result["fallback_reason"] = str(e)
        return result


def suggest_improvements(spec: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Analyze a MapSpec and suggest improvements using Hermes AI.

    Args:
        spec: MapSpec dictionary from map2arcpy
        context: Context dict with web_enabled, etc.

    Returns:
        Dict with suggestions, warnings, best_practices, spec_summary
    """
    agent = get_hermes_agent()

    web_enabled = context.get("web_enabled", False)

    # Build a summary of the spec for the LLM
    spec_summary = _summarize_spec(spec)

    prompt = f"""You are an expert GIS cartographer and ArcPy developer. Analyze this MapSpec and provide specific, actionable improvements.

MapSpec Summary:
{json.dumps(spec_summary, indent=2)}

Full MapSpec:
{json.dumps(spec, indent=2)}

Context:
- Web enrichment: {'enabled' if web_enabled else 'disabled'}

Provide a JSON response with exactly these fields:
{{
  "suggestions": [
    {{
      "type": "symbology|basemap|labeling|crs|layout|operation|data|performance",
      "priority": "high|medium|low",
      "description": "Clear description of the improvement",
      "code_hint": "Specific map2arcpy syntax or arcpy code hint (e.g., 'graduated by pop_density, classify=quantile, classes=5')",
      "impact": "What this improves (readability, accuracy, performance, etc.)"
    }}
  ],
  "warnings": [
    {{
      "type": "crs|buffer|zonal_stats|missing_source|topology|projection",
      "severity": "error|warning|info",
      "description": "Description of the issue",
      "fix": "Specific fix or workaround"
    }}
  ],
  "best_practices": [
    "General GIS best practice recommendations applicable to this map"
  ],
  "spec_summary": {json.dumps(spec_summary)}
}}

Analyze for:
1. Symbology: missing classification, wrong ramp type, no field specified
2. Basemap: missing context layer
3. Labeling: unlabeled vector layers that should be labeled
4. CRS: operations in WGS84 (degrees), missing projection for local analysis
5. Layout: missing title, legend, north arrow, scale bar
6. Operations: buffer in degrees, zonal stats without zone_field, topology issues
7. Data sources: missing paths, shapefiles without .prj
8. Performance: large rasters without pyramids, too many classes

Limit to 8 suggestions max, 5 warnings max. Prioritize high-impact fixes."""

    try:
        result = agent.run_conversation(
            user_message=prompt,
        )

        # Check if the agent call failed
        if result.get("failed", False):
            raise RuntimeError(f"Agent failed: {result.get('error', 'Unknown error')}")

        response_text = result.get("final_response", "")
        return _parse_suggestions_response(response_text, spec_summary)

    except Exception as e:
        # Fallback to rule-based analysis
        result = _fallback_analyze(spec, web_enabled)
        result["fallback"] = True
        result["fallback_reason"] = str(e)
        return result


def _summarize_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Create a concise summary of the MapSpec for the LLM."""
    layers = spec.get("layers", [])
    operations = spec.get("operations", [])
    layout = spec.get("layout", {})
    crs = spec.get("crs_epsg", 4326)

    data_layers = [l for l in layers if l.get("kind") in ("vector", "raster") and l.get("source")]
    basemaps = [l for l in layers if l.get("kind") == "basemap"]

    return {
        "layer_count": len(data_layers),
        "layers": [
            {
                "name": l.get("name"),
                "kind": l.get("kind"),
                "renderer_type": l.get("renderer", {}).get("type"),
                "renderer_field": l.get("renderer", {}).get("field"),
                "class_method": l.get("renderer", {}).get("class_method"),
                "class_count": l.get("renderer", {}).get("class_count"),
                "label_field": l.get("label_field"),
                "source": l.get("source", "")[:80] if l.get("source") else None,
            }
            for l in data_layers
        ],
        "has_basemap": len(basemaps) > 0,
        "operation_count": len(operations),
        "operations": [
            {
                "tool": op.get("tool"),
                "output": op.get("output"),
                "params": op.get("params", {}),
            }
            for op in operations
        ],
        "crs_epsg": crs,
        "layout": {
            "title": layout.get("title"),
            "page": layout.get("page"),
            "dpi": layout.get("dpi"),
            "legend": layout.get("legend", True),
            "north_arrow": layout.get("north_arrow"),
            "scale_bar": layout.get("scale_bar"),
        },
    }


def _parse_ai_response(response_text: str, web_enabled: bool) -> Dict[str, Any]:
    """Parse the AI response, falling back to rule-based if JSON parsing fails."""
    # Try to extract JSON from the response
    try:
        # Find JSON block
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)
            # Ensure all required fields exist
            result.setdefault("enhanced_description", "")
            result.setdefault("suggestions", [])
            result.setdefault("best_practices_applied", [])
            result.setdefault("detected_map_types", [])
            result.setdefault("web_enrichment_available", web_enabled)
            return result
    except Exception:
        pass

    # Fallback: extract useful info from text response
    return _fallback_enhance("", web_enabled)


def _parse_suggestions_response(response_text: str, spec_summary: Dict[str, Any]) -> Dict[str, Any]:
    """Parse the AI suggestions response."""
    try:
        start = response_text.find("{")
        end = response_text.rfind("}") + 1
        if start >= 0 and end > start:
            json_str = response_text[start:end]
            result = json.loads(json_str)
            result.setdefault("suggestions", [])
            result.setdefault("warnings", [])
            result.setdefault("best_practices", [])
            result.setdefault("spec_summary", spec_summary)
            return result
    except Exception:
        pass

    return _fallback_analyze({"layers": [], "operations": []}, False)


def _fallback_enhance(description: str, web_enabled: bool) -> Dict[str, Any]:
    """Rule-based fallback enhancement (original logic)."""
    import re

    detected_types = []
    enhancements = []
    best_practices = set()
    suggestions = []

    patterns = {
        "healthcare": {
            "triggers": ["hospital", "clinic", "healthcare", "medical", "health facility"],
            "enhancements": ["source OSM amenity=hospital", "graduated by bed capacity or specialty", "add 5km service area buffers", "clip to administrative boundary"],
            "best_practices": ["web_enrichment", "graduated_symbology", "service_areas"]
        },
        "education": {
            "triggers": ["school", "college", "university", "education", "campus"],
            "enhancements": ["source OSM amenity=school|college|university", "unique values by type (primary/secondary/tertiary)", "add walk-time catchment areas", "label with institution name"],
            "best_practices": ["web_enrichment", "unique_values", "catchment_analysis"]
        },
        "transportation": {
            "triggers": ["road", "highway", "street", "transport", "transit", "bus", "rail"],
            "enhancements": ["use OSM highway=* tags for road hierarchy", "graduated line width by road class", "add transit stops as points", "include network analysis if routing needed"],
            "best_practices": ["web_enrichment", "hierarchical_symbology", "network_analysis"]
        },
        "population": {
            "triggers": ["population", "density", "demographic", "census", "people"],
            "enhancements": ["choropleth with quantile or natural breaks classification", "use sequential color ramp (blues, greens, purples)", "normalize by area for density maps", "add reference basemap for context"],
            "best_practices": ["graduated_symbology", "normalization", "basemap"]
        },
        "environmental": {
            "triggers": ["flood", "risk", "hazard", "environment", "pollution", "air quality", "water quality"],
            "enhancements": ["use diverging color ramp for risk (red-blue, brown-teal)", "classify with standard deviation or geometric intervals", "add contour lines for continuous surfaces", "include uncertainty visualization if available"],
            "best_practices": ["diverging_symbology", "uncertainty_viz", "contours"]
        },
        "elevation": {
            "triggers": ["elevation", "dem", "terrain", "slope", "hillshade", "topography"],
            "enhancements": ["hypsometric tinting (green-brown-white ramp)", "add hillshade for 3D effect", "contour lines at appropriate interval", "slope/aspect analysis if needed"],
            "best_practices": ["hypsometric_ramp", "hillshade", "contours"]
        },
        "rainfall": {
            "triggers": ["rain", "rainfall", "precipitation", "monsoon", "weather", "climate"],
            "enhancements": ["sequential blue ramp (light to dark)", "period average (annual/monthly/decadal)", "isohyet contours for interpolation", "compare to normals if time series"],
            "best_practices": ["sequential_ramp", "temporal_aggregation", "contours"]
        },
        "landuse": {
            "triggers": ["land use", "land cover", "zoning", "urban", "built-up", "agriculture"],
            "enhancements": ["unique values by land cover class", "standard color scheme (NLCD/CORINE palette)", "add transparency for overlay on imagery", "calculate area statistics by class"],
            "best_practices": ["unique_values", "standard_palette", "area_stats"]
        }
    }

    low = description.lower()
    for map_type, config in patterns.items():
        for trigger in config["triggers"]:
            if re.search(rf"\b{re.escape(trigger)}\b", low):
                detected_types.append(map_type)
                enhancements.extend(config["enhancements"])
                best_practices.update(config["best_practices"])
                break

    enhanced_parts = [description.strip()]

    if web_enabled:
        if any(t in detected_types for t in ["healthcare", "education", "transportation"]):
            enhanced_parts.append("from osm")
            suggestions.append("Enable web enrichment to download OSM features")

    if "population" in detected_types or "density" in low:
        enhanced_parts.append("graduated colors using quantile classification")
        suggestions.append("Use quantile classification for population density")

    if "environmental" in detected_types or "risk" in low:
        enhanced_parts.append("diverging color ramp (red-blue)")
        suggestions.append("Use diverging ramp for risk/hazard maps")

    if "elevation" in detected_types or "terrain" in detected_types:
        enhanced_parts.append("hypsometric tinting with hillshade")
        suggestions.append("Add hillshade for terrain visualization")

    enhanced_parts.append("titled with descriptive name")
    enhanced_parts.append("A3 landscape, 300 dpi")

    if web_enabled:
        suggestions.extend([
            "Geocode place names for automatic extent/CRS",
            "Search ArcGIS Online for authoritative layers"
        ])

    general_practices = [
        "Project data to appropriate UTM zone for accurate measurements",
        "Use graduated colors for quantitative data, unique values for categorical",
        "Choose color ramps appropriate for data type (sequential/diverging/qualitative)",
        "Set proper classification method (natural breaks, quantile, equal interval)",
        "Include legend, north arrow, scale bar, and title",
        "Export at 300 DPI for print, 150 DPI for screen",
        "Document data sources and projection in map credits"
    ]
    best_practices.update(general_practices[:3])

    enhanced = ", ".join(enhanced_parts)

    return {
        "enhanced_description": enhanced,
        "suggestions": suggestions,
        "best_practices_applied": list(best_practices),
        "detected_map_types": detected_types,
        "web_enrichment_available": web_enabled
    }


def _fallback_analyze(spec: Dict[str, Any], web_enabled: bool) -> Dict[str, Any]:
    """Rule-based fallback analysis (original logic from server.py)."""
    suggestions = []
    warnings = []
    best_practices = []

    def has_choropleth():
        for layer in spec.get("layers", []):
            renderer = layer.get("renderer", {})
            if renderer.get("type") in ("graduated", "choropleth"):
                return True
        return False

    def has_unique_values():
        for layer in spec.get("layers", []):
            renderer = layer.get("renderer", {})
            if renderer.get("type") == "unique":
                return True
        return False

    def has_classification():
        for layer in spec.get("layers", []):
            renderer = layer.get("renderer", {})
            if renderer.get("type") == "graduated":
                if renderer.get("class_method") and renderer.get("class_count", 0) > 0:
                    return True
        return False

    def has_basemap():
        for layer in spec.get("layers", []):
            if layer.get("kind") == "basemap":
                return True
        return False

    def has_labels():
        for layer in spec.get("layers", []):
            if layer.get("label_field"):
                return True
        return False

    def get_crs():
        return spec.get("crs_epsg", 4326)

    def get_data_layers():
        return [l for l in spec.get("layers", [])
                if l.get("kind") in ("vector", "raster") and l.get("source")]

    def has_operations():
        return len(spec.get("operations", [])) > 0

    # Symbology analysis
    if has_choropleth():
        if not has_classification():
            suggestions.append({
                "type": "symbology",
                "priority": "high",
                "description": "Graduated renderer missing classification method and class count",
                "code_hint": "classify=natural_breaks|quantile|equal_interval, classes=5",
                "impact": "Without classification, ArcGIS defaults to 5 natural breaks which may not suit your data"
            })

        for layer in spec.get("layers", []):
            renderer = layer.get("renderer", {})
            if renderer.get("type") == "graduated" and not renderer.get("field"):
                suggestions.append({
                    "type": "symbology",
                    "priority": "high",
                    "description": f"Layer '{layer['name']}' has graduated renderer but no field specified",
                    "code_hint": "graduated by <FIELD_NAME>",
                    "impact": "Will default to 'VALUE' field - replace with actual attribute"
                })

    # Basemap check
    if not has_basemap() and get_data_layers():
        suggestions.append({
            "type": "basemap",
            "priority": "medium",
            "description": "No basemap layer for geographic context",
            "code_hint": "basemap=Imagery|Topographic|OpenStreetMap|'Dark Gray Canvas'",
            "impact": "Map will lack geographic reference - add basemap for context"
        })

    # Label check
    if not has_labels() and get_data_layers():
        vector_layers = [l for l in get_data_layers() if l.get("kind") == "vector"]
        if vector_layers:
            suggestions.append({
                "type": "labeling",
                "priority": "low",
                "description": "No labels on vector layers - consider labeling key features",
                "code_hint": "label by <FIELD_NAME>",
                "impact": "Unlabeled maps are harder to interpret"
            })

    # CRS analysis
    crs = get_crs()
    if crs == 4326 and has_operations():
        warnings.append({
            "type": "crs",
            "severity": "warning",
            "description": "Operations (buffer, clip, etc.) in WGS84 (EPSG:4326) use degrees - results will be inaccurate",
            "fix": "Project data to UTM zone or use map2arcpy probe to auto-detect"
        })
        best_practices.append("Project data to UTM zone for accurate buffer/area calculations")

    # Operations analysis
    ops = spec.get("operations", [])
    for op in ops:
        tool = op.get("tool", "")
        if tool == "buffer" and crs == 4326:
            warnings.append({
                "type": "buffer_crs",
                "severity": "error",
                "description": f"Buffer operation '{op.get('output', '?')}' in WGS84 - distance in degrees!",
                "fix": "Set CRS to UTM zone before buffering, or use geodesic buffering"
            })
        if tool == "zonal_stats":
            params = op.get("params", {})
            if params.get("zone_field") == "TODO_ZONE_FIELD":
                warnings.append({
                    "type": "zonal_stats",
                    "severity": "error",
                    "description": "Zonal statistics missing zone_field - must specify the zone attribute",
                    "fix": "Add zone_field parameter with actual field name from zone layer"
                })

    # Data source checks
    for layer in spec.get("layers", []):
        source = layer.get("source", "")
        if source == "TODO_SET_PATH.shp" or not source:
            if layer.get("kind") != "basemap":
                warnings.append({
                    "type": "missing_source",
                    "severity": "error",
                    "description": f"Layer '{layer['name']}' has no data source",
                    "fix": "Provide path to data file or use web enrichment for OSM data"
                })
        elif source.endswith(".shp") and crs != 4326:
            best_practices.append("Shapefiles don't store CRS - ensure .prj file exists or specify CRS explicitly")

    # Layout checks
    layout = spec.get("layout", {})
    if not layout.get("title") or layout.get("title") == "Untitled Map":
        suggestions.append({
            "type": "layout",
            "priority": "medium",
            "description": "Map has default title - add descriptive title",
            "code_hint": "titled 'Your Descriptive Map Title'",
            "impact": "Title is essential for map communication"
        })

    if not layout.get("legend", True):
        suggestions.append({
            "type": "layout",
            "priority": "low",
            "description": "Legend disabled - consider enabling for interpretability",
            "code_hint": "legend=on",
            "impact": "Maps without legends are hard to interpret"
        })

    # General best practices
    best_practices.extend([
        "Use quantile classification for population/density or natural breaks for skewed data distributions",
        "Choose colorblind-safe ramps (viridis, cividis, colorbrewer safe)",
        "Set appropriate transparency for overlay layers",
        "Validate geometry before analysis (Check Geometry tool)"
    ])

    return {
        "suggestions": suggestions,
        "warnings": warnings,
        "best_practices": list(set(best_practices)),
        "spec_summary": _summarize_spec(spec)
    }


# =========================================================================
# intelligent recommendation integration
# =========================================================================
def get_web_recommendations(description: str, web_enabled: bool = True) -> Dict[str, Any]:
    """
    Get intelligent web data recommendations using the recommendations engine.
    
    Returns data sources, operations, cartography, and CRS recommendations.
    """
    try:
        from . import recommendations
        return recommendations.get_full_recommendations(description, web_enabled)
    except Exception as e:
        # Fallback to rule-based recommendations
        return {
            "data_sources": {"sources": [], "location": None},
            "operations": {"operations": {}, "sequence": []},
            "cartography": {"detected_types": [], "primary_type": "generic"},
            "crs": {"recommended_epsg": 4326, "name": "WGS 84"},
            "optimized_instructions": description,
            "fallback": True,
            "fallback_reason": str(e)
        }


def optimize_instructions(description: str, web_enabled: bool = True) -> str:
    """
    Generate optimized map2arcpy instructions from user description.
    
    Intelligently combines data sources, operations, cartography, and layout
    into a complete, executable instruction string.
    """
    try:
        from . import recommendations
        return recommendations.generate_optimized_instructions(description, web_enabled)
    except Exception:
        # Fallback: return original description with basic optimization
        return description.strip()


def detect_map_type_detailed(description: str) -> Dict[str, Any]:
    """
    Detect and analyze map types with detailed recommendations.
    """
    try:
        from . import recommendations
        
        map_types = recommendations.detect_map_types(description)
        cartography_recs = recommendations.recommend_cartography(description)
        operation_recs = recommendations.recommend_operations(description)
        
        return {
            "detected_types": map_types,
            "cartography": cartography_recs,
            "operations": operation_recs,
            "primary_type": map_types[0][0] if map_types else None,
        }
    except Exception:
        return {
            "detected_types": [],
            "cartography": {},
            "operations": {},
            "primary_type": None,
        }


def search_web_sources(description: str) -> Dict[str, Any]:
    """
    Search for optimal web data sources (OSM, AGOL) based on description.
    
    Returns recommendations for:
    - OSM features to download
    - AGOL layers to search
    - Location for geocoding
    - Data enrichment opportunities
    """
    try:
        from . import recommendations
        
        data_recs = recommendations.recommend_data_sources(description, web_enabled=True)
        
        return {
            "recommended_sources": data_recs["sources"],
            "location": data_recs["location"],
            "web_instructions": data_recs["instructions"],
            "enrichment_available": data_recs["web_enrichment_available"],
            "source_count": len(data_recs["sources"]),
        }
    except Exception as e:
        return {
            "recommended_sources": [],
            "location": None,
            "web_instructions": "",
            "enrichment_available": False,
            "source_count": 0,
            "fallback": True,
            "fallback_reason": str(e)
        }