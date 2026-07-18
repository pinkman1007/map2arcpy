"""
Tests for the recommendations module.
"""

import pytest
from map2arcpy.recommendations import (
    detect_map_types,
    recommend_data_sources,
    recommend_operations,
    recommend_cartography,
    recommend_crs,
    generate_optimized_instructions,
    get_full_recommendations,
)


class TestMapTypeDetection:
    def test_detect_choropleth(self):
        """Detect choropleth map type."""
        result = detect_map_types("choropleth of population by district")
        assert any(t[0] == "choropleth" for t in result)
    
    def test_detect_heatmap(self):
        """Detect heatmap from density keywords."""
        result = detect_map_types("density heatmap of accidents")
        assert any(t[0] == "heatmap" for t in result)
    
    def test_detect_buffer(self):
        """Detect buffer analysis."""
        result = detect_map_types("buffer hospitals by 500 meters")
        assert any(t[0] == "buffer" for t in result)
    
    def test_detect_terrain(self):
        """Detect terrain analysis."""
        result = detect_map_types("terrain elevation slope map from dem")
        assert any(t[0] == "terrain" for t in result)
    
    def test_confidence_scores(self):
        """Verify confidence scores are between 0 and 1."""
        result = detect_map_types("choropleth choropleth choropleth")  # Multiple matches
        for _, confidence in result:
            assert 0 <= confidence <= 1


class TestDataSourceRecommendations:
    def test_hospitals_osm_recommendation(self):
        """Recommend hospitals from OSM."""
        result = recommend_data_sources("map of hospitals in Visakhapatnam", web_enabled=True)
        assert len(result["sources"]) > 0
        assert any(s["osm"] == "hospitals" for s in result["sources"])
    
    def test_schools_osm_recommendation(self):
        """Recommend schools from OSM."""
        result = recommend_data_sources("schools distribution map")
        assert any(s["osm"] == "schools" for s in result["sources"])
    
    def test_location_extraction(self):
        """Extract location from description."""
        result = recommend_data_sources("hospitals in Bangalore")
        assert result["location"] is not None
        assert "Bangalore" in result["location"]
    
    def test_web_instructions_generation(self):
        """Generate web instructions."""
        result = recommend_data_sources("hospitals in New York")
        assert result["instructions"] != ""
        assert "osm" in result["instructions"]


class TestOperationRecommendations:
    def test_buffer_operation_detection(self):
        """Detect buffer operation."""
        result = recommend_operations("buffer by 500 meters")
        assert "buffer" in result["operations"]
    
    def test_clip_operation_detection(self):
        """Detect clip operation."""
        result = recommend_operations("clip to district boundary")
        assert "clip" in result["operations"]
    
    def test_operation_sequence(self):
        """Verify logical operation sequence."""
        result = recommend_operations("buffer and clip and dissolve")
        sequence = result["sequence"]
        # Buffer should come before clip in sequence
        if "buffer" in sequence and "clip" in sequence:
            assert sequence.index("buffer") < sequence.index("clip")


class TestCartographyRecommendations:
    def test_choropleth_color_ramp_recommendation(self):
        """Recommend color ramp for choropleth."""
        result = recommend_cartography("choropleth of population")
        assert "choropleth" in result["practices"]
        assert "color_recommendations" in result
    
    def test_layout_page_size_for_regional_maps(self):
        """Recommend A1 for large regional maps."""
        result = recommend_cartography("regional state-level map of rainfall")
        assert result["layout"]["page"] in ["A1L", "A0L"]
    
    def test_layout_page_size_for_detailed_maps(self):
        """Recommend A3 for detailed local maps."""
        result = recommend_cartography("detailed city ward map")
        assert result["layout"]["page"] in ["A3P", "A4P"]


class TestCRSRecommendations:
    def test_india_crs_for_india_location(self):
        """Recommend UTM 43N for India."""
        result = recommend_crs("map of India with buffer analysis", "India")
        # Should recommend projected CRS (UTM)
        assert result["recommended_epsg"] in [32643]  # UTM 43N
    
    def test_utm_for_distance_analysis(self):
        """Recommend UTM for buffer/distance operations."""
        result = recommend_crs("buffer analysis requires accurate distances")
        # Should recommend projected CRS
        assert result["recommended_epsg"] != 4326
    
    def test_wgs84_default(self):
        """Default to WGS84 for generic maps."""
        result = recommend_crs("simple display map")
        assert result["recommended_epsg"] == 4326


class TestOptimizedInstructions:
    def test_generate_instructions_with_osm(self):
        """Generate optimized instructions with OSM data."""
        instructions = generate_optimized_instructions("hospitals in Bangalore", web_enabled=True)
        assert len(instructions) > 0
        # Should include hospital-related content
        assert any(word in instructions.lower() for word in ["hospital", "osm"])
    
    def test_generate_instructions_with_layout(self):
        """Generate instructions with title and layout."""
        instructions = generate_optimized_instructions(
            "titled 'Hospital Distribution Map', A3 landscape"
        )
        assert "Hospital Distribution Map" in instructions
        assert "A3" in instructions or "landscape" in instructions
    
    def test_generate_instructions_with_choropleth(self):
        """Generate instructions for choropleth."""
        instructions = generate_optimized_instructions("choropleth of population density")
        assert "choropleth" in instructions.lower() or "classify" in instructions.lower()


class TestFullRecommendations:
    def test_comprehensive_recommendations(self):
        """Test full recommendation set."""
        result = get_full_recommendations(
            "hospitals from osm in Bangalore, titled 'Health Access Map', A3 landscape",
            web_enabled=True
        )
        
        # Should have all recommendation categories
        assert "data_sources" in result
        assert "operations" in result
        assert "cartography" in result
        assert "crs" in result
        assert "optimized_instructions" in result
        
        # Verify data source recommendations
        assert "sources" in result["data_sources"]
        
        # Verify cartography recommendations
        assert "layout" in result["cartography"]
    
    def test_empty_description(self):
        """Handle empty description gracefully."""
        result = get_full_recommendations("")
        assert "optimized_instructions" in result


class TestIntegration:
    def test_workflow_from_description_to_instructions(self):
        """Test complete workflow from description to optimized instructions."""
        description = "Build a choropleth map of population density by district, " \
                      "showing hospitals from OSM, buffer by 5km, in Bangalore, " \
                      "titled 'Health Access Map', A3 landscape, 300 dpi"
        
        # Get recommendations
        recs = get_full_recommendations(description, web_enabled=True)
        
        # Verify key recommendations
        assert recs["data_sources"]["location"] is not None
        assert len(recs["data_sources"]["sources"]) > 0
        assert "choropleth" in recs["cartography"]["detected_types"]
        
        # Verify optimized instructions are generated
        optimized = recs["optimized_instructions"]
        assert len(optimized) > len(description) or len(optimized) >= len(description.split(",")[0])
        
        # Verify CRS recommendation for distance operations
        assert recs["crs"]["recommended_epsg"] != 4326  # Should not be WGS84


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
