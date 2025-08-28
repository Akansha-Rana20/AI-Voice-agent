# services/agent.py
from app.services.llm import get_llm_response
from app.services.search import web_search

def agent_response(user_query, history):
    search_triggers = ["latest", "today", "price", "weather", "news", "update", "current"]

    if any(word in user_query.lower() for word in search_triggers):
        return web_search(user_query), history
    else:
        return get_llm_response(user_query, history)
