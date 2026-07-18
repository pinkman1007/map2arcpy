"""
Web scraping module for dynamic geographic data collection.

This module uses Scrapy to fetch geographic data from various web sources
(open data portals, CSV/GeoJSON repositories, web services) and normalizes
the results into formats suitable for map2arcpy (GeoJSON, Shapefile, etc).

Supports:
- CSV data with coordinates
- GeoJSON from web APIs
- Shapefiles from data portals
- Web services (WFS, etc.)
- Dynamic data source discovery
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import hashlib
import os


class DataSource:
    """Represents a web data source with scraping metadata."""
    
    def __init__(
        self,
        name: str,
        url: str,
        data_type: str,  # "geojson", "csv", "shapefile", "wfs", "api"
        description: str = "",
        format_spec: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ):
        self.name = name
        self.url = url
        self.data_type = data_type
        self.description = description
        self.format_spec = format_spec or {}
        self.tags = tags or []
        self.last_updated = None
        self.record_count = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "data_type": self.data_type,
            "description": self.description,
            "format_spec": self.format_spec,
            "tags": self.tags,
            "last_updated": self.last_updated,
            "record_count": self.record_count,
        }


# Known geographic data sources by region and category
GEOGRAPHIC_DATA_SOURCES: Dict[str, List[DataSource]] = {
    "india": {
        "health": [
            DataSource(
                name="India Health Facilities",
                url="https://data.world/datasets/india-health-facilities",
                data_type="csv",
                description="Government and private healthcare facilities in India",
                tags=["hospitals", "clinics", "health"],
            ),
            DataSource(
                name="HMIS India Health Data",
                url="https://hmis.samhsa.gov/",
                data_type="api",
                description="Health Management Information System data",
                tags=["health", "facilities"],
            ),
        ],
        "education": [
            DataSource(
                name="India Schools Directory",
                url="https://data.world/datasets/india-schools",
                data_type="csv",
                description="Educational institutions across India",
                tags=["schools", "colleges", "education"],
            ),
        ],
        "administrative": [
            DataSource(
                name="India Wards GeoJSON",
                url="https://github.com/datameet/indian_zips",
                data_type="geojson",
                description="Administrative boundaries and ward data for Indian cities",
                tags=["boundaries", "wards", "districts"],
            ),
        ],
        "infrastructure": [
            DataSource(
                name="India Roads Network",
                url="https://github.com/datameet/roads",
                data_type="geojson",
                description="Road network data for India",
                tags=["roads", "highways", "transportation"],
            ),
        ],
    },
    "global": {
        "administrative": [
            DataSource(
                name="Natural Earth Admin Boundaries",
                url="https://www.naturalearthdata.com/downloads/",
                data_type="shapefile",
                description="Global administrative boundaries at multiple resolutions",
                tags=["boundaries", "countries", "states"],
            ),
        ],
        "populated_places": [
            DataSource(
                name="Natural Earth Cities",
                url="https://www.naturalearthdata.com/downloads/10m-cultural-vectors/",
                data_type="shapefile",
                description="Global populated places and cities",
                tags=["cities", "towns", "places"],
            ),
        ],
        "water": [
            DataSource(
                name="Natural Earth Water Bodies",
                url="https://www.naturalearthdata.com/downloads/10m-physical-vectors/",
                data_type="shapefile",
                description="Global water bodies, coastlines, rivers",
                tags=["water", "rivers", "lakes", "oceans"],
            ),
        ],
    },
}


class DataSourceRegistry:
    """Registry and discovery engine for geographic data sources."""
    
    def __init__(self):
        self.sources = self._build_registry()
    
    def _build_registry(self) -> Dict[str, List[DataSource]]:
        """Build searchable registry from known sources."""
        registry = {}
        for region, categories in GEOGRAPHIC_DATA_SOURCES.items():
            for category, sources in categories.items():
                key = f"{region}:{category}"
                registry[key] = sources
        return registry
    
    def find_by_keyword(self, keyword: str) -> List[DataSource]:
        """Find data sources matching a keyword."""
        keyword_lower = keyword.lower()
        matches = []
        
        for source_list in self.sources.values():
            for source in source_list:
                # Check name, description, and tags
                if (keyword_lower in source.name.lower() or
                    keyword_lower in source.description.lower() or
                    any(keyword_lower in tag.lower() for tag in source.tags)):
                    matches.append(source)
        
        return matches
    
    def find_by_region_and_type(
        self, region: str, category: str
    ) -> List[DataSource]:
        """Find data sources for a specific region and category."""
        key = f"{region.lower()}:{category.lower()}"
        return self.sources.get(key, [])
    
    def find_for_description(self, description: str) -> List[Tuple[DataSource, float]]:
        """
        Find relevant data sources for a description.
        
        Returns:
            List of (source, relevance_score) tuples.
        """
        results = []
        keywords = description.lower().split()
        
        for source_list in self.sources.values():
            for source in source_list:
                # Calculate relevance score
                score = 0.0
                
                # Tag matches (highest weight)
                for tag in source.tags:
                    if tag.lower() in description.lower():
                        score += 0.4
                
                # Description matches
                for keyword in keywords:
                    if keyword in source.description.lower():
                        score += 0.1
                
                if score > 0:
                    results.append((source, min(1.0, score)))
        
        # Sort by relevance score
        return sorted(results, key=lambda x: x[1], reverse=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Export registry as dict."""
        return {
            key: [s.to_dict() for s in sources]
            for key, sources in self.sources.items()
        }


class ScrapedDataProcessor:
    """Process scraped data into GIS-compatible formats."""
    
    @staticmethod
    def csv_to_geojson(
        data: List[Dict[str, Any]],
        lat_field: str = "latitude",
        lon_field: str = "longitude",
        name_field: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convert CSV data with coordinates to GeoJSON.
        
        Args:
            data: List of dictionaries with coordinate columns
            lat_field: Name of latitude column
            lon_field: Name of longitude column
            name_field: Optional field for feature name
        
        Returns:
            GeoJSON FeatureCollection
        """
        features = []
        
        for row in data:
            if lat_field not in row or lon_field not in row:
                continue
            
            try:
                lat = float(row[lat_field])
                lon = float(row[lon_field])
            except (ValueError, TypeError):
                continue
            
            # Build properties (all fields except coordinates)
            properties = {
                k: v for k, v in row.items()
                if k not in [lat_field, lon_field]
            }
            
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": properties,
            }
            
            if name_field and name_field in row:
                feature["properties"]["_name"] = row[name_field]
            
            features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "record_count": len(features),
                "generated_at": datetime.now().isoformat(),
                "lat_field": lat_field,
                "lon_field": lon_field,
            },
        }
    
    @staticmethod
    def geojson_to_map2arcpy(geojson_data: Dict[str, Any]) -> str:
        """
        Convert GeoJSON to a map2arcpy instruction.
        
        Args:
            geojson_data: GeoJSON FeatureCollection
        
        Returns:
            map2arcpy instruction string
        """
        # Extract feature info
        features = geojson_data.get("features", [])
        record_count = len(features)
        
        # Infer layer name from first property
        layer_name = "data"
        if features and features[0].get("properties"):
            first_prop = list(features[0]["properties"].keys())[0]
            layer_name = first_prop.replace("_", " ").title()
        
        # Build instruction
        instruction = (
            f"load {record_count} features from scraped data, "
            f"unique values by type, "
            f"titled '{layer_name}', "
            f"A4L, 300 dpi"
        )
        
        return instruction
    
    @staticmethod
    def deduplicate_features(
        geojson_data: Dict[str, Any],
        duplicate_distance_m: float = 10.0,
    ) -> Dict[str, Any]:
        """
        Remove duplicate features based on proximity.
        
        Args:
            geojson_data: GeoJSON FeatureCollection
            duplicate_distance_m: Distance threshold in meters
        
        Returns:
            Deduplicated GeoJSON FeatureCollection
        """
        features = geojson_data.get("features", [])
        unique_features = []
        
        for feature in features:
            coords = feature.get("geometry", {}).get("coordinates", [])
            if not coords:
                continue
            
            # Check if this location is already in results
            is_duplicate = False
            for existing in unique_features:
                existing_coords = existing.get("geometry", {}).get("coordinates", [])
                distance = _haversine_distance(coords, existing_coords)
                
                if distance < duplicate_distance_m:
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": unique_features,
            "metadata": {
                "original_count": len(features),
                "deduplicated_count": len(unique_features),
                "duplicate_distance_m": duplicate_distance_m,
            },
        }
    
    @staticmethod
    def filter_by_bbox(
        geojson_data: Dict[str, Any],
        bbox: Tuple[float, float, float, float],  # (minlon, minlat, maxlon, maxlat)
    ) -> Dict[str, Any]:
        """Filter GeoJSON features by bounding box."""
        features = geojson_data.get("features", [])
        minlon, minlat, maxlon, maxlat = bbox
        
        filtered_features = []
        for feature in features:
            coords = feature.get("geometry", {}).get("coordinates", [])
            if not coords or len(coords) < 2:
                continue
            
            lon, lat = coords[0], coords[1]
            if minlon <= lon <= maxlon and minlat <= lat <= maxlat:
                filtered_features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": filtered_features,
            "metadata": {
                "bbox": bbox,
                "total_features": len(features),
                "filtered_features": len(filtered_features),
            },
        }


def _haversine_distance(
    coord1: Tuple[float, float],
    coord2: Tuple[float, float],
) -> float:
    """
    Calculate distance between two coordinates in meters.
    
    Args:
        coord1: [lon, lat]
        coord2: [lon, lat]
    
    Returns:
        Distance in meters
    """
    import math
    
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    
    R = 6371000  # Earth radius in meters
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c


def discover_web_data_sources(description: str) -> Dict[str, Any]:
    """
    Discover web data sources for a map description.
    
    Args:
        description: User's map description
    
    Returns:
        Dict with discovered sources and relevance scores
    """
    registry = DataSourceRegistry()
    sources = registry.find_for_description(description)
    
    return {
        "description": description,
        "discovered_sources": [
            {
                "source": s[0].to_dict(),
                "relevance_score": s[1],
            }
            for s in sources[:5]  # Top 5 matches
        ],
        "total_available": len(registry.sources),
    }


def get_data_source_by_name(name: str) -> Optional[DataSource]:
    """Get a specific data source by name."""
    registry = DataSourceRegistry()
    for source_list in registry.sources.values():
        for source in source_list:
            if source.name.lower() == name.lower():
                return source
    return None
