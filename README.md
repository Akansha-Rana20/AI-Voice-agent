# 🎙️ AI Conversational Voice Agent

An intelligent **voice-first** chatbot that can:

- Listen to your voice,
- Understand your question (via Speech-to-Text),
- Generate a context-aware answer using an LLM,
- Speak it back in a natural voice.

This project was built as part of **30 Days of AI Voice Agents Challenge (Murf AI)**.

---

## 🚀 About the Project

This voice agent is capable of **multi-turn conversation** with **chat history memory**, making interactions feel natural and human-like.

**Core Flow:**
1. User clicks the 🎤 button and speaks a question.
2. Audio is sent to the backend.
3. Backend transcribes using **AssemblyAI**.
4. Conversation history + new query sent to **Google Gemini** LLM.
5. AI response converted to speech with **Murf AI Text-to-Speech**.
6. Audio reply auto-plays, and the agent listens again for the next message.

---

## 🛠️ Tech Stack

**Frontend**
- HTML, CSS, JavaScript
- MediaRecorder API (for recording audio from browser)

**Backend**
- Python 3.10+
- **FastAPI** (API server)
- **AssemblyAI SDK** (Speech-to-Text)
- **Google Generative AI** (`google-generativeai`)
- **Murf AI REST API** (Text-to-Speech)
- `requests`, `pydantic`

---

<details> <summary>Mermaid Diagram Code</summary>
## 🏛️ Architecture
flowchart TD
A[🎤 User Voice] -->|Audio/webm| B[Frontend Recorder: HTML+JS]
B -->|POST /agent/chat/{session_id}| C[FastAPI Backend]
C --> D[AssemblyAI: Speech-to-Text]
D --> E[Combine with Chat History]
E --> F[Google Gemini: Context-Aware Response]
F --> G[Murf AI: Text-to-Speech]
G -->|Audio URL| H[Frontend Playback + Display Response]
H -->|Auto Restart| A
undefined
</details>



- Backend uses an **in-memory dictionary** to store chat history per session.
- `session_id` passed in the query string ensures *conversation memory*.
- Fallback voice ("I'm having trouble connecting right now") plays if any API fails.

---

## ✨ Features

- 🎤 **Single Toggle Record Button** with animated recording state
- 💬 **Multi-Turn Chat History**
- 🗣 **Natural AI Voice Responses** via Murf AI
- 🛡 **Error Handling & Fallback Audio**
- 🖥 **Clean, Responsive UI**
- 🔁 **Automatic re-record after reply playback** for smooth conversation

---

## ⚙️ Setup Instructions

### 1️⃣ Clone the Repository
git clone https://github.com/yourusername/ai-voice-agent.git
cd ai-voice-agent


### 2️⃣ Create a Virtual Environment
python -m venv venv
venv\Scripts\activate # Windows


### 3️⃣ Install Dependencies
pip install -r requirements.txt


### 4️⃣ Set Environment Variables
Create a `.env` file in the root directory:
ASSEMBLYAI_API_KEY=your_assemblyai_key
GEMINI_API_KEY=your_gemini_key
MURF_API_KEY=your_murf_key
MURF_BASE_URL=https://api.murf.ai


*(You can also export these directly in your shell environment.)*

### 5️⃣ Run the Backend Server
uvicorn main:app --reload --host 0.0.0.0 --port 8000


### 6️⃣ Open the Frontend
- Open `index.html` in your browser.
- Make sure the backend is running on `http://localhost:8000`.

---

## 📷 Screenshot
### Updated Conversational UI
![Conversational Agent UI](screenshots/ui.png)


---

## 📡 API Endpoints

- `POST /agent/chat/{session_id}` → Conversational bot with memory (audio input → audio+text output)
- `POST /llm/query` → Single-turn Q&A without memory
- `POST /transcribe/file` → Audio → text
- `POST /generate-speech` → Text → audio (via Murf)
- `GET /voices` → List available Murf voices


---

## 💡 Acknowledgments
- [AssemblyAI](https://www.assemblyai.com/) for Speech-to-Text
- [Google Gemini](https://ai.google/) for LLM
- [Murf AI](https://murf.ai) for Text-to-Speech

