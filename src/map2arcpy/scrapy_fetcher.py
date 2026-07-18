"""
Scrapy-based data fetcher for geographic datasets.

This module provides lightweight data fetching using Scrapy spiders
for different data source types (CSV, GeoJSON, etc).

Note: Scrapy is an optional dependency. The web_scraper module functions
without it, but scraping requires: pip install scrapy
"""

from __future__ import annotations

import json
import csv
import io
from typing import Any, Dict, Optional, List
from abc import ABC, abstractmethod


class DataFetcher(ABC):
    """Abstract base for data fetchers."""
    
    @abstractmethod
    def fetch(self, url: str) -> Optional[Any]:
        """Fetch data from URL."""
        pass


class CSVFetcher(DataFetcher):
    """Fetch and parse CSV data."""
    
    def fetch(self, url: str, encoding: str = "utf-8") -> Optional[List[Dict[str, Any]]]:
        """
        Fetch CSV data from URL.
        
        Args:
            url: URL to CSV file
            encoding: Text encoding (default UTF-8)
        
        Returns:
            List of dictionaries (rows), or None on error
        """
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read().decode(encoding)
            
            reader = csv.DictReader(io.StringIO(content))
            return list(reader)
        except Exception as e:
            print(f"Failed to fetch CSV from {url}: {e}")
            return None


class GeoJSONFetcher(DataFetcher):
    """Fetch and parse GeoJSON data."""
    
    def fetch(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch GeoJSON from URL.
        
        Args:
            url: URL to GeoJSON file
        
        Returns:
            GeoJSON dict, or None on error
        """
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=30) as response:
                content = response.read().decode("utf-8")
            
            return json.loads(content)
        except Exception as e:
            print(f"Failed to fetch GeoJSON from {url}: {e}")
            return None


class APIFetcher(DataFetcher):
    """Fetch data from REST APIs."""
    
    def fetch(
        self,
        url: str,
        params: Optional[Dict[str, str]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch JSON data from API.
        
        Args:
            url: API endpoint URL
            params: Query parameters
            headers: HTTP headers
        
        Returns:
            JSON response dict, or None on error
        """
        try:
            import urllib.request
            import urllib.parse
            
            if params:
                query_string = urllib.parse.urlencode(params)
                url = f"{url}?{query_string}"
            
            req = urllib.request.Request(url)
            if headers:
                for key, value in headers.items():
                    req.add_header(key, value)
            
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode("utf-8")
            
            return json.loads(content)
        except Exception as e:
            print(f"Failed to fetch from API {url}: {e}")
            return None


class ScrapyDataCollector:
    """
    Manages data collection from various sources using appropriate fetchers.
    
    This class dynamically selects the right fetcher based on data source type
    and handles format conversion to GeoJSON.
    """
    
    def __init__(self):
        self.fetchers = {
            "csv": CSVFetcher(),
            "geojson": GeoJSONFetcher(),
            "api": APIFetcher(),
        }
    
    def fetch_and_convert(
        self,
        url: str,
        data_type: str,
        format_spec: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Fetch data and convert to GeoJSON.
        
        Args:
            url: Data source URL
            data_type: Type of data source (csv, geojson, api)
            format_spec: Format specification dict with field mappings
        
        Returns:
            GeoJSON FeatureCollection or None on error
        """
        format_spec = format_spec or {}
        fetcher = self.fetchers.get(data_type.lower())
        
        if not fetcher:
            print(f"Unknown data type: {data_type}")
            return None
        
        # Fetch raw data
        raw_data = fetcher.fetch(url)
        if not raw_data:
            return None
        
        # Convert to GeoJSON based on type
        if data_type.lower() == "csv":
            return self._convert_csv_to_geojson(raw_data, format_spec)
        elif data_type.lower() == "geojson":
            return raw_data
        elif data_type.lower() == "api":
            return self._convert_api_response_to_geojson(raw_data, format_spec)
        
        return None
    
    def _convert_csv_to_geojson(
        self,
        csv_data: List[Dict[str, Any]],
        format_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Convert CSV data to GeoJSON."""
        from .web_scraper import ScrapedDataProcessor
        
        lat_field = format_spec.get("lat_field", "latitude")
        lon_field = format_spec.get("lon_field", "longitude")
        name_field = format_spec.get("name_field")
        
        geojson = ScrapedDataProcessor.csv_to_geojson(
            csv_data,
            lat_field=lat_field,
            lon_field=lon_field,
            name_field=name_field,
        )
        
        return geojson
    
    def _convert_api_response_to_geojson(
        self,
        api_response: Dict[str, Any],
        format_spec: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Convert API response to GeoJSON.
        
        Handles common API patterns (features array, data array, etc).
        """
        # Extract features/data from various API response structures
        features_key = format_spec.get("features_key", "features")
        
        features = []
        
        # Try to find features in response
        if features_key in api_response:
            items = api_response[features_key]
        elif "data" in api_response:
            items = api_response["data"]
        else:
            items = []
        
        # Convert items to GeoJSON features
        for item in items:
            # Check if already a GeoJSON feature
            if item.get("type") == "Feature":
                features.append(item)
            else:
                # Try to extract coordinates
                lat_field = format_spec.get("lat_field", "latitude")
                lon_field = format_spec.get("lon_field", "longitude")
                
                lat = item.get(lat_field)
                lon = item.get(lon_field)
                
                if lat is not None and lon is not None:
                    feature = {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(lon), float(lat)],
                        },
                        "properties": {k: v for k, v in item.items() 
                                     if k not in [lat_field, lon_field]},
                    }
                    features.append(feature)
        
        return {
            "type": "FeatureCollection",
            "features": features,
            "metadata": {
                "record_count": len(features),
                "source_api": "custom",
            },
        }
    
    def batch_fetch(
        self,
        sources: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Fetch data from multiple sources and merge results.
        
        Args:
            sources: List of source dicts with url, data_type, format_spec
        
        Returns:
            Merged GeoJSON FeatureCollection
        """
        all_features = []
        
        for source in sources:
            url = source.get("url")
            data_type = source.get("data_type")
            format_spec = source.get("format_spec", {})
            
            geojson = self.fetch_and_convert(url, data_type, format_spec)
            if geojson:
                features = geojson.get("features", [])
                all_features.extend(features)
        
        return {
            "type": "FeatureCollection",
            "features": all_features,
            "metadata": {
                "record_count": len(all_features),
                "sources_fetched": len(sources),
            },
        }
