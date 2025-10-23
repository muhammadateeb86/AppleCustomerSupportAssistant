# 🍎 Apple Customer Support (Voice AI Assistant)

This project is a real-time, voice-driven AI assistant that simulates an Apple Technical Customer Support call. It captures audio from your microphone, transcribes it live using AssemblyAI, and generates an intelligent, in-character response from OpenAI's GPT-4o-mini.

![App Screenshot](screenshot.png)

## Features

* **Real-time Audio Capture:** Uses PyAudio to capture microphone input.
* **Dynamic Device Selection:** A pop-up window on first run allows you to select your preferred audio input device.
* **Live Speech-to-Text:** Streams audio to AssemblyAI's WebSocket API for fast, real-time transcription.
* **Intelligent AI Responses:** Uses OpenAI (GPT-4o-mini) with a detailed system prompt to act as "TJ," a professional Apple Technical Advisor.
* **Streaming Responses:** The AI's response is streamed back and displayed word-by-word for a more natural, conversational feel.
* **Modern Tkinter GUI:** A clean, modern interface showing the full conversation log, connection status, and performance stats.
* **Performance Stats:** Monitors call duration, AI response latency, and total responses.
* **Conversation Management:** Includes controls to copy the conversation to the clipboard, clear the log, and start/stop the assistant.

## How It Works

The application uses multi-threading to manage several tasks concurrently without freezing the UI:

1.  **Audio Thread:** `PyAudio` captures audio from the selected microphone and places it into a `queue`.
2.  **AssemblyAI Thread:** A `websocket` connection sends the audio data from the queue to the AssemblyAI streaming API. It listens for transcript messages (both partial and final).
3.  **GPT Worker Thread:** When a final transcript is received from AssemblyAI, it's put into another `queue`. The GPT worker picks it up, adds it to the conversation history, and sends it to the OpenAI API.
4.  **UI Thread (Main):** The main thread runs the Tkinter event loop. It polls a `ui_queue` for new messages (customer transcripts, AI responses, or errors) and updates the chat box, ensuring all UI updates are thread-safe.

[Image of a flow diagram: Mic -> PyAudio -> AssemblyAI -> OpenAI GPT -> Tkinter UI]

## Technologies Used

* **Python 3**
* **GUI:** Tkinter
* **Audio Capture:** [PyAudio](https://people.csail.mit.edu/hubert/pyaudio/)
* **Speech-to-Text (STT):** [AssemblyAI](https://www.assemblyai.com/) (Streaming API)
* **Language Model (LLM):** [OpenAI](https://openai.com/) (GPT-4o-mini)
* **WebSockets:** [websocket-client](https://github.com/websocket-client/websocket-client)
* **Concurrency:** `threading` and `queue`

## Setup and Installation

### 1. Prerequisites

* Python 3.7 or newer.
* An **AssemblyAI** API key.
* An **OpenAI** API key.

### 2. Clone the Repository

```bash
git clone [https://github.com/your-username/your-repository-name.git](https://github.com/your-username/your-repository-name.git)
cd your-repository-name
