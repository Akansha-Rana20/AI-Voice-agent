# Fixed services/llm.py with proper async/await handling
import google.generativeai as genai
from typing import List, Dict, Any, Tuple, Optional
import logging
import asyncio
import time
import os

# Import persona
from app.persona import merged_persona

logger = logging.getLogger(__name__)

# Cache for configured clients
_client_cache = {}
_cache_timeout = 3600


def get_llm_response(user_query: str, history: List[Dict[str, Any]], api_key: str = None) -> Tuple[
    str, List[Dict[str, Any]]]:
    """
    Enhanced LLM response with dynamic API key support.
    """
    # Use provided API key or fall back to environment
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return "Please configure your Gemini API key in the settings.", history

    try:
        # Configure the API key
        genai.configure(api_key=api_key)

        # Create model with system instructions
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            system_instruction=merged_persona
        )

        # Generate response with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                chat = model.start_chat(history=history)
                response = chat.send_message(user_query)

                if response.text and response.text.strip():
                    logger.info(f"LLM response generated successfully (attempt {attempt + 1})")
                    return response.text.strip(), chat.history
                else:
                    raise ValueError("Empty response from model")

            except Exception as e:
                logger.warning(f"LLM attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(1)  # Brief delay before retry

    except Exception as e:
        logger.error(f"Error getting LLM response: {e}")

        # Provide contextual error messages
        error_str = str(e).upper()
        if "API_KEY" in error_str or "INVALID" in error_str:
            error_msg = "Invalid Gemini API key. Please check your configuration."
        elif "QUOTA" in error_str or "LIMIT" in error_str:
            error_msg = "API quota exceeded. Please check your Gemini API usage limits."
        elif "NETWORK" in error_str or "CONNECTION" in error_str:
            error_msg = "Network connectivity issue. Please check your internet connection."
        else:
            error_msg = "I'm experiencing technical difficulties. Please try again in a moment."

        return error_msg, history


async def get_llm_response_async(user_query: str, history: List[Dict[str, Any]], api_key: str = None) -> Tuple[
    str, List[Dict[str, Any]]]:
    """Async wrapper for LLM response."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_llm_response, user_query, history, api_key)


def validate_gemini_api_key(api_key: str) -> Tuple[bool, str]:
    """Validate Gemini API key."""
    if not api_key or not api_key.strip():
        return False, "API key is empty"

    if not api_key.startswith("AIza"):
        return False, "Invalid API key format"

    try:
        # Test the API key
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        # Send a minimal test message
        test_response = model.generate_content("Hello", stream=False)

        if test_response and test_response.text:
            return True, "API key is valid"
        else:
            return False, "API key test failed"

    except Exception as e:
        logger.warning(f"API key validation failed: {e}")
        error_msg = str(e)
        if "API_KEY" in error_msg.upper():
            return False, "Invalid API key"
        elif "QUOTA" in error_msg.upper():
            return False, "API quota exceeded"
        else:
            return False, f"Validation error: {str(e)}"


class EnhancedLLMService:
    """Enhanced LLM service class for advanced features."""

    @staticmethod
    def get_model_info(api_key: str) -> Dict[str, Any]:
        """Get available models information."""
        try:
            genai.configure(api_key=api_key)
            models = genai.list_models()

            model_list = []
            for model in models:
                if 'gemini' in model.name.lower():
                    model_info = {
                        "name": model.name,
                        "display_name": getattr(model, 'display_name', model.name),
                        "description": getattr(model, 'description', ''),
                        "input_token_limit": getattr(model, 'input_token_limit', 0),
                        "output_token_limit": getattr(model, 'output_token_limit', 0)
                    }
                    model_list.append(model_info)

            return {"available_models": model_list}

        except Exception as e:
            logger.error(f"Error getting model info: {e}")
            return {"error": str(e)}

    @staticmethod
    def generate_streaming_response(user_query: str, history: List[Dict[str, Any]], api_key: str):
        """Generate streaming response (generator function)."""
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=merged_persona)

            chat = model.start_chat(history=history)
            response = chat.send_message(user_query, stream=True)

            for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            logger.error(f"Streaming response error: {e}")
            yield f"Error: {str(e)}"

    @staticmethod
    def get_token_count(text: str, api_key: str) -> int:
        """Get approximate token count for text."""
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-1.5-flash')
            count_result = model.count_tokens(text)
            return count_result.total_tokens
        except Exception as e:
            logger.warning(f"Token count error: {e}")
            # Approximate: 1 token ≈ 4 characters
            return len(text) // 4


# Helper functions for backward compatibility
def test_api_connection(api_key: str) -> bool:
    """Test API connection."""
    is_valid, _ = validate_gemini_api_key(api_key)
    return is_valid


def get_available_models(api_key: str) -> List[str]:
    """Get list of available model names."""
    try:
        model_info = EnhancedLLMService.get_model_info(api_key)
        if "available_models" in model_info:
            return [model["name"] for model in model_info["available_models"]]
        return []
    except Exception:
        return ["gemini-1.5-flash", "gemini-1.5-pro"]  # Default fallback