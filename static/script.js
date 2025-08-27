// Enhanced script with all original functionality preserved
        document.addEventListener("DOMContentLoaded", () => {
            const recordBtn = document.getElementById("recordBtn");
            const recordIcon = document.getElementById("recordIcon");
            const statusDisplay = document.getElementById("statusDisplay");
            const chatLog = document.getElementById('chat-log');
            const waveform = document.getElementById("waveform");
            const typingIndicator = document.getElementById("typingIndicator");
            const connectionStatus = document.getElementById("connectionStatus");
            const connectionText = document.getElementById("connectionText");

            // Control buttons
            const clearBtn = document.getElementById("clearBtn");
            const volumeBtn = document.getElementById("volumeBtn");
            const helpBtn = document.getElementById("helpBtn");

            let isRecording = false;
            let ws = null;
            let audioContext;
            let mediaStream;
            let processor;
            let audioQueue = [];
            let isPlaying = false;
            let assistantMessageDiv = null;
            let audioEnabled = true;

            // Enhanced message handling with better animations
            const addOrUpdateMessage = (text, type) => {
                if (type === "assistant") {
                    // Hide typing indicator when assistant starts responding
                    hideTypingIndicator();

                    if (!assistantMessageDiv) {
                        assistantMessageDiv = document.createElement('div');
                        assistantMessageDiv.className = 'message assistant';
                        assistantMessageDiv.innerHTML = '<i class="fas fa-robot" style="margin-right: 8px; color: #4facfe;"></i>';
                        chatLog.appendChild(assistantMessageDiv);
                    }

                    // Detect mermaid code block
                    const mermaidRegex = /```mermaid([\s\S]*?)```/g;
                    const matches = [...text.matchAll(mermaidRegex)];

                    if (matches.length > 0) {
                        assistantMessageDiv.innerHTML = '<i class="fas fa-robot" style="margin-right: 8px; color: #4facfe;"></i>';
                        matches.forEach(match => {
                            const diagram = document.createElement('div');
                            diagram.className = "mermaid";
                            diagram.textContent = match[1].trim();
                            assistantMessageDiv.appendChild(diagram);
                        });

                        // Render diagrams
                        if (window.mermaid) {
                            mermaid.init(undefined, assistantMessageDiv.querySelectorAll('.mermaid'));
                        }
                    } else {
                        // For streaming text, preserve the robot icon
                        const currentText = assistantMessageDiv.textContent.replace('🤖', '').trim();
                        assistantMessageDiv.innerHTML = '<i class="fas fa-robot" style="margin-right: 8px; color: #4facfe;"></i>' + currentText + text;
                    }
                } else {
                    // User message
                    assistantMessageDiv = null;
                    const messageDiv = document.createElement('div');
                    messageDiv.className = 'message user';
                    messageDiv.innerHTML = '<i class="fas fa-user" style="margin-right: 8px;"></i>' + text;
                    chatLog.appendChild(messageDiv);
                }
                chatLog.scrollTop = chatLog.scrollHeight;
            };

            // Enhanced audio playback
            const playNextInQueue = () => {
                if (audioQueue.length > 0 && audioEnabled) {
                    isPlaying = true;
                    const base64Audio = audioQueue.shift();
                    const audioData = Uint8Array.from(atob(base64Audio), c => c.charCodeAt(0)).buffer;

                    audioContext.decodeAudioData(audioData).then(buffer => {
                        const source = audioContext.createBufferSource();
                        source.buffer = buffer;
                        source.connect(audioContext.destination);
                        source.onended = playNextInQueue;
                        source.start();
                    }).catch(e => {
                        console.warn("Audio decode failed (maybe raw PCM):", e);
                        playNextInQueue();
                    });
                } else {
                    isPlaying = false;
                }
            };

            // Enhanced UI functions
            const showTypingIndicator = () => {
                typingIndicator.classList.add("active");
                chatLog.scrollTop = chatLog.scrollHeight;
            };

            const hideTypingIndicator = () => {
                typingIndicator.classList.remove("active");
            };

            const updateConnectionStatus = (status) => {
                connectionStatus.className = `connection-status ${status}`;
                switch(status) {
                    case 'connected':
                        connectionText.textContent = 'Connected';
                        break;
                    case 'connecting':
                        connectionText.textContent = 'Connecting...';
                        break;
                    case 'disconnected':
                        connectionText.textContent = 'Disconnected';
                        break;
                }
            };

            const updateStatus = (message, type = '') => {
                let icon = '';
                switch(type) {
                    case 'recording':
                        icon = '<i class="fas fa-microphone"></i>';
                        break;
                    case 'processing':
                        icon = '<i class="fas fa-cog status-icon"></i>';
                        break;
                    case 'error':
                        icon = '<i class="fas fa-exclamation-triangle"></i>';
                        break;
                }
                statusDisplay.innerHTML = `${icon} ${message}`;
            };

            // Enhanced recording functions
            const startRecording = async () => {
                try {
                    updateStatus("Initializing...", "processing");
                    updateConnectionStatus('connecting');

                    mediaStream = await navigator.mediaDevices.getUserMedia({
                        audio: {
                            echoCancellation: true,
                            noiseSuppression: true,
                            sampleRate: 16000
                        }
                    });

                    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });

                    const source = audioContext.createMediaStreamSource(mediaStream);
                    processor = audioContext.createScriptProcessor(4096, 1, 1);
                    source.connect(processor);
                    processor.connect(audioContext.destination);

                    processor.onaudioprocess = (e) => {
                        const inputData = e.inputBuffer.getChannelData(0);
                        const pcmData = new Int16Array(inputData.length);
                        for (let i = 0; i < inputData.length; i++) {
                            pcmData[i] = Math.max(-1, Math.min(1, inputData[i])) * 32767;
                        }
                        if (ws && ws.readyState === WebSocket.OPEN) {
                            ws.send(pcmData);
                        }
                    };

                    const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
                    ws = new WebSocket(`${wsProtocol}//${window.location.host}/ws`);

                    ws.onopen = () => {
                        console.log("✅ WebSocket connected");
                        updateConnectionStatus('connected');
                        isRecording = true;
                        updateRecordingUI();
                    };

                    ws.onmessage = (event) => {
                        const msg = JSON.parse(event.data);
                        if (msg.type === "assistant") {
                            addOrUpdateMessage(msg.text, "assistant", msg.diagram);
                        } else if (msg.type === "final") {
                            addOrUpdateMessage(msg.text, "user");
                            showTypingIndicator();
                        } else if (msg.type === "audio") {
                            audioQueue.push(msg.b64);
                            if (!isPlaying) playNextInQueue();
                        }
                    };

                    ws.onclose = (e) => {
                        console.warn("⚠️ WebSocket closed:", e.code, e.reason);
                        updateConnectionStatus('disconnected');
                        if (isRecording) {
                            stopRecording();
                        }
                    };

                } catch (error) {
                    console.error("Could not start recording:", error);
                    updateStatus("Microphone access denied", "error");
                    updateConnectionStatus('disconnected');
                    setTimeout(() => {
                        alert("Microphone access is required to use the voice agent. Please allow microphone access and try again.");
                    }, 100);
                }
            };

            const stopRecording = () => {
                if (processor) {
                    processor.disconnect();
                    processor = null;
                }
                if (mediaStream) {
                    mediaStream.getTracks().forEach(track => track.stop());
                    mediaStream = null;
                }
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.close();
                }
                if (audioContext && audioContext.state !== 'closed') {
                    audioContext.close();
                }

                isRecording = false;
                updateRecordingUI();
                updateConnectionStatus('disconnected');
            };

            const updateRecordingUI = () => {
                if (isRecording) {
                    recordBtn.classList.add("recording");
                    recordIcon.className = "fas fa-stop";
                    recordBtn.setAttribute("aria-label", "Stop Recording");
                    waveform.classList.add("active");
                    updateStatus("Listening... Click to stop", "recording");
                } else {
                    recordBtn.classList.remove("recording");
                    recordIcon.className = "fas fa-microphone";
                    recordBtn.setAttribute("aria-label", "Start Recording");
                    waveform.classList.remove("active");
                    hideTypingIndicator();
                    updateStatus("Ready to chat!");
                }
            };

            // Event listeners
            recordBtn.addEventListener("click", () => {
                if (isRecording) {
                    stopRecording();
                } else {
                    startRecording();
                }
            });

            // Control button functionality
            clearBtn.addEventListener("click", () => {
                // Clear chat but keep the welcome message
                const messages = chatLog.querySelectorAll('.message:not(:first-child)');
                messages.forEach(msg => msg.remove());
                hideTypingIndicator();
                assistantMessageDiv = null;

                // Add confirmation message
                updateStatus("Chat cleared!", "");
                setTimeout(() => {
                    updateStatus("Ready to chat!");
                }, 1500);
            });

            volumeBtn.addEventListener("click", () => {
                audioEnabled = !audioEnabled;
                if (audioEnabled) {
                    volumeBtn.innerHTML = '<i class="fas fa-volume-up"></i> Audio On';
                    volumeBtn.classList.remove('active');
                } else {
                    volumeBtn.innerHTML = '<i class="fas fa-volume-mute"></i> Audio Off';
                    volumeBtn.classList.add('active');
                    // Clear audio queue if disabling
                    audioQueue = [];
                    isPlaying = false;
                }
            });

            helpBtn.addEventListener("click", () => {
                const helpMessage = document.createElement('div');
                helpMessage.className = 'message assistant';
                helpMessage.innerHTML = `
                    <i class="fas fa-info-circle" style="margin-right: 8px; color: #4facfe;"></i>
                    <strong>How to use the AI Voice Agent:</strong><br><br>
                    🎤 <strong>Voice Input:</strong> Click the microphone button and speak naturally<br>
                    📝 <strong>Text Responses:</strong> I'll respond with text and voice<br>
                    📊 <strong>Diagrams:</strong> I can create flowcharts and diagrams using Mermaid<br>
                    🎵 <strong>Audio Control:</strong> Toggle audio responses on/off<br>
                    🗑️ <strong>Clear Chat:</strong> Remove conversation history<br><br>
                    <em>Tips: Speak clearly, ask questions, request diagrams, or just have a conversation!</em>
                `;
                chatLog.appendChild(helpMessage);
                chatLog.scrollTop = chatLog.scrollHeight;
            });

            // Keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Space bar to toggle recording (when not focused on input)
                if (e.code === 'Space' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
                    e.preventDefault();
                    if (isRecording) {
                        stopRecording();
                    } else {
                        startRecording();
                    }
                }

                // Escape to stop recording
                if (e.key === 'Escape' && isRecording) {
                    stopRecording();
                }

                // Ctrl+L to clear chat
                if (e.ctrlKey && e.key === 'l') {
                    e.preventDefault();
                    clearBtn.click();
                }
            });

            // Initialize connection status
            updateConnectionStatus('disconnected');

            // Add some visual feedback on page load
            setTimeout(() => {
                updateStatus("Click the microphone to start!");
            }, 1000);

            // Cleanup on page unload
            window.addEventListener('beforeunload', () => {
                if (isRecording) {
                    stopRecording();
                }
            });
        });
