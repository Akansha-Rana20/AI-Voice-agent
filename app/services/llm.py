import google.generativeai as genai
import os
import logging

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

logger = logging.getLogger(__name__)

class LLMService:
    @staticmethod
    def generate_response(prompt: str) -> str:
        logger.info("Generating LLM response via Google Gemini")
        model = genai.GenerativeModel("gemini-2.5-flash")
        response = model.generate_content(prompt)

        if not response.text:
            logger.warning("No text returned by LLM, using fallback")
            return "[No response]"
        return response.text
