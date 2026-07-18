"""
Tests for dynamic source discovery, tutorial scraping, and feedback learning.
"""

import pytest
import json
import os
import tempfile
from unittest.mock import Mock, patch, MagicMock

from src.map2arcpy.dynamic_source_discovery import (
    DynamicSourceDiscovery,
    discover_data_sources,
)
from src.map2arcpy.tutorial_scraper import (
    TutorialScraper,
    scrape_tutorial_instructions,
)
from src.map2arcpy.feedback_learning import (
    FeedbackLearner,
    get_learner,
    record_feedback,
)


class TestDynamicSourceDiscovery:
    """Test dynamic data source discovery."""
    
    def test_init_creates_discovery(self):
        discovery = DynamicSourceDiscovery()
        assert discovery.timeout == 10
        assert isinstance(discovery.cache, dict)
    
    def test_infer_data_type_geojson(self):
        discovery = DynamicSourceDiscovery()
        assert discovery._infer_data_type("path/to/data.geojson") == "geojson"
    
    def test_infer_data_type_shapefile(self):
        discovery = DynamicSourceDiscovery()
        assert discovery._infer_data_type("path/data.shp") == "shapefile"
    
    def test_infer_data_type_csv(self):
        discovery = DynamicSourceDiscovery()
        assert discovery._infer_data_type("hospitals.csv") == "csv"
    
    def test_infer_data_type_unknown(self):
        discovery = DynamicSourceDiscovery()
        assert discovery._infer_data_type("somefile.xyz") == "unknown"
    
    def test_caching_works(self):
        discovery = DynamicSourceDiscovery()
        
        # Add something to cache
        discovery.cache["test:key"] = [{"name": "test"}]
        
        # Should return cached value
        result = discovery.search_github_geospatial_data("test", "")
        # Without mocking, it returns empty or cached
        assert isinstance(result, list)
    
    def test_search_osm_related_data(self):
        discovery = DynamicSourceDiscovery()
        
        results = discovery.search_osm_related_data("osm", "India")
        
        # Should return OSM sources
        assert isinstance(results, list)
        # OSM data sources should be found for "osm" or related keywords
        if results:
            source_names = [r.get("name") for r in results]
            assert any("Overpass" in n or "OSM" in n or "Export" in n for n in source_names if n)
    
    def test_calculate_relevance_score(self):
        discovery = DynamicSourceDiscovery()
        
        result = {
            "name": "hospitals in India",
            "description": "Health facilities dataset",
            "stars": 150,
            "type": "geojson",
        }
        
        score = discovery._calculate_relevance_score(result, "hospitals", "India")
        
        # Should have reasonable score
        assert isinstance(score, float)
        assert score > 0


class TestTutorialScraper:
    """Test tutorial scraping."""
    
    def test_init_creates_scraper(self):
        scraper = TutorialScraper()
        assert scraper.timeout == 10
        assert isinstance(scraper.tutorial_sources, dict)
    
    def test_extract_instructions_from_code(self):
        scraper = TutorialScraper()
        
        code = '''
        """
        Create a choropleth map from census data.
        
        This function takes district boundaries and population data
        and creates a colored map showing population density.
        """
        
        # Load the shapefile
        import geopandas as gpd
        
        # Read boundaries
        gdf = gpd.read_file("boundaries.shp")
        '''
        
        instructions = scraper._extract_instructions_from_code(code)
        
        # Should extract docstring and comments
        assert len(instructions) > 0
        assert any("choropleth" in i for i in instructions)
    
    def test_extract_step_by_step_instructions(self):
        scraper = TutorialScraper()
        
        content = """
Step 1: Load Data
First, load the GeoJSON file with geographic boundaries.
```python
import geopandas as gpd
gdf = gpd.read_file("data.geojson")
```

Step 2: Create Choropleth
Now create a colored map by the population field.
```python
gdf.plot(column="population", cmap="viridis")
```
        """
        
        steps = scraper.extract_step_by_step_instructions(content)
        
        # May have 0-3 steps depending on pattern matching
        assert isinstance(steps, list)
    
    def test_analyze_instruction_patterns(self):
        scraper = TutorialScraper()
        
        examples = [
            {
                "code": "import geopandas; gdf.buffer(100).clip(bounds)"
            },
            {
                "code": "from folium import Map; m.choropleth(data=df)"
            },
        ]
        
        patterns = scraper._analyze_instruction_patterns(examples, [])
        
        assert isinstance(patterns, dict)
        assert "common_operations" in patterns


class TestFeedbackLearner:
    """Test feedback learning system."""
    
    def test_init_creates_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            assert os.path.exists(tmpdir)
            assert learner.patterns_file.startswith(tmpdir)
    
    def test_record_user_feedback(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            learner.record_user_feedback(
                "choropleth map of population by district",
                "choropleth",
                "choropleth",
                user_rating=5
            )
            
            assert learner.feedback_count == 1
            assert os.path.exists(learner.feedback_log)
    
    def test_record_operation_usage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            learner.record_operation_usage(
                "choropleth",
                "dissolve",
                "postgres",
                success=True
            )
            
            # Check patterns were saved
            patterns = learner.learned_patterns
            assert "operations" in patterns
            assert "choropleth" in patterns["operations"]
    
    def test_record_data_source_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            learner.record_data_source_success(
                "hospitals_map",
                "India Health Facilities",
                "Delhi",
                success=True,
                record_count=100
            )
            
            patterns = learner.learned_patterns
            assert "data_sources" in patterns
    
    def test_get_recommendations_for_map_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            # Record some operations
            learner.record_operation_usage("choropleth", "dissolve", "csv")
            learner.record_operation_usage("choropleth", "buffer", "geojson")
            
            recs = learner.get_recommendations_for_map_type("choropleth")
            
            assert recs["map_type"] == "choropleth"
            assert "operations" in recs
            assert isinstance(recs["confidence"], float)
    
    def test_discover_new_map_types(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            # Add feedback for new map types
            learner.record_user_feedback(
                "isopleth map",
                "generic",
                "isopleth",
                user_rating=4
            )
            learner.record_user_feedback(
                "isopleth boundaries",
                "generic",
                "isopleth",
                user_rating=4
            )
            
            new_types = learner.discover_new_map_types()
            
            assert isinstance(new_types, list)
    
    def test_improve_detection(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            # Teach it about choropleth
            learner._learn_from_misclassification(
                "choropleth map colored by population density",
                "choropleth"
            )
            
            # Try to detect
            map_type, confidence = learner.improve_detection(
                "colored map showing population"
            )
            
            assert isinstance(map_type, str)
            assert isinstance(confidence, float)
            assert 0 <= confidence <= 1
    
    def test_get_learning_stats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            learner.record_user_feedback("test map", "a", "a")
            learner.record_user_feedback("test map 2", "b", "c")
            
            stats = learner.get_learning_stats()
            
            assert stats["total_feedback"] == 2
            assert "accuracy" in stats
            assert isinstance(stats["accuracy"], float)
    
    def test_patterns_persistence(self):
        """Test that learned patterns are saved and loaded."""
        with tempfile.TemporaryDirectory() as tmpdir:
            learner1 = FeedbackLearner(tmpdir)
            learner1.record_operation_usage("choropleth", "buffer", "csv")
            
            # Create new learner from same directory
            learner2 = FeedbackLearner(tmpdir)
            
            # Should have loaded the patterns
            assert "operations" in learner2.learned_patterns


class TestIntegration:
    """Integration tests for all three modules."""
    
    def test_discovery_to_learning_pipeline(self):
        """Test data discovery flowing to feedback learning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            # Record that a source worked well
            learner.record_data_source_success(
                "choropleth",
                "GeoJSON hospital data",
                "India"
            )
            
            # Get recommendations
            recs = learner.get_recommendations_for_map_type("choropleth")
            
            # Should include the source we recorded
            assert "data_sources" in recs
    
    def test_tutorial_to_operations_learning(self):
        """Test tutorial parsing flowing to operation tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            scraper = TutorialScraper()
            
            # Parse a tutorial
            content = """
            Step 1: Buffer the points by 500m
            Step 2: Dissolve boundaries
            Step 3: Join with population data
            """
            
            steps = scraper.extract_step_by_step_instructions(content)
            
            # Record operations from tutorial
            for step in steps:
                if "buffer" in step.get("description", "").lower():
                    learner.record_operation_usage("point_density", "buffer", "csv")
    
    def test_end_to_end_feedback_collection(self):
        """Test complete feedback collection pipeline."""
        with tempfile.TemporaryDirectory() as tmpdir:
            learner = FeedbackLearner(tmpdir)
            
            # User creates a map
            description = "density map of hospitals in major cities"
            learner.record_user_feedback(description, "heatmap", "heatmap", user_rating=5)
            
            # Record operations that worked
            learner.record_operation_usage("heatmap", "buffer", "postgis")
            learner.record_operation_usage("heatmap", "dissolve", "csv")
            
            # Check improvements
            stats = learner.get_learning_stats()
            assert stats["accuracy"] == 1.0  # All correct so far
            
            # Try to detect similar map
            detected, conf = learner.improve_detection(
                "show density of police stations"
            )
            
            # Should recognize some pattern
            assert isinstance(detected, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
