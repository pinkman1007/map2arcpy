"""
Dynamic data source discovery from GitHub, OpenData portals, and web APIs.

Searches for geographic datasets in real-time instead of using hardcoded registry.
Supports GitHub repositories, Kaggle datasets, Open Data portals, and CKAN instances.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote
import warnings

try:
    import requests
except ImportError:
    requests = None


class DynamicSourceDiscovery:
    """Discover geographic data sources dynamically from the web."""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.cache: Dict[str, List[Dict[str, Any]]] = {}
    
    def search_github_geospatial_data(self, query: str, region: str = "") -> List[Dict[str, Any]]:
        """
        Search GitHub for geospatial datasets using GitHub API.
        
        Args:
            query: Search term (e.g., "hospitals", "roads", "boundaries")
            region: Geographic region (e.g., "India", "Delhi")
        
        Returns:
            List of discovered GitHub repositories with geospatial data
        """
        if not requests:
            return []
        
        cache_key = f"github:{query}:{region}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        # Build search query with geospatial keywords
        search_terms = [
            query,
            "geojson OR shapefile OR gpkg",
            "region:" + region if region else "",
            "language:json",
        ]
        github_query = " ".join(filter(None, search_terms))
        
        try:
            # Search GitHub for relevant repos
            url = "https://api.github.com/search/repositories"
            params = {
                "q": github_query,
                "sort": "stars",
                "per_page": 10,
            }
            
            resp = requests.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            results = []
            
            for repo in data.get("items", [])[:5]:
                # Extract GeoJSON/Shapefile URLs from repo
                geo_urls = self._extract_geo_urls_from_repo(
                    repo["owner"]["login"],
                    repo["name"],
                    repo.get("default_branch", "main")
                )
                
                for geo_url in geo_urls:
                    results.append({
                        "name": repo["name"],
                        "source": "github",
                        "url": geo_url,
                        "repo_url": repo["html_url"],
                        "description": repo.get("description", ""),
                        "stars": repo.get("stargazers_count", 0),
                        "type": self._infer_data_type(geo_url),
                        "region": region,
                        "tags": [query, "geospatial"],
                    })
            
            self.cache[cache_key] = results
            return results
        except Exception as e:
            warnings.warn(f"GitHub search failed: {e}")
            return []
    
    def _extract_geo_urls_from_repo(
        self,
        owner: str,
        repo: str,
        branch: str = "main"
    ) -> List[str]:
        """Extract URLs to GeoJSON/Shapefile from GitHub repo."""
        if not requests:
            return []
        
        urls = []
        
        try:
            # Get repo contents to find GeoJSON/Shapefile files
            api_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
            resp = requests.get(api_url, timeout=self.timeout)
            
            if resp.status_code != 200:
                return []
            
            data = resp.json()
            
            for item in data.get("tree", []):
                path = item.get("path", "")
                
                # Match common geospatial file extensions
                if re.search(r"\.(geojson|json|shp|gpkg|kml)$", path, re.I):
                    if item["type"] == "blob":
                        # Build raw GitHub URL
                        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
                        urls.append(raw_url)
        except Exception:
            pass
        
        return urls
    
    def search_open_data_portals(self, query: str, region: str = "") -> List[Dict[str, Any]]:
        """
        Search Open Data portals (CKAN instances) for datasets.
        
        Supports: data.world, OpenData portals, CKAN instances
        """
        if not requests:
            return []
        
        cache_key = f"opendata:{query}:{region}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        results = []
        
        # Search multiple CKAN instances
        ckan_instances = [
            ("data.world", "https://api.data.world/v1/search"),
            ("OpenData", "https://demo.ckan.org/api/3/action/package_search"),
        ]
        
        for portal_name, api_url in ckan_instances:
            try:
                # Build search query with location filter
                search_query = f"{query}"
                if region:
                    search_query += f" {region}"
                
                params = {
                    "q": search_query,
                    "rows": 5,
                    "fq": "res_format:(GeoJSON OR Shapefile OR CSV OR JSON)",
                }
                
                resp = requests.get(api_url, params=params, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                
                data = resp.json()
                
                # Extract packages/datasets
                packages = data.get("result", {}).get("results", data.get("packages", []))
                
                for pkg in packages[:3]:
                    pkg_name = pkg.get("name", pkg.get("title", ""))
                    pkg_url = pkg.get("url", "")
                    
                    # Extract resource URLs
                    for resource in pkg.get("resources", []):
                        res_url = resource.get("url", "")
                        if res_url:
                            results.append({
                                "name": pkg_name,
                                "source": portal_name.lower(),
                                "url": res_url,
                                "description": pkg.get("notes", ""),
                                "type": self._infer_data_type(res_url),
                                "region": region,
                                "tags": [query, "public"],
                            })
            except Exception:
                pass
        
        self.cache[cache_key] = results
        return results
    
    def search_kaggle_datasets(self, query: str, region: str = "") -> List[Dict[str, Any]]:
        """
        Search Kaggle for geospatial datasets.
        
        Note: Requires unofficial API or web scraping.
        """
        if not requests:
            return []
        
        results = []
        
        try:
            # Use Kaggle search URL (unofficial)
            search_url = "https://www.kaggle.com/api/i/datasets.DatasetSearchManager/search"
            
            params = {
                "search": query,
                "pageNo": 0,
                "pageSize": 5,
                "sortBy": "hottest",
            }
            
            resp = requests.get(search_url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return results
            
            data = resp.json()
            
            for dataset in data.get("datasets", [])[:3]:
                results.append({
                    "name": dataset.get("name", ""),
                    "source": "kaggle",
                    "url": f"https://www.kaggle.com/datasets/{dataset.get('ref', '')}",
                    "description": dataset.get("description", ""),
                    "type": "dataset",
                    "region": region,
                    "tags": [query, "kaggle"],
                    "downloads": dataset.get("downloadCount", 0),
                })
        except Exception:
            pass
        
        return results
    
    def search_osm_related_data(self, query: str, region: str = "") -> List[Dict[str, Any]]:
        """
        Search for OSM-related datasets and mirrors.
        """
        if not requests:
            return []
        
        results = []
        
        # Common OSM data sources
        osm_sources = [
            {
                "name": "Overpass API",
                "url": "https://overpass-api.de",
                "type": "api",
                "description": "Real-time OSM data queries",
                "tags": ["osm", "api", "real-time"],
            },
            {
                "name": "GeoFabrik",
                "url": "https://download.geofabrik.de/",
                "type": "download",
                "description": "OSM data extracts by region",
                "tags": ["osm", "download", "extracts"],
            },
            {
                "name": "HOT Export Tool",
                "url": "https://export.hotosm.org",
                "type": "api",
                "description": "Humanitarian OSM exports",
                "tags": ["osm", "humanitarian"],
            },
        ]
        
        # Filter by region/query
        for source in osm_sources:
            if query.lower() in source["description"].lower() or \
               query.lower() in " ".join(source["tags"]).lower():
                source["region"] = region
                results.append(source)
        
        return results
    
    def _infer_data_type(self, url: str) -> str:
        """Infer data type from URL."""
        url_lower = url.lower()
        
        if ".geojson" in url_lower:
            return "geojson"
        elif ".json" in url_lower:
            return "json"
        elif ".shp" in url_lower:
            return "shapefile"
        elif ".gpkg" in url_lower:
            return "geopackage"
        elif ".kml" in url_lower:
            return "kml"
        elif ".csv" in url_lower:
            return "csv"
        elif "wfs" in url_lower or "wms" in url_lower:
            return "web_service"
        else:
            return "unknown"
    
    def discover_sources_for_query(
        self,
        query: str,
        region: str = "",
        sources: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Discover data sources from multiple sources for a query.
        
        Args:
            query: Search term
            region: Geographic region (optional)
            sources: Which sources to search (default: all)
        
        Returns:
            Combined list of discovered sources, sorted by relevance
        """
        if sources is None:
            sources = ["github", "opendata", "kaggle", "osm"]
        
        all_results = []
        
        if "github" in sources:
            all_results.extend(self.search_github_geospatial_data(query, region))
        
        if "opendata" in sources:
            all_results.extend(self.search_open_data_portals(query, region))
        
        if "kaggle" in sources:
            all_results.extend(self.search_kaggle_datasets(query, region))
        
        if "osm" in sources:
            all_results.extend(self.search_osm_related_data(query, region))
        
        # Score and sort results
        scored = []
        for result in all_results:
            score = self._calculate_relevance_score(result, query, region)
            scored.append((score, result))
        
        scored.sort(reverse=True, key=lambda x: x[0])
        return [r for _, r in scored]
    
    def _calculate_relevance_score(
        self,
        result: Dict[str, Any],
        query: str,
        region: str
    ) -> float:
        """Calculate relevance score for a result."""
        score = 0.0
        
        # Exact match in name or description
        text = f"{result.get('name', '')} {result.get('description', '')}".lower()
        if query.lower() in text:
            score += 0.4
        
        # Region match
        if region and region.lower() in text:
            score += 0.3
        
        # Source popularity (GitHub stars, Kaggle downloads)
        if "stars" in result:
            score += min(0.2, result["stars"] / 1000)
        elif "downloads" in result:
            score += min(0.2, result["downloads"] / 10000)
        
        # Preferred data types
        preferred_types = ["geojson", "shapefile", "geopackage"]
        if result.get("type") in preferred_types:
            score += 0.1
        
        return score


# Convenience function
def discover_data_sources(
    query: str,
    region: str = "",
    sources: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Quick access to dynamic source discovery."""
    discovery = DynamicSourceDiscovery()
    return discovery.discover_sources_for_query(query, region, sources)
