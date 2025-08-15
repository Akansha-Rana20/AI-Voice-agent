from dotenv import load_dotenv
load_dotenv()  # This loads environment variables from a .env file in your project root

import os
import shutil
import logging

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.schemas import ChatRequestResponse, ChatMessage, LLMQueryResponse
from app.services import stt, llm, tts

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="AI Voice Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory chat session store
chat_sessions = {}

FALLBACK_TEXT = "I'm having trouble connecting right now, please try again."


@app.post("/agent/chat/{session_id}", response_model=ChatRequestResponse)
async def agent_chat(session_id: str, file: UploadFile = File(...)):
    if session_id not in chat_sessions:
        chat_sessions[session_id] = []

    # Save audio temporarily
    temp_file_path = f"temp_{file.filename}"
    audio_bytes = await file.read()
    with open(temp_file_path, "wb") as f:
        f.write(audio_bytes)

    try:
        # STT
        user_text = stt.STTService.transcribe_audio(temp_file_path)
    except Exception as e:
        logger.error(f"STT failure: {e}")
        return await generate_fallback(session_id, "[STT failed]")

    chat_sessions[session_id].append(ChatMessage(role="user", content=user_text))

    # Build conversation prompt
    conversation_prompt = "\n".join([f"{m.role.capitalize()}: {m.content}" for m in chat_sessions[session_id]])

    try:
        # LLM
        assistant_text = llm.LLMService.generate_response(conversation_prompt)
    except Exception as e:
        logger.error(f"LLM failure: {e}")
        return await generate_fallback(session_id, user_text)

    chat_sessions[session_id].append(ChatMessage(role="assistant", content=assistant_text))

    try:
        # TTS
        audio_url = tts.TTSService.generate_speech(assistant_text)
    except Exception as e:
        logger.error(f"TTS failure: {e}")
        return await generate_fallback(session_id, user_text)

    # Clean up temp file
    os.remove(temp_file_path)

    return ChatRequestResponse(
        audio_url=audio_url,
        transcript=user_text,
        llm_response=assistant_text,
        history=chat_sessions[session_id]
    )


@app.post("/llm/query", response_model=LLMQueryResponse)
async def llm_query(file: UploadFile = File(...)):
    temp_file_path = f"temp_{file.filename}"
    audio_bytes = await file.read()
    with open(temp_file_path, "wb") as f:
        f.write(audio_bytes)

    try:
        prompt = stt.STTService.transcribe_audio(temp_file_path)
    except Exception as e:
        logger.error(f"STT failure: {e}")
        audio_url = tts.TTSService.generate_speech(FALLBACK_TEXT)
        return LLMQueryResponse(audio_url=audio_url, transcript="[STT failed]", llm_response=FALLBACK_TEXT)

    try:
        reply = llm.LLMService.generate_response(prompt)
    except Exception as e:
        logger.error(f"LLM failure: {e}")
        audio_url = tts.TTSService.generate_speech(FALLBACK_TEXT)
        return LLMQueryResponse(audio_url=audio_url, transcript=prompt, llm_response=FALLBACK_TEXT)

    try:
        audio_url = tts.TTSService.generate_speech(reply)
    except Exception as e:
        logger.error(f"TTS failure: {e}")
        audio_url = tts.TTSService.generate_speech(FALLBACK_TEXT)
        reply = FALLBACK_TEXT

    os.remove(temp_file_path)

    return LLMQueryResponse(audio_url=audio_url, transcript=prompt, llm_response=reply)


async def generate_fallback(session_id: str, user_text: str):
    logger.warning(f"Generating fallback for session {session_id}")
    try:
        audio_url = tts.TTSService.generate_speech(FALLBACK_TEXT)
    except Exception as e:
        logger.error(f"Fallback TTS failure: {e}")
        audio_url = ""

    return JSONResponse(content={
        "audio_url": audio_url,
        "transcript": user_text,
        "llm_response": FALLBACK_TEXT,
        "history": chat_sessions.get(session_id, [])
    })
