# Fixed services/llm.py - Compatible with older Google Generative AI versions
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
    Enhanced LLM response with version compatibility for Google Generative AI.
    """
    # Use provided API key or fall back to environment
    if not api_key:
        api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        return "Please configure your Gemini API key in the settings.", history

    try:
        # Configure the API key
        genai.configure(api_key=api_key)

        # Create model with version compatibility check
        try:
            # Try new version with system_instruction (v0.4.0+)
            model = genai.GenerativeModel(
                'gemini-1.5-flash',
                system_instruction=merged_persona
            )
            logger.debug("Using GenerativeModel with system_instruction parameter")
        except TypeError as e:
            if "system_instruction" in str(e):
                # Fallback for older versions (v0.3.x)
                model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("Using GenerativeModel without system_instruction (older version)")

                # Prepend system instruction to the user query as a workaround
                enhanced_query = f"""You are TechTutor Buddy, my personal AI assistant who combines:
- the friendliness of a personal assistant,
- the clarity of a patient tutor, 
- and the enthusiasm of a tech geek.

Keep replies brief, clear, and natural to speak. Always stay under 1500 characters.
Answer directly — avoid filler or repetition. Stay in role as TechTutor Buddy.

User question: {user_query}"""
                user_query = enhanced_query
            else:
                raise e

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
        elif "SYSTEM_INSTRUCTION" in error_str:
            error_msg = "Using older Gemini API version. System instructions will be included in messages."
        else:
            error_msg = "I'm experiencing technical difficulties. Please try again in a moment."

        return error_msg, history


async def get_llm_response_async(user_query: str, history: List[Dict[str, Any]], api_key: str = None) -> Tuple[
    str, List[Dict[str, Any]]]:
    """Async wrapper for LLM response."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, get_llm_response, user_query, history, api_key)


def validate_gemini_api_key(api_key: str) -> Tuple[bool, str]:
    """Validate Gemini API key with version compatibility."""
    if not api_key or not api_key.strip():
        return False, "API key is empty"

    if not api_key.startswith("AIza"):
        return False, "Invalid API key format"

    try:
        # Test the API key
        genai.configure(api_key=api_key)

        # Try with different model initialization approaches
        try:
            model = genai.GenerativeModel('gemini-1.5-flash')
        except Exception:
            # Fallback to older model name if needed
            try:
                model = genai.GenerativeModel('gemini-pro')
            except Exception as model_err:
                return False, f"Model initialization failed: {str(model_err)}"

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


def get_available_models(api_key: str) -> List[str]:
    """Get available models with fallback for different API versions."""
    try:
        genai.configure(api_key=api_key)
        models = genai.list_models()

        model_names = []
        for model in models:
            if 'gemini' in model.name.lower():
                model_names.append(model.name)

        return model_names if model_names else ["gemini-1.5-flash", "gemini-pro"]

    except Exception as e:
        logger.error(f"Error getting models: {e}")
        # Return common model names as fallback
        return ["gemini-1.5-flash", "gemini-pro", "gemini-1.5-pro"]


def get_api_version() -> str:
    """Get the current Google Generative AI library version."""
    try:
        import google.generativeai
        version = getattr(google.generativeai, '__version__', 'unknown')
        return version
    except Exception:
        return 'unknown'


class EnhancedLLMService:
    """Enhanced LLM service class with version compatibility."""

    @staticmethod
    def get_model_info(api_key: str) -> Dict[str, Any]:
        """Get available models information with version compatibility."""
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
                        "version": getattr(model, 'version', ''),
                        "input_token_limit": getattr(model, 'input_token_limit', 0),
                        "output_token_limit": getattr(model, 'output_token_limit', 0)
                    }
                    model_list.append(model_info)

            return {
                "available_models": model_list,
                "api_version": get_api_version(),
                "system_instruction_support": EnhancedLLMService.check_system_instruction_support(api_key)
            }

        except Exception as e:
            logger.error(f"Error getting model info: {e}")
            return {"error": str(e)}

    @staticmethod
    def check_system_instruction_support(api_key: str) -> bool:
        """Check if the current API version supports system_instruction."""
        try:
            genai.configure(api_key=api_key)

            # Try to create a model with system_instruction
            test_model = genai.GenerativeModel(
                'gemini-1.5-flash',
                system_instruction="Test"
            )
            return True

        except TypeError as e:
            if "system_instruction" in str(e):
                return False
            return True  # Other errors don't indicate lack of support
        except Exception:
            return False

    @staticmethod
    def generate_streaming_response(user_query: str, history: List[Dict[str, Any]], api_key: str):
        """Generate streaming response with version compatibility."""
        try:
            genai.configure(api_key=api_key)

            # Try with system instruction first
            try:
                model = genai.GenerativeModel('gemini-1.5-flash', system_instruction=merged_persona)
            except TypeError as e:
                if "system_instruction" in str(e):
                    # Fallback for older versions
                    model = genai.GenerativeModel('gemini-1.5-flash')
                    # Prepend system instruction to query
                    user_query = f"System: {merged_persona}\n\nUser: {user_query}"
                else:
                    raise e

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


def get_service_info() -> Dict[str, Any]:
    """Get service information including version compatibility."""
    return {
        "service": "Google Generative AI",
        "version": get_api_version(),
        "system_instruction_support": "unknown",  # Will be checked when API key is provided
        "available_models": ["gemini-1.5-flash", "gemini-pro"],
        "compatibility_mode": "auto-detect"
    }


# Version-specific configuration
def configure_for_version(api_key: str) -> Dict[str, Any]:
    """Configure service based on detected API version."""
    version = get_api_version()
    system_support = EnhancedLLMService.check_system_instruction_support(api_key) if api_key else False

    config = {
        "version": version,
        "system_instruction_support": system_support,
        "recommended_model": "gemini-1.5-flash",
        "fallback_model": "gemini-pro"
    }

    logger.info(f"Configured for Google Generative AI v{version}, system_instruction: {system_support}")
    return config