"""
Tests for web scraping and geographic data collection.
"""

import pytest
from map2arcpy.web_scraper import (
    DataSource,
    DataSourceRegistry,
    ScrapedDataProcessor,
    discover_web_data_sources,
    get_data_source_by_name,
)
from map2arcpy.scrapy_fetcher import ScrapyDataCollector, CSVFetcher, GeoJSONFetcher


class TestDataSource:
    def test_create_data_source(self):
        """Create a data source."""
        source = DataSource(
            name="Test Source",
            url="https://example.com/data.csv",
            data_type="csv",
            description="Test data source",
            tags=["test", "data"],
        )
        
        assert source.name == "Test Source"
        assert source.data_type == "csv"
        assert "test" in source.tags
    
    def test_data_source_to_dict(self):
        """Convert data source to dict."""
        source = DataSource(
            name="Test",
            url="https://example.com/data.csv",
            data_type="csv",
        )
        
        d = source.to_dict()
        assert d["name"] == "Test"
        assert d["url"] == "https://example.com/data.csv"


class TestDataSourceRegistry:
    def test_registry_initialization(self):
        """Registry initializes with known sources."""
        registry = DataSourceRegistry()
        assert len(registry.sources) > 0
    
    def test_find_by_keyword_hospitals(self):
        """Find hospital data sources."""
        registry = DataSourceRegistry()
        results = registry.find_by_keyword("hospital")
        
        assert len(results) > 0
    
    def test_find_by_keyword_schools(self):
        """Find education data sources."""
        registry = DataSourceRegistry()
        results = registry.find_by_keyword("school")
        
        assert len(results) > 0
    
    def test_find_by_region_and_type(self):
        """Find sources by region and category."""
        registry = DataSourceRegistry()
        results = registry.find_by_region_and_type("india", "health")
        
        assert len(results) > 0
    
    def test_find_for_description_returns_scored_results(self):
        """Find sources with relevance scores."""
        registry = DataSourceRegistry()
        results = registry.find_for_description("hospitals in India")
        
        # Should return tuples of (source, score)
        assert len(results) > 0
        assert all(len(r) == 2 for r in results)
        assert all(0 <= r[1] <= 1 for r in results)
    
    def test_results_sorted_by_relevance(self):
        """Results sorted by relevance score."""
        registry = DataSourceRegistry()
        results = registry.find_for_description("hospitals")
        
        if len(results) > 1:
            # Check descending order
            scores = [r[1] for r in results]
            assert scores == sorted(scores, reverse=True)


class TestScrapedDataProcessor:
    def test_csv_to_geojson_with_coordinates(self):
        """Convert CSV with coordinates to GeoJSON."""
        csv_data = [
            {"name": "Hospital A", "latitude": 13.0827, "longitude": 80.2707},
            {"name": "Hospital B", "latitude": 13.0850, "longitude": 80.2750},
        ]
        
        geojson = ScrapedDataProcessor.csv_to_geojson(csv_data)
        
        assert geojson["type"] == "FeatureCollection"
        assert len(geojson["features"]) == 2
        assert geojson["features"][0]["geometry"]["type"] == "Point"
    
    def test_csv_to_geojson_preserves_properties(self):
        """GeoJSON preserves CSV properties."""
        csv_data = [
            {
                "name": "Hospital A",
                "latitude": 13.0827,
                "longitude": 80.2707,
                "beds": 100,
                "type": "government",
            },
        ]
        
        geojson = ScrapedDataProcessor.csv_to_geojson(csv_data)
        feature = geojson["features"][0]
        
        assert feature["properties"]["name"] == "Hospital A"
        assert feature["properties"]["beds"] == 100
        assert feature["properties"]["type"] == "government"
    
    def test_csv_to_geojson_custom_field_names(self):
        """CSV to GeoJSON with custom field names."""
        csv_data = [
            {"title": "Place 1", "lat": 13.0827, "lon": 80.2707},
        ]
        
        geojson = ScrapedDataProcessor.csv_to_geojson(
            csv_data,
            lat_field="lat",
            lon_field="lon",
            name_field="title",
        )
        
        assert len(geojson["features"]) == 1
        assert geojson["features"][0]["properties"]["_name"] == "Place 1"
    
    def test_geojson_to_map2arcpy_instruction(self):
        """Convert GeoJSON to map2arcpy instruction."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [80.2707, 13.0827]},
                    "properties": {"hospital_name": "Hospital A"},
                },
            ],
        }
        
        instruction = ScrapedDataProcessor.geojson_to_map2arcpy(geojson)
        
        assert "1 features" in instruction or "data" in instruction
        assert "titled" in instruction
    
    def test_deduplicate_features_removes_close_points(self):
        """Remove duplicate features within distance threshold."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [80.2707, 13.0827]},
                    "properties": {"name": "A"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [80.2707, 13.0827]},  # Same location
                    "properties": {"name": "B"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [80.3707, 13.0827]},  # Far away
                    "properties": {"name": "C"},
                },
            ],
        }
        
        dedup = ScrapedDataProcessor.deduplicate_features(geojson, duplicate_distance_m=100)
        
        # Should have 2 features (A and C, B is duplicate of A)
        assert len(dedup["features"]) == 2
    
    def test_filter_by_bbox(self):
        """Filter GeoJSON features by bounding box."""
        geojson = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [80.0, 13.0]},
                    "properties": {"name": "Inside"},
                },
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [90.0, 20.0]},
                    "properties": {"name": "Outside"},
                },
            ],
        }
        
        # BBox: minlon, minlat, maxlon, maxlat
        filtered = ScrapedDataProcessor.filter_by_bbox(
            geojson,
            bbox=(79.0, 12.0, 81.0, 14.0),
        )
        
        assert len(filtered["features"]) == 1
        assert filtered["features"][0]["properties"]["name"] == "Inside"


class TestScrapyDataCollector:
    def test_collector_initialization(self):
        """Initialize data collector."""
        collector = ScrapyDataCollector()
        assert "csv" in collector.fetchers
        assert "geojson" in collector.fetchers
        assert "api" in collector.fetchers
    
    def test_batch_fetch_multiple_sources(self):
        """Fetch from multiple sources (mock)."""
        collector = ScrapyDataCollector()
        
        # This would require actual web services to test fully
        # Here we just verify the structure
        assert hasattr(collector, "batch_fetch")
        assert callable(collector.batch_fetch)


class TestDataDiscovery:
    def test_discover_web_data_sources_hospitals(self):
        """Discover hospital data sources."""
        result = discover_web_data_sources("hospitals in India")
        
        assert "discovered_sources" in result
        assert "description" in result
        assert len(result["discovered_sources"]) > 0
    
    def test_discover_web_data_sources_schools(self):
        """Discover school data sources."""
        result = discover_web_data_sources("schools directory")
        
        assert len(result["discovered_sources"]) > 0
    
    def test_discover_returns_relevance_scores(self):
        """Discovered sources include relevance scores."""
        result = discover_web_data_sources("hospitals")
        
        sources = result["discovered_sources"]
        for item in sources:
            assert "source" in item
            assert "relevance_score" in item
            assert 0 <= item["relevance_score"] <= 1
    
    def test_get_data_source_by_name(self):
        """Get a specific data source by name."""
        source = get_data_source_by_name("India Health Facilities")
        
        assert source is not None
        assert source.name == "India Health Facilities"
        assert source.data_type == "csv"


class TestIntegration:
    def test_workflow_from_description_to_geojson(self):
        """End-to-end: description -> discover sources -> prepare instruction."""
        # Step 1: Discover sources
        discovery = discover_web_data_sources("hospitals in India")
        sources = discovery["discovered_sources"]
        
        assert len(sources) > 0
        
        # Step 2: Get top source
        top_source = sources[0]["source"]
        assert top_source["name"]
        assert top_source["data_type"]
        assert top_source["url"]
    
    def test_csv_data_to_map_instruction_flow(self):
        """CSV data -> GeoJSON -> map2arcpy instruction."""
        # Mock CSV data
        csv_data = [
            {
                "school_name": "School A",
                "latitude": 13.0827,
                "longitude": 80.2707,
                "students": 500,
            },
            {
                "school_name": "School B",
                "latitude": 13.0850,
                "longitude": 80.2750,
                "students": 400,
            },
        ]
        
        # Convert to GeoJSON
        geojson = ScrapedDataProcessor.csv_to_geojson(
            csv_data,
            lat_field="latitude",
            lon_field="longitude",
            name_field="school_name",
        )
        
        assert len(geojson["features"]) == 2
        
        # Generate map instruction
        instruction = ScrapedDataProcessor.geojson_to_map2arcpy(geojson)
        
        assert "2 features" in instruction or "features" in instruction
        assert "School" in instruction or "titled" in instruction


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
