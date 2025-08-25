//// static/script.js
//document.addEventListener("DOMContentLoaded", () => {
//    const recordBtn = document.getElementById("recordBtn");
//    const statusDisplay = document.getElementById("statusDisplay");
//    const chatLog = document.getElementById('chat-log');
//
//    let isRecording = false;
//    let ws = null;
//    let audioContext;
//    let mediaStream;
//    let processor;
//    let audioQueue = [];
//    let isPlaying = false;
//    let assistantMessageDiv = null;
//
//    const addOrUpdateMessage = (text, type) => {
//        if (type === "assistant") {
//            // Reuse the same div while assistant is streaming
//            if (!assistantMessageDiv) {
//                assistantMessageDiv = document.createElement('div');
//                assistantMessageDiv.className = 'message assistant';
//                assistantMessageDiv.textContent = "";
//                chatLog.appendChild(assistantMessageDiv);
//            }
//            assistantMessageDiv.textContent += text;
//        } else {
//            assistantMessageDiv = null; // Reset for next assistant reply
//            const messageDiv = document.createElement('div');
//            messageDiv.className = 'message user';
//            messageDiv.textContent = text;
//            chatLog.appendChild(messageDiv);
//        }
//        chatLog.scrollTop = chatLog.scrollHeight;
//    };
//
//    const playNextInQueue = () => {
//        if (audioQueue.length > 0) {
//            isPlaying = true;
//            const base64Audio = audioQueue.shift();
//            const audioData = Uint8Array.from(atob(base64Audio), c => c.charCodeAt(0)).buffer;
//
//            audioContext.decodeAudioData(audioData).then(buffer => {
//                const source = audioContext.createBufferSource();
//                source.buffer = buffer;
//                source.connect(audioContext.destination);
//                source.onended = playNextInQueue;
//                source.start();
//            }).catch(e => {
//                console.warn("Audio decode failed (maybe raw PCM):", e);
//                playNextInQueue();
//            });
//        } else {
//            isPlaying = false;
//        }
//    };
//
//    const startRecording = async () => {
//        try {
//            mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
//            audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
//
//            const source = audioContext.createMediaStreamSource(mediaStream);
//            processor = audioContext.createScriptProcessor(4096, 1, 1);
//            source.connect(processor);
//            processor.connect(audioContext.destination);
//            processor.onaudioprocess = (e) => {
//                const inputData = e.inputBuffer.getChannelData(0);
//                const pcmData = new Int16Array(inputData.length);
//                for (let i = 0; i < inputData.length; i++) {
//                    pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 32767;
//                }
//                if (ws && ws.readyState === WebSocket.OPEN) {
//                    ws.send(pcmData); // send directly as Int16Array
//                }
//            };
//
//            const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
//            ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);
//
//            ws.onopen = () => {
//                console.log("✅ WebSocket connected");
//            };
//
//            ws.onmessage = (event) => {
//                const msg = JSON.parse(event.data);
//                if (msg.type === "assistant") {
//                    addOrUpdateMessage(msg.text, "assistant");
//                } else if (msg.type === "final") {
//                    addOrUpdateMessage(msg.text, "user");
//                } else if (msg.type === "audio") {
//                    audioQueue.push(msg.b64);
//                    if (!isPlaying) playNextInQueue();
//                }
//            };
//
//            ws.onerror = (err) => {
//                console.error("❌ WebSocket error:", err);
//            };
//
//            ws.onclose = (e) => {
//                console.warn("⚠️ WebSocket closed:", e.code, e.reason);
//            };
//
//            isRecording = true;
//            recordBtn.classList.add("recording");
//            statusDisplay.textContent = "Listening...";
//        } catch (error) {
//            console.error("Could not start recording:", error);
//            alert("Microphone access is required to use the voice agent.");
//        }
//    };
//
//    const stopRecording = () => {
//        if (processor) processor.disconnect();
//        if (mediaStream) mediaStream.getTracks().forEach(track => track.stop());
//        if (ws) ws.close();
//
//        isRecording = false;
//        recordBtn.classList.remove("recording");
//        statusDisplay.textContent = "Ready to chat!";
//    };
//
//    recordBtn.addEventListener("click", () => {
//        if (isRecording) {
//            stopRecording();
//        } else {
//            startRecording();
//        }
//    });
//});


const socket = new WebSocket("ws://localhost:8000/ws");
const micBtn = document.getElementById("micBtn");
const chatBox = document.getElementById("chatBox");

function addMessage(text, sender) {
  const msg = document.createElement("div");
  msg.classList.add("message", sender);
  msg.textContent = text;
  chatBox.appendChild(msg);
  chatBox.scrollTop = chatBox.scrollHeight;
}

// ✅ Handle WebSocket events
socket.onopen = () => {
  console.log("✅ WebSocket connected");
};

socket.onmessage = (event) => {
  const data = JSON.parse(event.data);

  if (data.type === "transcription") {
    addMessage("You: " + data.text, "user");
  }

  if (data.type === "response") {
    addMessage("🤖 " + data.text, "agent");
  }
};

socket.onclose = () => {
  console.log("⚠️ WebSocket closed");
};

// 🎤 Handle mic button click
micBtn.addEventListener("click", () => {
  micBtn.classList.toggle("active");

  if (micBtn.classList.contains("active")) {
    addMessage("🎙️ Listening...", "agent");
    // Send "start recording" signal to backend
    socket.send(JSON.stringify({ action: "start" }));
  } else {
    addMessage("✅ Recording stopped", "agent");
    // Send "stop recording" signal to backend
    socket.send(JSON.stringify({ action: "stop" }));
  }
});

