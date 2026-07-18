"""
Feedback learning system for dynamic map type recognition.

Learns from user interactions and feedback to recognize new map types
and improve recommendations over time.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import Counter


class FeedbackLearner:
    """Learn and improve from user feedback."""
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        Initialize feedback learner.
        
        Args:
            storage_dir: Directory to store learned patterns (default: ~/.map2arcpy/ml)
        """
        if storage_dir is None:
            home = os.path.expanduser("~")
            storage_dir = os.path.join(home, ".map2arcpy", "ml")
        
        self.storage_dir = storage_dir
        self.patterns_file = os.path.join(storage_dir, "learned_patterns.json")
        self.feedback_log = os.path.join(storage_dir, "feedback_log.jsonl")
        
        # Ensure directory exists
        os.makedirs(storage_dir, exist_ok=True)
        
        # Load existing patterns
        self.learned_patterns = self._load_patterns()
        self.feedback_count = 0
    
    def record_user_feedback(
        self,
        description: str,
        detected_map_type: str,
        actual_map_type: str,
        user_rating: int = 0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Record user feedback about map type detection.
        
        Args:
            description: User's map description
            detected_map_type: What was predicted
            actual_map_type: What it should have been
            user_rating: 1-5 satisfaction rating
            metadata: Additional context
        """
        feedback = {
            "timestamp": datetime.now().isoformat(),
            "description": description,
            "detected": detected_map_type,
            "actual": actual_map_type,
            "rating": user_rating,
            "correct": detected_map_type == actual_map_type,
            "metadata": metadata or {},
        }
        
        # Append to feedback log
        with open(self.feedback_log, "a") as f:
            f.write(json.dumps(feedback) + "\n")
        
        self.feedback_count += 1
        
        # Learn from this feedback
        if not feedback["correct"]:
            self._learn_from_misclassification(description, actual_map_type)
        
        if user_rating >= 4:
            self._learn_from_positive_feedback(description, actual_map_type)
    
    def record_operation_usage(
        self,
        map_type: str,
        operation: str,
        data_source: str,
        success: bool = True
    ) -> None:
        """
        Record successful operations for a map type.
        
        Builds knowledge base of what operations work well for each map type.
        """
        if "operations" not in self.learned_patterns:
            self.learned_patterns["operations"] = {}
        
        if map_type not in self.learned_patterns["operations"]:
            self.learned_patterns["operations"][map_type] = {}
        
        key = f"{operation}:{data_source}"
        
        if key not in self.learned_patterns["operations"][map_type]:
            self.learned_patterns["operations"][map_type][key] = {
                "count": 0,
                "success": 0,
                "last_used": None,
            }
        
        entry = self.learned_patterns["operations"][map_type][key]
        entry["count"] += 1
        if success:
            entry["success"] += 1
        entry["last_used"] = datetime.now().isoformat()
        
        self._save_patterns()
    
    def record_data_source_success(
        self,
        map_type: str,
        source_name: str,
        region: str,
        success: bool = True,
        record_count: int = 0
    ) -> None:
        """
        Record successful data source usage.
        
        Tracks which data sources work well for which map types.
        """
        if "data_sources" not in self.learned_patterns:
            self.learned_patterns["data_sources"] = {}
        
        if map_type not in self.learned_patterns["data_sources"]:
            self.learned_patterns["data_sources"][map_type] = {}
        
        key = f"{source_name}:{region}"
        
        if key not in self.learned_patterns["data_sources"][map_type]:
            self.learned_patterns["data_sources"][map_type][key] = {
                "count": 0,
                "success": 0,
                "total_records": 0,
                "last_used": None,
            }
        
        entry = self.learned_patterns["data_sources"][map_type][key]
        entry["count"] += 1
        if success:
            entry["success"] += 1
        entry["total_records"] += record_count
        entry["last_used"] = datetime.now().isoformat()
        
        self._save_patterns()
    
    def get_recommendations_for_map_type(
        self,
        map_type: str
    ) -> Dict[str, Any]:
        """
        Get learned recommendations for a specific map type.
        
        Returns operations, data sources, and parameters that work well.
        """
        recommendations = {
            "map_type": map_type,
            "operations": [],
            "data_sources": [],
            "parameters": [],
            "confidence": 0.0,
        }
        
        # Get best operations
        if "operations" in self.learned_patterns and map_type in self.learned_patterns["operations"]:
            ops = self.learned_patterns["operations"][map_type]
            
            # Score operations by success rate
            scored_ops = []
            for key, stats in ops.items():
                if stats["count"] > 0:
                    success_rate = stats["success"] / stats["count"]
                    scored_ops.append((key, success_rate, stats["count"]))
            
            scored_ops.sort(key=lambda x: (-x[1], -x[2]))
            recommendations["operations"] = [op[0] for op in scored_ops[:3]]
        
        # Get best data sources
        if "data_sources" in self.learned_patterns and map_type in self.learned_patterns["data_sources"]:
            sources = self.learned_patterns["data_sources"][map_type]
            
            scored_sources = []
            for key, stats in sources.items():
                if stats["count"] > 0:
                    success_rate = stats["success"] / stats["count"]
                    scored_sources.append((key, success_rate, stats["count"]))
            
            scored_sources.sort(key=lambda x: (-x[1], -x[2]))
            recommendations["data_sources"] = [src[0] for src in scored_sources[:3]]
        
        # Calculate confidence
        total_feedback = sum(
            1 for feedback in self._read_feedback_log()
            if feedback.get("actual") == map_type
        )
        
        recommendations["confidence"] = min(1.0, total_feedback / 10.0)
        
        return recommendations
    
    def discover_new_map_types(self) -> List[Dict[str, Any]]:
        """
        Discover new/uncommon map types from feedback.
        
        Returns map types that users have created that we don't have
        built-in recognition for.
        """
        new_types = []
        
        # Collect all unique map types from feedback
        all_types = Counter()
        
        for feedback in self._read_feedback_log():
            actual = feedback.get("actual", "")
            if actual and actual not in ["choropleth", "heatmap", "buffer", "terrain"]:
                all_types[actual] += 1
        
        # Filter for types with multiple instances
        for map_type, count in all_types.most_common():
            if count >= 2:  # At least 2 instances
                new_types.append({
                    "name": map_type,
                    "occurrences": count,
                    "pattern": self._extract_pattern_for_type(map_type),
                })
        
        return new_types
    
    def _extract_pattern_for_type(self, map_type: str) -> Dict[str, Any]:
        """Extract common patterns for a new map type from feedback."""
        pattern = {
            "keywords": [],
            "common_operations": [],
            "data_sources": [],
            "parameters": [],
        }
        
        related_feedback = [
            f for f in self._read_feedback_log()
            if f.get("actual") == map_type
        ]
        
        # Extract keywords from descriptions
        all_text = " ".join(f.get("description", "") for f in related_feedback)
        words = re.findall(r"\b\w+\b", all_text.lower())
        
        # Get most common significant words
        from collections import Counter
        word_freq = Counter(words)
        
        # Filter out common words
        stopwords = {"a", "the", "is", "on", "in", "of", "and", "or", "map", "data", "layer"}
        pattern["keywords"] = [
            w for w, _ in word_freq.most_common(5)
            if w not in stopwords
        ]
        
        # Get learned operations and data sources
        if "operations" in self.learned_patterns and map_type in self.learned_patterns["operations"]:
            pattern["common_operations"] = list(
                self.learned_patterns["operations"][map_type].keys()
            )[:3]
        
        if "data_sources" in self.learned_patterns and map_type in self.learned_patterns["data_sources"]:
            pattern["data_sources"] = list(
                self.learned_patterns["data_sources"][map_type].keys()
            )[:3]
        
        return pattern
    
    def improve_detection(
        self,
        description: str
    ) -> Tuple[str, float]:
        """
        Use learned patterns to improve map type detection.
        
        Returns (predicted_map_type, confidence)
        """
        best_match = None
        best_score = 0.0
        
        # Try to match against learned patterns
        if "keywords" in self.learned_patterns:
            keywords_by_type = self.learned_patterns.get("keywords", {})
            
            desc_lower = description.lower()
            
            for map_type, keywords in keywords_by_type.items():
                # Score based on keyword matches
                matches = sum(1 for kw in keywords if kw in desc_lower)
                score = matches / len(keywords) if keywords else 0
                
                if score > best_score:
                    best_score = score
                    best_match = map_type
        
        return (best_match or "generic", best_score)
    
    def _learn_from_misclassification(
        self,
        description: str,
        correct_type: str
    ) -> None:
        """Learn keywords/patterns from misclassified examples."""
        if "keywords" not in self.learned_patterns:
            self.learned_patterns["keywords"] = {}
        
        if correct_type not in self.learned_patterns["keywords"]:
            self.learned_patterns["keywords"][correct_type] = []
        
        # Extract keywords from description
        words = re.findall(r"\b\w{3,}\b", description.lower())
        
        # Keep unique keywords
        existing = set(self.learned_patterns["keywords"][correct_type])
        new_keywords = list(set(words) - existing)
        
        self.learned_patterns["keywords"][correct_type].extend(new_keywords[:5])
        
        self._save_patterns()
    
    def _learn_from_positive_feedback(
        self,
        description: str,
        map_type: str
    ) -> None:
        """Reinforce learning from positive user feedback."""
        if "keywords" not in self.learned_patterns:
            self.learned_patterns["keywords"] = {}
        
        if map_type not in self.learned_patterns["keywords"]:
            self.learned_patterns["keywords"][map_type] = []
        
        # Extract all keywords and boost them
        words = re.findall(r"\b\w{3,}\b", description.lower())
        
        # Weight frequently appearing keywords higher
        for word in words:
            if word in self.learned_patterns["keywords"][map_type]:
                # Move to front (implicit boost)
                self.learned_patterns["keywords"][map_type].remove(word)
                self.learned_patterns["keywords"][map_type].insert(0, word)
        
        self._save_patterns()
    
    def _load_patterns(self) -> Dict[str, Any]:
        """Load learned patterns from disk."""
        if os.path.exists(self.patterns_file):
            try:
                with open(self.patterns_file, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        
        return {
            "keywords": {},
            "operations": {},
            "data_sources": {},
            "parameters": {},
        }
    
    def _save_patterns(self) -> None:
        """Save learned patterns to disk."""
        with open(self.patterns_file, "w") as f:
            json.dump(self.learned_patterns, f, indent=2)
    
    def _read_feedback_log(self) -> List[Dict[str, Any]]:
        """Read all feedback from log."""
        feedback = []
        
        if os.path.exists(self.feedback_log):
            with open(self.feedback_log, "r") as f:
                for line in f:
                    try:
                        feedback.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        
        return feedback
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """Get statistics about what the system has learned."""
        feedback_list = self._read_feedback_log()
        
        correct = sum(1 for f in feedback_list if f.get("correct"))
        total = len(feedback_list)
        
        accuracy = correct / total if total > 0 else 0
        
        return {
            "total_feedback": total,
            "correct_predictions": correct,
            "accuracy": accuracy,
            "learned_map_types": list(self.learned_patterns.get("keywords", {}).keys()),
            "unique_operations": len(self.learned_patterns.get("operations", {})),
            "unique_data_sources": len(self.learned_patterns.get("data_sources", {})),
        }


# Global learner instance
_learner_instance: Optional[FeedbackLearner] = None


def get_learner() -> FeedbackLearner:
    """Get or create global feedback learner instance."""
    global _learner_instance
    if _learner_instance is None:
        _learner_instance = FeedbackLearner()
    return _learner_instance


def record_feedback(
    description: str,
    detected: str,
    actual: str,
    rating: int = 0
) -> None:
    """Convenience function to record feedback."""
    get_learner().record_user_feedback(description, detected, actual, rating)
