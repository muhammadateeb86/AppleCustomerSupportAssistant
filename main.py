import pyaudio
import queue
import json
import threading
import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import openai
import websocket
from urllib.parse import urlencode
from datetime import datetime
import audioop
import time

# ------------ CONFIG SETUP ------------
CONFIG_FILE = 'config.json'
DEFAULT_CONFIG = {
    "openai_api_key": "",
    "assemblyai_api_key": "",
    "device_index": 0
}

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

config = load_config()

# ------------ GLOBALS ------------
is_running = False
stream_open = False
stream = None
openai.api_key = config['openai_api_key']
CONNECTION_PARAMS = {"sample_rate": 16000, "format_turns": True}
API_ENDPOINT = f"wss://streaming.assemblyai.com/v3/ws?{urlencode(CONNECTION_PARAMS)}"
RATE = 16000
CHUNK_MS = 50  # Reduced from 100ms to 50ms for faster audio delivery
FRAME_LEN = int(RATE * CHUNK_MS / 1000)  # 800 samples

# ------------ QUEUES ------------
audio_q = queue.Queue()
stt_q = queue.Queue()
ui_q = queue.Queue()

# ------------ STYLING CONSTANTS ------------
COLORS = {
    'bg_primary': '#f8f9fa',
    'bg_secondary': '#ffffff',
    'bg_bones': '#D3D3D3',
    'bg_accent': '#007AFF',
    'bg_success': '#34D399',
    'bg_error': '#EF4444',
    'text_primary': '#1f2937',
    'text_secondary': '#6b7280',
    'text_accent': '#ffffff',
    'border': '#e5e7eb',
    'hover': '#f3f4f6',
    'chat_customer': '#E5F0FF',
    'chat_assistant': '#F0FDFA'
}

FONTS = {
    'title': ('SF Pro Display', 18, 'bold'),
    'subtitle': ('SF Pro Display', 14, 'bold'),
    'body': ('SF`SF Pro Text', 12),
    'small': ('SF Pro Text', 10),
    'mono': ('SF Mono', 11),
    'chat': ('SF Pro Text', 12)
}

# ------------ CUSTOM WIDGETS ------------
class ModernFrame(tk.Frame):
    def __init__(self, parent, bg_color=COLORS['bg_secondary'], **kwargs):
        super().__init__(parent, bg=bg_color, relief='flat', bd=0, **kwargs)
        self.configure(highlightthickness=1, highlightcolor=COLORS['border'], highlightbackground=COLORS['border'])

class ModernButton(tk.Button):
    def __init__(self, parent, style='primary', **kwargs):
        styles = {
            'primary': {
                'bg': COLORS['bg_accent'],
                'fg': COLORS['text_accent'],
                'activebackground': '#0056CC',
                'activeforeground': COLORS['text_accent']
            },
            'secondary': {
                'bg': COLORS['bg_primary'],
                'fg': COLORS['text_primary'],
                'activebackground': COLORS['hover'],
                'activeforeground': COLORS['text_primary']
            },
            'success': {
                'bg': COLORS['bg_success'],
                'fg': COLORS['text_accent'],
                'activebackground': '#10B981',
                'activeforeground': COLORS['text_accent']
            }
        }
        
        style_config = styles.get(style, styles['primary'])
        super().__init__(
            parent,
            font=FONTS['body'],
            relief='flat',
            bd=0,
            cursor='hand2',
            **style_config,
            **kwargs
        )
        
        self.bind('<Enter>', self._on_enter)
        self.bind('<Leave>', self._on_leave)
        self.default_bg = style_config['bg']
        self.hover_bg = style_config['activebackground']
    
    def _on_enter(self, event):
        self.configure(bg=self.hover_bg)
    
    def _on_leave(self, event):
        self.configure(bg=self.default_bg)

class StatusIndicator(tk.Label):
    def __init__(self, parent, **kwargs):
        bg_color = kwargs.pop('bg', COLORS['bg_secondary'])
        super().__init__(
            parent,
            font=FONTS['small'],
            bg=bg_color,
            fg=COLORS['text_secondary'],
            **kwargs
        )
        self.set_status('offline')
    
    def set_status(self, status):
        status_config = {
            'online': {'text': '🟢 Live &Ready', 'fg': COLORS['bg_success']},
            'processing': {'text': '🟡 Processing...', 'fg': '#F59E0B'},
            'offline': {'text': '🔴 Offline', 'fg': COLORS['bg_error']},
            'error': {'text': '🔴 Error', 'fg': COLORS['bg_error']}
        }
        config = status_config.get(status, status_config['offline'])
        self.configure(text=config['text'], fg=config['fg'])

class StatsPanel(ModernFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.stats = {
            'call_duration': '00:00',
            'responses': 0,
            'accuracy': '98%',
            'latency': '0.8s'
        }
        self.labels = {}
        self.setup_ui()
        self.start_time = time.time()
        self.update_timer()
    
    def setup_ui(self):
        title = tk.Label(self, text='Performance Stats', font=FONTS['subtitle'], 
                        bg=COLORS['bg_secondary'], fg=COLORS['text_primary'])
        title.pack(pady=(10, 5))
        
        stats_frame = tk.Frame(self, bg=COLORS['bg_secondary'])
        stats_frame.pack(fill='x', padx=10, pady=5)
        
        stat_items = [
            ('Call Duration', 'call_duration'),
            ('Responses', 'responses'),
            ('Accuracy', 'accuracy'),
            ('Latency', 'latency')
        ]
        
        for i, (label, key) in enumerate(stat_items):
            frame = tk.Frame(stats_frame, bg=COLORS['bg_secondary'])
            frame.grid(row=i//2, column=i%2, padx=5, pady=3, sticky='w')
            
            tk.Label(frame, text=f'{label}:', font=FONTS['small'], 
                    bg=COLORS['bg_secondary'], fg=COLORS['text_secondary']).pack(side='left')
            
            self.labels[key] = tk.Label(frame, text=self.stats[key], font=FONTS['body'], 
                                       bg=COLORS['bg_secondary'], fg=COLORS['text_primary'])
            self.labels[key].pack(side='right', padx=(10, 0))
    
    def update_stat(self, key, value):
        if key in self.stats:
            self.stats[key] = value
            if key in self.labels:
                self.labels[key].configure(text=str(value))
    
    def update_timer(self):
        if is_running:
            duration = int(time.time() - self.start_time)
            minutes = duration // 60
            seconds = duration % 60
            self.update_stat('call_duration', f'{minutes:02d}:{seconds:02d}')
            self.after(1000, self.update_timer)

# ------------ AUDIO DEVICE SELECTION ------------
def select_device(p):
    devices = []
    for i in range(p.get_device_count()):
        dev = p.get_device_info_by_index(i)
        if dev['maxInputChannels'] > 0:
            devices.append((i, f"[{i}] {dev['name']}"))

    if not devices:
        raise ValueError("No input devices found")

    if config['device_index'] is not None and config['device_index'] in [d[0] for d in devices]:
        return config['device_index']

    temp_root = tk.Tk()
    temp_root.title("Select Audio Device")
    temp_root.configure(bg=COLORS['bg_primary'])
    temp_root.resizable(True, True)
    
    temp_root.withdraw()
    
    header = ModernFrame(temp_root, bg_color=COLORS['bg_accent'])
    header.pack(fill='x', pady=(0, 15))
    
    tk.Label(header, text="🎤 Select Audio Input Device", 
            font=FONTS['title'], bg=COLORS['bg_accent'], fg=COLORS['text_accent']).pack(pady=15)
    
    main_frame = ModernFrame(temp_root)
    main_frame.pack(fill='both', expand=True, padx=15, pady=(0, 15))
    
    tk.Label(main_frame, text="Available Input Devices:", 
            font=FONTS['subtitle'], bg=COLORS['bg_secondary'], fg=COLORS['text_primary']).pack(pady=(10, 5), anchor='w')
    
    canvas = tk.Canvas(main_frame, bg=COLORS['bg_secondary'], highlightthickness=0)
    scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=COLORS['bg_secondary'])
    
    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    
    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    
    canvas.pack(side="left", fill="both", expand=True, pady=(0, 15))
    scrollbar.pack(side="right", fill="y", pady=(0, 15))
    
    var = tk.StringVar(value=str(devices[0][0]))
    selected_device = [None]
    
    for idx, name in devices:
        frame = tk.Frame(scrollable_frame, bg=COLORS['bg_secondary'])
        frame.pack(fill='x', pady=2, padx=5)
        
        tk.Radiobutton(frame, text=name, variable=var, value=str(idx),
                      font=FONTS['body'], bg=COLORS['bg_secondary'], 
                      fg=COLORS['text_primary'], selectcolor=COLORS['bg_accent'],
                      wraplength=500).pack(anchor='w', padx=10, pady=2)
    
    btn_frame = tk.Frame(temp_root, bg=COLORS['bg_primary'])
    btn_frame.pack(fill='x', padx=15, pady=(0, 15))
    
    def on_select():
        selected_device[0] = int(var.get())
        temp_root.destroy()
    
    def on_cancel():
        temp_root.destroy()
    
    ModernButton(btn_frame, text="Cancel", style='secondary', 
                command=on_cancel).pack(side='left')
    ModernButton(btn_frame, text="✓ Select Device", style='primary', 
                command=on_select).pack(side='right')
    
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    temp_root.update_idletasks()
    temp_root.geometry("600x500")
    width = 600
    height = 500
    x = (temp_root.winfo_screenwidth() // 2) - (width // 2)
    y = (temp_root.winfo_screenheight() // 2) - (height // 2)
    temp_root.geometry(f'{width}x{height}+{x}+{y}')
    
    temp_root.deiconify()
    temp_root.lift()
    temp_root.focus_force()
    temp_root.grab_set()
    
    temp_root.mainloop()
    
    try:
        canvas.unbind_all("<MouseWheel>")
    except tk.TclError:
        pass
    
    if selected_device[0] is not None:
        config['device_index'] = selected_device[0]
        save_config(config)
        return selected_device[0]
    else:
        return devices[0][0]

# ------------ TK SETUP ------------
p = pyaudio.PyAudio()
device_index = select_device(p)
dev = p.get_device_info_by_index(device_index)
CHANNELS = dev['maxInputChannels']
sample_width = p.get_sample_size(pyaudio.paInt16)

if CHANNELS > 1:
    CHANNELS = 1

root = tk.Tk()

# ------------ AUDIO CAPTURE ------------
def read_audio():
    try:
        while is_running:
            data = stream.read(FRAME_LEN, exception_on_overflow=False)
            if CHANNELS > 1:
                data = audioop.tomono(data, sample_width, 0.5, 0.5)
            if len(data) == 0 or data == b'\x00' * len(data):
                continue
            audio_q.put(data)
    except Exception as e:
        stt_q.put(f"Error: Audio input failed - {e}")
        ui_q.put(f"Error: Audio input failed - {e}")
        audio_q.put(b'')

# ------------ STT HANDLER ------------
last_partial_transcript = None

def on_open(ws):
    print("WebSocket connection opened.")
    status_indicator.set_status('online')
    def stream_audio():
        while is_running:
            try:
                audio_data = audio_q.get(timeout=1.0)
                if not audio_data or audio_data == b'\x00' * len(audio_data):
                    continue
                ws.send(audio_data, websocket.ABNF.OPCODE_BINARY)
            except queue.Empty:
                continue
            except websocket.WebSocketConnectionClosedException:
                break
            except Exception as e:
                break
    threading.Thread(target=stream_audio, daemon=True).start()

def on_message(ws, message):
    global last_partial_transcript
    try:
        data = json.loads(message)
        if data.get('type') == "Begin":
            session_id = data.get('id')
            expires_at = data.get('expires_at')
            print(f"Session began: ID={session_id}, ExpiresAt={datetime.fromtimestamp(expires_at)}")
        elif data.get('type') == "Turn":
            transcript = data.get('transcript', '')
            if transcript and data.get('turn_is_formatted'):
                ui_q.put(('customer', transcript, data.get('end_of_turn', False)))
                if data.get('end_of_turn'):
                    stt_q.put(transcript)  # Process immediately
        elif data.get('type') == "Termination":
            audio_duration = data.get('audio_duration_seconds', 0)
            print(f"Session terminated: Audio Duration={audio_duration}s")
        elif data.get('type') == "error":
            stt_q.put(f"STT error: {data.get('message')}")
            ui_q.put(('error', f"STT error: {data.get('message')}", True))
            status_indicator.set_status('error')
    except Exception as e:
        print(f"on_message error: {e}")

def on_error(ws, error):
    stt_q.put(f"Error: STT connection failed - {error}")
    ui_q.put(('error', f"Error: STT connection failed - {error}", True))
    status_indicator.set_status('error')

def on_close(ws, status_code, msg):
    print(f"WebSocket closed: Status={status_code}, Msg={msg}")
    global is_running
    is_running = False
    status_indicator.set_status('offline')

ws_app = websocket.WebSocketApp(
    API_ENDPOINT,
    header=[f"Authorization: {config['assemblyai_api_key']}"],
    on_open=on_open,
    on_message=on_message,
    on_error=on_error,
    on_close=on_close
)

def run_stt():
    ws_app.run_forever()

def gpt_worker():
    client = openai.OpenAI(api_key=config['openai_api_key'])

    # Initialize conversation history with the system message
    system_message = {
        "role": "system",
        "content": (
            "Act as a Apple Technical Customer Support Advisor named TJ.\n"
            "You are a technical expert in Apple inc. You will need to provide solutions and help to issues, query,  troubleshooting and others regarding any apple products. You need to understand every technical issuws apple products have and best solution  to in a way to satisfy the customer. You Must Sound exactly like a human, professional, calm, and empathetic. Stay in character.\n\n"
            "Follow this chat flows as a expert technical advisor when attending to any Apple customers to ensure they are satisfied:\n"
            "1. Greet the customer.\n"
            "2. Ask for their first and last name, then Apple ID email.\n"
            "3. Ask, “What can I help you with today?”\n"
            "4. Confirm and restate the issue back to them.\n"
            "5. Ask clarifying questions if needed.\n"
            "6. Guide the customers step-by-step (in short, clear instructions). Speak simply for elderly customers.\n"
            "7. Provide resolution or next steps.\n"
            "8. Log a short case note in this format:\n"
            "Issue: [summarize]\n"
            "Steps taken: [summarize]\n"
            "Outcome: [resolved/escalated/transferred]\n"
            "9. Always end each conversation with a polite closing as well trained tech advisor, even if no resolution.\n\n"
            "Your response be human like and not robotic. Always sound understanding — if a customer is upset or things aren’t going their way, show calm empathy and reassure them that you’ll do all you can within your scope to calm them down and ensure they are happy  you will help them.\n\n"
            "Only support iOS issues (Apple ID, iCloud, billing, app issues, iPhone/iPad help). If out of scope (e.g., carrier, Mac, or Apple TV), politely refer them to the right support incase or unrelated questions. Note: Stay updated of latest updates from the apple Inc."
        )
    }
    conversation_history = [system_message]

    while is_running:
        try:
            text = stt_q.get(timeout=1.0)
            if text.startswith("Error:"):
                continue

            status_indicator.set_status('processing')
            stats_panel.update_stat('responses', stats_panel.stats['responses'] + 1)

            # Add user message to conversation history
            user_message = {"role": "user", "content": text}
            conversation_history.append(user_message)

            # TRIM the conversation to last 10 user+assistant pairs (20 messages)
            MAX_TURNS = 10
            if len(conversation_history) > (2 * MAX_TURNS + 1):  # +1 for system message
                conversation_history = [system_message] + conversation_history[-2 * MAX_TURNS:]

            start_time = time.time()
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=conversation_history,
                stream=True,
                max_tokens=150,
                temperature=0.5
            )

            # Initialize assistant message in UI
            ui_q.put(('assistant', f"[{datetime.now().strftime('%H:%M:%S')}] TJ: ", False))

            # Collect streamed response
            assistant_response = ""
            for chunk in resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    assistant_response += content
                    ui_q.put(('assistant', content, False))

            # Add assistant response to conversation history
            conversation_history.append({"role": "assistant", "content": assistant_response})

            # Mark the end of the assistant's response
            ui_q.put(('assistant', "\n\n", True))

            latency = time.time() - start_time
            stats_panel.update_stat('latency', f'{latency:.1f}s')

            btn_copy.configure(state="normal")
            status_indicator.set_status('online')

        except queue.Empty:
            continue
        except Exception as e:
            print(f"GPT error: {e}")
            status_indicator.set_status('error')
            

# ------------ ENHANCED UI ------------
root.title("🍎 Apple Customer Support Assistant")
root.geometry("1100x800")
root.configure(bg=COLORS['bg_primary'])

try:
    root.iconbitmap('icon.ico')
except:
    pass

# Header Frame
header_frame = ModernFrame(root, bg_color=COLORS['bg_accent'])
header_frame.pack(fill='x', pady=(0, 10))

title_frame = tk.Frame(header_frame, bg=COLORS['bg_accent'])
title_frame.pack(fill='x', pady=15)

tk.Label(title_frame, text="🍎 Apple Customer Support Assistant", 
         font=FONTS['title'], bg=COLORS['bg_accent'], fg=COLORS['text_accent']).pack(side='left', padx=20)

status_indicator = StatusIndicator(title_frame, bg=COLORS['bg_accent'])
status_indicator.pack(side='right', padx=20)

# Main container
main_container = tk.Frame(root, bg=COLORS['bg_primary'])
main_container.pack(fill='both', expand=True, padx=10, pady=(0, 10))

# Left panel (chat thread)
left_panel = tk.Frame(main_container, bg=COLORS['bg_primary'])
left_panel.pack(side='left', fill='both', expand=True, padx=(0, 5))

# Chat panel
chat_frame = ModernFrame(left_panel)
chat_frame.pack(fill='both', expand=True)

tk.Label(chat_frame, text="💬 Conversation", 
         font=FONTS['subtitle'], bg=COLORS['bg_secondary'], fg=COLORS['text_primary']).pack(pady=(15, 5))

chat_box = scrolledtext.ScrolledText(
    chat_frame, 
    height=20, 
    state="disabled",
    font=FONTS['chat'],
    bg=COLORS['bg_primary'],
    fg=COLORS['text_primary'],
    insertbackground=COLORS['text_primary'],
    selectbackground=COLORS['bg_accent'],
    selectforeground=COLORS['text_accent'],
    relief='flat',
    bd=0,
    wrap='word'
)
chat_box.pack(fill="both", expand=True, padx=15, pady=(0, 15))

# Configure tags for styling customer and assistant messages
chat_box.tag_configure("customer", background=COLORS['chat_customer'], lmargin1=10, lmargin2=10, rmargin=10, spacing1=5, spacing3=5)
chat_box.tag_configure("assistant", background=COLORS['chat_assistant'], lmargin1=10, lmargin2=10, rmargin=10, spacing1=5, spacing3=5)

# Right panel (stats and controls)
right_panel = tk.Frame(main_container, bg=COLORS['bg_primary'])
right_panel.pack(side='right', fill='y', padx=(5, 0))

# Stats panel
stats_panel = StatsPanel(right_panel)
stats_panel.pack(fill='x', pady=(0, 10))

# Controls panel
controls_frame = ModernFrame(right_panel)
controls_frame.pack(fill='x', pady=(0, 10))

tk.Label(controls_frame, text="Controls", 
         font=FONTS['subtitle'], bg=COLORS['bg_secondary'], fg=COLORS['text_primary']).pack(pady=(15, 10))

def copy_to_clipboard():
    text = chat_box.get("1.0", "end").strip()
    if text:
        root.clipboard_clear()
        root.clipboard_append(text)
        btn_copy.configure(text="✓ Copied!")
        root.after(1500, lambda: btn_copy.configure(text="📋 Copy Conversation"))

def clear_conversation():
    chat_box.configure(state="normal")
    chat_box.delete("1.0", "end")
    chat_box.configure(state="disabled")
    btn_copy.configure(state="disabled")

def start_assistant():
    global is_running, stream, stream_open
    if is_running:
        return
    is_running = True
    stats_panel.start_time = time.time()  # Reset start time
    stats_panel.update_timer()           # Start the timer
    stream = p.open(
        format=pyaudio.paInt16,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        input_device_index=device_index,
        frames_per_buffer=FRAME_LEN
    )
    stream_open = True
    threading.Thread(target=read_audio, daemon=True).start()
    threading.Thread(target=gpt_worker, daemon=True).start()
    threading.Thread(target=run_stt, daemon=True).start()
    root.after(100, poll_queues)
    btn_start.configure(state="disabled")
    btn_stop.configure(state="normal")

def stop_app():
    global is_running, stream_open
    if not is_running:
        return
    is_running = False
    audio_q.put(b'')
    try:
        if ws_app.sock and ws_app.sock.connected:
            ws_app.send(json.dumps({"type": "Terminate"}))
            time.sleep(1)
        ws_app.close()
    except Exception:
        pass
    if stream_open:
        stream.stop_stream()
        stream.close()
        stream_open = False
    btn_start.configure(state="normal")
    btn_stop.configure(state="disabled")

def exit_app():
    stop_app()
    p.terminate()
    root.quit()

# Control buttons
btn_frame = tk.Frame(controls_frame, bg=COLORS['bg_secondary'])
btn_frame.pack(fill='x', padx=15, pady=(0, 15))

btn_start = ModernButton(btn_frame, text="▶️ Start Assistant", style='success', 
                        command=start_assistant)
btn_start.pack(fill='x', pady=(0, 8))

btn_copy = ModernButton(btn_frame, text="📋 Copy Conversation", style='primary', 
                       state="disabled", command=copy_to_clipboard)
btn_copy.pack(fill='x', pady=(0, 8))

ModernButton(btn_frame, text="🗑️ Clear Conversation", style='secondary', 
            command=clear_conversation).pack(fill='x', pady=(0, 8))

btn_stop = ModernButton(btn_frame, text="⏹️ Stop Assistant", style='secondary', 
                       command=stop_app, state="disabled")
btn_stop.pack(fill='x', pady=(0, 8))

# Info panel
info_frame = ModernFrame(right_panel)
info_frame.pack(fill='x')

tk.Label(info_frame, text="ℹ️ Information", 
         font=FONTS['subtitle'], bg=COLORS['bg_secondary'], fg=COLORS['text_primary']).pack(pady=(15, 10))

info_text = tk.Text(
    info_frame,
    height=6,
    font=FONTS['small'],
    bg=COLORS['bg_primary'],
    fg=COLORS['text_secondary'],
    relief='flat',
    bd=0,
    wrap='word',
    state='disabled'
)
info_text.pack(fill='x', padx=15, pady=(0, 15))

info_content = """• Listening for customer audio input
• Real-time speech transcription
• AI-powered response generation
• Professional Apple support tone
• Click Copy to use conversation
• Monitor performance stats above"""

info_text.configure(state='normal')
info_text.insert('1.0', info_content)
info_text.configure(state='disabled')

def poll_queues():
    global last_partial_transcript
    try:
        while True:
            item = ui_q.get_nowait()
            role, text, is_final = item
            chat_box.configure(state="normal")
            
            if role == 'customer':
                if last_partial_transcript:
                    chat_box.delete("end-2l", "end-1l")
                if is_final:
                    chat_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] Customer: {text}\n\n", "customer")
                    last_partial_transcript = None
                else:
                    chat_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] Customer: {text}", "customer")
                    last_partial_transcript = text
            elif role == 'assistant':
                if not is_final:
                    chat_box.insert("end", text, "assistant")
                else:
                    chat_box.insert("end", text, "assistant")
            elif role == 'error':
                chat_box.insert("end", f"[{datetime.now().strftime('%H:%M:%S')}] Error: {text}\n\n", "error")
            
            chat_box.configure(state="disabled")
            chat_box.see("end")
            root.update()
    except queue.Empty:
        pass

    if is_running:
        root.after(100, poll_queues)  # Reduced from 200ms to 100ms

# ------------ START ------------
print("Starting enhanced Tkinter application...")
root.protocol("WM_DELETE_WINDOW", exit_app)
root.mainloop()