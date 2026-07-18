"""
Tutorial and example scraper for mapping instructions.

Crawls mapping tutorials, blog posts, and examples to learn how to prepare
different map types and extract best-practice instructions.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
import warnings

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None


class TutorialScraper:
    """Scrape and parse mapping tutorials for instructions."""
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.cache: Dict[str, List[Dict[str, Any]]] = {}
        
        # Known tutorial sources
        self.tutorial_sources = {
            "arcgis": "https://learn.arcgis.com/en/galleries/",
            "geospatial-python": "https://automating-gis-processes.github.io/",
            "kartograph": "https://kartograph.org/",
            "mapbox": "https://docs.mapbox.com/help/",
        }
    
    def scrape_map_examples_from_github(
        self,
        map_type: str,
        language: str = "python"
    ) -> List[Dict[str, Any]]:
        """
        Scrape mapping examples from GitHub repositories.
        
        Args:
            map_type: Type of map (e.g., "choropleth", "heatmap")
            language: Programming language (default: python)
        
        Returns:
            List of example scripts with instructions
        """
        if not requests:
            return []
        
        cache_key = f"github_examples:{map_type}:{language}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        results = []
        
        try:
            # Search for examples
            search_query = f"{map_type} map example language:{language}"
            url = "https://api.github.com/search/code"
            
            params = {
                "q": search_query,
                "sort": "stars",
                "per_page": 5,
            }
            
            resp = requests.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return results
            
            data = resp.json()
            
            for item in data.get("items", [])[:3]:
                # Extract code snippet
                code_url = item.get("url", "").replace("api.github.com", "raw.githubusercontent.com")
                
                try:
                    code_resp = requests.get(code_url, timeout=self.timeout)
                    if code_resp.status_code == 200:
                        code = code_resp.text
                        
                        # Extract instructions (comments, docstrings)
                        instructions = self._extract_instructions_from_code(code)
                        
                        results.append({
                            "map_type": map_type,
                            "language": language,
                            "code": code,
                            "instructions": instructions,
                            "source_url": item.get("html_url", ""),
                            "repository": item.get("repository", {}).get("full_name", ""),
                            "stars": item.get("repository", {}).get("stargazers_count", 0),
                        })
                except Exception:
                    pass
            
            self.cache[cache_key] = results
            return results
        
        except Exception as e:
            warnings.warn(f"GitHub examples scrape failed: {e}")
            return []
    
    def scrape_mapping_blog_tutorials(
        self,
        map_type: str,
        limit: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Scrape mapping tutorials from popular geospatial blogs.
        
        Targets: Medium, Towards Data Science, ArcGIS blog, etc.
        """
        if not requests or not BeautifulSoup:
            return []
        
        cache_key = f"blog_tutorials:{map_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        results = []
        
        # Blog URLs to scrape
        blog_sources = [
            ("https://medium.com/search?q=" + map_type + " map tutorial", "medium"),
            ("https://towardsdatascience.com/search?q=" + map_type, "towardsdatascience"),
        ]
        
        for url, source in blog_sources:
            try:
                resp = requests.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    continue
                
                soup = BeautifulSoup(resp.content, "html.parser")
                
                # Extract article links and metadata
                articles = soup.find_all("article")[:limit]
                
                for article in articles:
                    title_elem = article.find("h2") or article.find("h3")
                    title = title_elem.get_text(strip=True) if title_elem else ""
                    
                    link_elem = article.find("a", href=True)
                    link = link_elem["href"] if link_elem else ""
                    
                    if not link.startswith("http"):
                        link = "https://" + source + link
                    
                    # Scrape content
                    summary = article.find("p")
                    summary_text = summary.get_text(strip=True) if summary else ""
                    
                    results.append({
                        "map_type": map_type,
                        "source": source,
                        "title": title,
                        "url": link,
                        "summary": summary_text,
                        "type": "blog",
                    })
            
            except Exception:
                pass
        
        self.cache[cache_key] = results
        return results
    
    def scrape_official_documentation(
        self,
        tool: str,
        map_type: str
    ) -> Dict[str, Any]:
        """
        Scrape official documentation for a specific tool and map type.
        
        Supports: ArcGIS, Folium, GeoPandas, etc.
        """
        if not requests or not BeautifulSoup:
            return {}
        
        cache_key = f"docs:{tool}:{map_type}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        result = {}
        
        # Documentation URLs
        doc_urls = {
            "arcgis": f"https://pro.arcgis.com/en/pro-app/latest/help/mapping/",
            "folium": f"https://python-visualization.github.io/folium/",
            "geopandas": f"https://geopandas.org/docs/",
        }
        
        if tool not in doc_urls:
            return result
        
        try:
            base_url = doc_urls[tool]
            resp = requests.get(base_url, timeout=self.timeout)
            
            if resp.status_code != 200:
                return result
            
            soup = BeautifulSoup(resp.content, "html.parser")
            
            # Extract relevant sections
            result = {
                "tool": tool,
                "map_type": map_type,
                "url": base_url,
                "title": soup.title.string if soup.title else "",
                "sections": [],
            }
            
            # Find sections related to map type
            for heading in soup.find_all(["h1", "h2", "h3"]):
                text = heading.get_text(strip=True).lower()
                
                if map_type.lower() in text:
                    # Extract following paragraphs as instructions
                    instructions = []
                    
                    for sibling in heading.find_all_next(["p", "li"]):
                        if sibling.name in ["h1", "h2", "h3"]:
                            break
                        
                        instructions.append(sibling.get_text(strip=True))
                    
                    result["sections"].append({
                        "heading": text,
                        "instructions": instructions[:3],  # First 3 paragraphs
                    })
            
            self.cache[cache_key] = result
            return result
        
        except Exception:
            return result
    
    def _extract_instructions_from_code(self, code: str) -> List[str]:
        """Extract instructions from code comments and docstrings."""
        instructions = []
        
        # Extract docstrings
        docstring_pattern = r'"""(.*?)"""'
        for match in re.finditer(docstring_pattern, code, re.DOTALL):
            instructions.append(match.group(1).strip())
        
        # Extract single-line comments
        for line in code.split("\n"):
            line = line.strip()
            
            if line.startswith("#") and not line.startswith("##"):
                comment = line[1:].strip()
                
                # Skip shebang and encoding
                if not comment.startswith("!") and not comment.startswith("coding"):
                    instructions.append(comment)
        
        return instructions
    
    def extract_step_by_step_instructions(
        self,
        tutorial_content: str
    ) -> List[Dict[str, Any]]:
        """
        Parse tutorial content into step-by-step instructions.
        
        Returns structured steps with code examples.
        """
        steps = []
        
        # Split by numbered sections or common patterns
        sections = re.split(
            r"(?:^|\n)\s*(?:step\s+\d+|##\s+|\d+\.\s+)",
            tutorial_content,
            flags=re.MULTILINE
        )
        
        for i, section in enumerate(sections[1:], 1):
            # Extract description and code
            lines = section.strip().split("\n")
            
            description_lines = []
            code_lines = []
            in_code = False
            
            for line in lines:
                if line.strip().startswith(("```", ">>>", "import", "from", "def")):
                    in_code = True
                
                if in_code:
                    code_lines.append(line)
                else:
                    description_lines.append(line)
            
            steps.append({
                "step": i,
                "description": "\n".join(description_lines).strip(),
                "code": "\n".join(code_lines).strip(),
            })
        
        return [s for s in steps if s["description"] or s["code"]]
    
    def generate_instruction_from_tutorials(
        self,
        map_type: str
    ) -> str:
        """
        Generate optimized map2arcpy instruction by learning from tutorials.
        """
        # Gather examples
        examples = self.scrape_map_examples_from_github(map_type)
        blogs = self.scrape_mapping_blog_tutorials(map_type)
        
        if not examples and not blogs:
            return ""
        
        # Analyze patterns from examples
        patterns = self._analyze_instruction_patterns(examples, blogs)
        
        # Generate instruction
        instruction = self._build_instruction_from_patterns(map_type, patterns)
        
        return instruction
    
    def _analyze_instruction_patterns(
        self,
        examples: List[Dict[str, Any]],
        blogs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze common patterns in examples and tutorials."""
        patterns = {
            "common_operations": [],
            "common_parameters": [],
            "color_schemes": [],
            "data_sources": [],
        }
        
        # Extract patterns from code examples
        for example in examples:
            code = example.get("code", "")
            
            # Find common operations
            operations = re.findall(r"\b(buffer|clip|dissolve|join|select|filter)\b", code, re.I)
            patterns["common_operations"].extend(operations)
            
            # Find color/ramp parameters
            colors = re.findall(r"(?:ramp|color|palette)=(?:'[^']*'|\"[^\"]*\")", code, re.I)
            patterns["color_schemes"].extend(colors)
        
        # Count frequencies
        from collections import Counter
        patterns["common_operations"] = [
            op for op, _ in Counter(patterns["common_operations"]).most_common(3)
        ]
        patterns["color_schemes"] = [
            c for c, _ in Counter(patterns["color_schemes"]).most_common(2)
        ]
        
        return patterns
    
    def _build_instruction_from_patterns(
        self,
        map_type: str,
        patterns: Dict[str, Any]
    ) -> str:
        """Build map2arcpy instruction from analyzed patterns."""
        parts = []
        
        # Data loading
        parts.append(f"load data")
        
        # Operations
        for op in patterns.get("common_operations", []):
            parts.append(op)
        
        # Rendering
        if map_type == "choropleth":
            parts.append("choropleth, classify=quantile")
        elif map_type == "heatmap":
            parts.append("density heatmap")
        elif map_type == "buffer":
            parts.append("buffer, visualize borders")
        
        # Export
        parts.append("titled 'Map', A4L, 300 dpi")
        
        return ", ".join(parts)


# Convenience function
def scrape_tutorial_instructions(
    map_type: str,
    source: str = "github"
) -> List[Dict[str, Any]]:
    """Quick access to tutorial scraping."""
    scraper = TutorialScraper()
    
    if source == "github":
        return scraper.scrape_map_examples_from_github(map_type)
    elif source == "blog":
        return scraper.scrape_mapping_blog_tutorials(map_type)
    else:
        return []
