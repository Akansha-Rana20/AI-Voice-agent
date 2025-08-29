# Fixed services/agent.py with proper imports
import logging
from typing import List, Dict, Any, Tuple
import re
import os

from app.services.llm import get_llm_response

logger = logging.getLogger(__name__)


async def agent_response(user_query, history, api_keys: Dict[str, str] = None):
    """
    Enhanced agent response with intelligent routing.
    """
    if api_keys is None:
        api_keys = {}

    # Simple search trigger detection
    search_triggers = [
        "latest", "today", "yesterday", "current", "now", "recent",
        "price", "cost", "stock", "market", "news", "weather",
        "2024", "2025", "this year", "last year"
    ]

    query_lower = user_query.lower()
    needs_search = any(trigger in query_lower for trigger in search_triggers)

    if needs_search:
        # Try web search first
        try:
            search_result = web_search(user_query, api_keys.get("serpapi"))
            if search_result and "couldn't find" not in search_result:
                # Enhance the query with search results
                enhanced_query = f"""
Based on this current information: {search_result}

Please answer the user's question: {user_query}

Provide a comprehensive response that incorporates the search results with your knowledge.
"""
                return get_llm_response(
                    enhanced_query,
                    history,
                    api_keys.get("gemini")
                )
        except Exception as e:
            logger.warning(f"Search failed, using LLM only: {e}")

    # Use LLM for general questions
    return get_llm_response(user_query, history, api_keys.get("gemini"))


def web_search(query: str, api_key: str = None) -> str:
    """
    Perform web search using SerpAPI.
    """
    if not api_key:
        api_key = os.getenv("SERPAPI_KEY")

    if not api_key:
        return "Web search is not available. Please configure SerpAPI key."

    try:
        from serpapi import GoogleSearch

        params = {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "num": 3
        }

        search = GoogleSearch(params)
        results = search.get_dict()

        if "error" in results:
            logger.error(f"Search API error: {results['error']}")
            return "Search service encountered an error."

        if "organic_results" in results and results["organic_results"]:
            # Format the top results
            formatted_results = []
            for i, result in enumerate(results["organic_results"][:2]):
                title = result.get("title", "No title")
                snippet = result.get("snippet", "No description")
                link = result.get("link", "#")

                formatted_result = f"{title}: {snippet} (Source: {link})"
                formatted_results.append(formatted_result)

            return " | ".join(formatted_results)
        else:
            return "I couldn't find any reliable information right now."

    except ImportError:
        logger.error("SerpAPI library not installed")
        return "Search functionality requires the serpapi package."
    except Exception as e:
        logger.error(f"Search error: {e}")
        return "Search service is currently unavailable."


def analyze_query_intent(query: str) -> Dict[str, Any]:
    """
    Analyze query to determine intent and need for search.
    """
    query_lower = query.lower()

    # Define intent patterns
    intent_patterns = {
        'current_info': [
            r'\b(today|now|current|latest|recent)\b',
            r'\b(what\'s|whats) (happening|new)\b',
            r'\b(this (year|month|week))\b'
        ],
        'financial': [
            r'\b(price|cost|stock|market|trading)\b',
            r'\b(USD|EUR|bitcoin|crypto)\b'
        ],
        'weather': [
            r'\b(weather|temperature|rain|snow)\b'
        ],
        'news': [
            r'\b(news|breaking|headline|announced)\b'
        ],
        'factual': [
            r'\b(what is|who is|where is|when is|how)\b',
            r'\b(define|explain|meaning)\b'
        ]
    }

    detected_intents = {}

    for intent, patterns in intent_patterns.items():
        score = 0
        for pattern in patterns:
            matches = re.findall(pattern, query_lower)
            score += len(matches)

        if score > 0:
            detected_intents[intent] = score

    # Determine if search is needed
    search_intents = ['current_info', 'financial', 'weather', 'news']
    needs_search = any(intent in detected_intents for intent in search_intents)

    return {
        'intents': detected_intents,
        'needs_search': needs_search,
        'primary_intent': max(detected_intents, key=detected_intents.get) if detected_intents else 'general'
    }


def validate_api_keys(api_keys: Dict[str, str]) -> Dict[str, bool]:
    """
    Validate provided API keys.
    """
    results = {}

    # Validate Gemini API key
    if api_keys.get('gemini'):
        try:
            from app.services.llm import validate_gemini_api_key
            is_valid, _ = validate_gemini_api_key(api_keys['gemini'])
            results['gemini'] = is_valid
        except Exception as e:
            logger.error(f"Gemini validation error: {e}")
            results['gemini'] = False
    else:
        results['gemini'] = False

    # Validate AssemblyAI API key (simple check)
    assembly_key = api_keys.get('assembly')
    if assembly_key:
        results['assembly'] = len(assembly_key) > 10 and assembly_key.isalnum()
    else:
        results['assembly'] = False

    # Validate Murf API key (simple check)
    murf_key = api_keys.get('murf')
    if murf_key:
        results['murf'] = len(murf_key) > 10
    else:
        results['murf'] = False

    # Validate SerpAPI key
    if api_keys.get('serpapi'):
        try:
            # Test with a simple search
            from serpapi import GoogleSearch
            search = GoogleSearch({
                "q": "test",
                "api_key": api_keys['serpapi'],
                "num": 1
            })
            test_results = search.get_dict()
            results['serpapi'] = 'error' not in test_results
        except Exception as e:
            logger.error(f"SerpAPI validation error: {e}")
            results['serpapi'] = False
    else:
        results['serpapi'] = False

    return results


# Enhanced query processing
def enhance_query_with_context(query: str, context: str = "") -> str:
    """
    Enhance query with additional context.
    """
    if not context:
        return query

    enhanced = f"""
Previous context:
{context}

Current question: {query}

Please answer considering both the context and current question.
"""
    return enhanced.strip()


def extract_search_keywords(query: str) -> List[str]:
    """
    Extract key search terms from query.
    """
    # Remove common words
    stop_words = {
        'what', 'is', 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on',
        'at', 'to', 'for', 'of', 'with', 'by', 'how', 'when', 'where', 'why'
    }

    # Extract words
    words = re.findall(r'\b\w+\b', query.lower())
    keywords = [word for word in words if word not in stop_words and len(word) > 2]

    return keywords[:5]  # Return top 5 keywords


def format_response_with_sources(response: str, sources: List[str]) -> str:
    """
    Format response with source attribution.
    """
    if not sources:
        return response

    formatted_sources = []
    for i, source in enumerate(sources[:3], 1):
        formatted_sources.append(f"{i}. {source}")

    return f"{response}\n\nSources:\n" + "\n".join(formatted_sources)