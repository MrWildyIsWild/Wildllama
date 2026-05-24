"""
WildLlama v2 - A savage Ollama UI
Run:  python3 WildLlamaV2.py
Then: open http://localhost:8080

Optional extras (graceful degradation if missing):
  pip install pymupdf         # fast PDF extraction
  pip install pdfminer.six    # fallback PDF extraction
"""

import json, os, glob, re, time, threading, subprocess, sys
import urllib.request, urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
PORT        = int(os.environ.get("WILDLLAMA_PORT", 8080))
HOST        = os.environ.get("WILDLLAMA_HOST", "127.0.0.1")
DATA_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wildllama-data")
CHATS_DIR   = os.path.join(DATA_DIR, "chats")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

for d in [DATA_DIR, CHATS_DIR]:
    os.makedirs(d, exist_ok=True)

DEFAULT_CONFIG = {
    "system_prompt": "",
    "temperature": 0.7,
    "context_window": 4096,
    "memory": [],
    "ollama_url": "http://localhost:11434",
    "theme": "dark",
    "accent": "#7c6ff7",
    "font_size": 14,
    "show_token_count": True,
    "prompts": [
        {"name": "Code Review", "text": "Review this code for bugs, security issues, and improvements:"},
        {"name": "Explain Simply", "text": "Explain this like I'm 5 years old:"},
        {"name": "Write Tests", "text": "Write comprehensive unit tests for:"},
        {"name": "Debug Helper", "text": "Help me debug this issue:"},
    ]
}

def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return dict(DEFAULT_CONFIG)

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def safe_filename(title, chat_id):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'\s+', '-', slug.strip())[:40]
    return f"{slug}-{chat_id}.json" if slug else f"chat-{chat_id}.json"

def chat_path_by_id(chat_id):
    matches = glob.glob(os.path.join(CHATS_DIR, f"*-{chat_id}.json"))
    return matches[0] if matches else os.path.join(CHATS_DIR, f"chat-{chat_id}.json")

def load_all_chats():
    chats = []
    for p in sorted(glob.glob(os.path.join(CHATS_DIR, "*.json")), key=os.path.getmtime):
        try:
            with open(p, "r", encoding="utf-8") as f:
                chats.append(json.load(f))
        except Exception:
            pass
    return chats

def save_chat(chat):
    old = glob.glob(os.path.join(CHATS_DIR, f"*-{chat['id']}.json"))
    new_path = os.path.join(CHATS_DIR, safe_filename(chat.get("title", "chat"), chat["id"]))
    for o in old:
        if o != new_path:
            try: os.remove(o)
            except: pass
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(chat, f, ensure_ascii=False, indent=2)

def delete_chat(chat_id):
    for p in glob.glob(os.path.join(CHATS_DIR, f"*-{chat_id}.json")):
        try: os.remove(p)
        except: pass

def export_chat_md(chat):
    lines = [f"# {chat.get('title','Chat')}", f"Model: {chat.get('model','')}", ""]
    for m in chat.get("messages", []):
        if m["role"] == "system": continue
        prefix = "**You:**" if m["role"] == "user" else "**WildLlama:**"
        lines.append(f"{prefix}\n{m['content']}\n")
    return "\n".join(lines)

def extract_pdf_text(b64):
    import base64, io
    raw = base64.b64decode(b64)
    try:
        import fitz
        doc = fitz.open(stream=raw, filetype="pdf")
        return "\n\n".join(p.get_text() for p in doc)
    except ImportError:
        pass
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        buf = io.BytesIO(raw); out = io.StringIO()
        extract_text_to_fp(buf, out, laparams=LAParams())
        return out.getvalue()
    except ImportError:
        pass
    return "[PDF extraction needs: pip install pymupdf  or  pip install pdfminer.six]"

def get_model_info(model_name, ollama_url):
    try:
        payload = json.dumps({"name": model_name}).encode()
        req = urllib.request.Request(
            f"{ollama_url}/api/show",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return {}

def stream_pull(model_name, write_fn):
    payload = json.dumps({"name": model_name, "stream": True}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/pull",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        while True:
            line = resp.readline()
            if not line: break
            write_fn(line)

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>WildLlama</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=DM+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/atom-one-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0d0d10;
  --bg2:#111116;
  --bg3:#18181f;
  --bg4:#1e1e28;
  --bg5:#24242f;
  --surface:#1a1a23;
  --border:#22222e;
  --border2:#2a2a38;
  --border3:#333345;

  --accent:#7c6ff7;
  --accent2:#6a5ee0;
  --accent3:#4d43b0;
  --accent-glow:rgba(124,111,247,0.2);
  --accent-dim:rgba(124,111,247,0.08);
  --accent-mid:rgba(124,111,247,0.14);

  --text:#e8e8f0;
  --text2:#8888a8;
  --text3:#44445a;
  --text4:#2a2a38;

  --user-bg:#16161e;
  --ai-bg:#0d0d10;

  --danger:#f05c7a;
  --danger-dim:rgba(240,92,122,0.1);
  --warn:#f0a05c;
  --green:#5cf0a0;
  --green-dim:rgba(92,240,160,0.1);

  --sidebar-w:260px;
  --radius:14px;
  --radius-sm:9px;
  --radius-xs:5px;
  --trans:all 0.15s cubic-bezier(0.4,0,0.2,1);
  --font:'DM Sans',sans-serif;
  --mono:'DM Mono',monospace;
  --font-size:14px;
}
html.light{
  --bg:#f2ede8;
  --bg2:#ede8e2;
  --bg3:#e5dfd8;
  --bg4:#ddd6cd;
  --bg5:#d4ccc2;
  --surface:#ede8e2;
  --border:#cfc8bf;
  --border2:#c4bcb2;
  --border3:#b8afa4;
  --text:#1a1814;
  --text2:#5a5248;
  --text3:#9a9088;
  --text4:#c0b8b0;
  --user-bg:#e8e2db;
  --ai-bg:#f2ede8;
  --accent-glow:rgba(124,111,247,0.15);
  --accent-dim:rgba(124,111,247,0.08);
  --accent-mid:rgba(124,111,247,0.13);
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font);overflow:hidden;font-size:var(--font-size)}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border3);border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:var(--accent3)}
button,input,select,textarea{font-family:var(--font)}
button{cursor:pointer}

/* ── LAYOUT ── */
#app{display:flex;height:100vh;position:relative}

/* ══ SIDEBAR ══ */
#sidebar{
  width:var(--sidebar-w);min-width:var(--sidebar-w);
  background:var(--bg2);border-right:1px solid var(--border);
  display:flex;flex-direction:column;height:100%;z-index:20;
  transition:var(--trans);
}

/* logo */
#sidebar-header{padding:18px 14px 14px;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:16px;text-decoration:none;user-select:none}
.logo-mark{
  width:34px;height:34px;flex-shrink:0;
  background:var(--accent);border-radius:10px;
  display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 18px var(--accent-glow);
  position:relative;overflow:hidden;
}
.logo-mark::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.18),transparent)}
.logo-llama{width:20px;height:20px;fill:none;stroke:#fff;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round;position:relative;z-index:1}
.logo-name{font-size:17px;font-weight:700;letter-spacing:-.02em;color:var(--text)}
.logo-name em{font-style:normal;color:var(--accent)}
.logo-badge{
  margin-left:auto;font-size:8px;font-weight:600;letter-spacing:.1em;
  background:var(--accent-dim);border:1px solid var(--accent3);
  color:var(--accent);border-radius:99px;padding:2px 7px;text-transform:uppercase;
  font-family:var(--mono);
}

/* model selector */
.model-label{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--text3);margin-bottom:5px}
.model-wrap{position:relative}
#model-select{
  width:100%;background:var(--bg3);border:1px solid var(--border2);
  border-radius:var(--radius-sm);color:var(--text);font-size:13px;font-weight:500;
  padding:8px 30px 8px 11px;appearance:none;cursor:pointer;
  transition:var(--trans);outline:none;
}
#model-select:hover,#model-select:focus{border-color:var(--accent3);background:var(--bg4)}
.model-chevron{position:absolute;right:9px;top:50%;transform:translateY(-50%);pointer-events:none;color:var(--text3)}

/* quick params */
.param-row{display:flex;gap:6px;margin-top:10px}
.param-block{
  flex:1;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);padding:7px 10px;cursor:pointer;transition:var(--trans);
}
.param-block:hover{border-color:var(--border2);background:var(--bg4)}
.param-block-label{font-size:9px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--text3);margin-bottom:2px}
.param-block-value{font-size:13px;font-weight:700;color:var(--accent);font-family:var(--mono)}

/* new chat */
#new-chat-btn{
  margin-top:10px;width:100%;padding:9px;
  background:var(--accent-dim);border:1px solid var(--border2);
  border-radius:var(--radius-sm);color:var(--accent);
  font-size:13px;font-weight:600;letter-spacing:.01em;
  display:flex;align-items:center;justify-content:center;gap:6px;
  transition:var(--trans);outline:none;
}
#new-chat-btn:hover{background:var(--accent-mid);border-color:var(--accent3);box-shadow:0 0 18px var(--accent-glow)}

/* sidebar tabs */
.sidebar-tabs{display:flex;gap:0;padding:0 14px;border-bottom:1px solid var(--border);margin-top:2px}
.sidebar-tab{
  flex:1;padding:10px 4px;font-size:11px;font-weight:600;letter-spacing:.04em;
  text-transform:uppercase;background:none;border:none;
  color:var(--text3);border-bottom:2px solid transparent;
  margin-bottom:-1px;transition:var(--trans);text-align:center;
}
.sidebar-tab.active{color:var(--accent);border-bottom-color:var(--accent)}
.sidebar-tab:hover:not(.active){color:var(--text2)}

.sidebar-panel{display:none;flex:1;overflow-y:auto;min-height:0}
.sidebar-panel.active{display:flex;flex-direction:column}

/* history */
#history-list{padding:8px 8px;display:flex;flex-direction:column;gap:1px}
.history-group-label{
  font-size:9px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text4);padding:10px 8px 4px;
}
.history-item{
  padding:8px 9px;border-radius:var(--radius-sm);cursor:pointer;
  border:1px solid transparent;position:relative;transition:var(--trans);
}
.history-item:hover{background:var(--bg3);border-color:var(--border)}
.history-item.active{background:var(--accent-dim);border-color:var(--border2)}
.history-item-title{
  font-size:12.5px;font-weight:500;color:var(--text2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;padding-right:44px;
  transition:var(--trans);
}
.history-item:hover .history-item-title,.history-item.active .history-item-title{color:var(--text)}
.history-item-meta{font-size:10px;color:var(--text3);margin-top:1px;font-family:var(--mono)}
.history-item-actions{position:absolute;right:5px;top:50%;transform:translateY(-50%);display:flex;gap:1px;opacity:0;transition:var(--trans)}
.history-item:hover .history-item-actions{opacity:1}
.history-action-btn{
  background:none;border:none;color:var(--text3);padding:4px;border-radius:4px;
  display:flex;align-items:center;justify-content:center;transition:var(--trans);
}
.history-action-btn:hover{color:var(--danger);background:var(--danger-dim)}
.history-action-btn.export:hover{color:var(--accent);background:var(--accent-dim)}

/* prompts panel */
#prompts-panel{padding:8px}
.prompt-card{
  padding:10px 12px;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);margin-bottom:5px;cursor:pointer;transition:var(--trans);
}
.prompt-card:hover{border-color:var(--accent3);background:var(--bg4)}
.prompt-card-name{font-size:12px;font-weight:700;color:var(--text);margin-bottom:2px}
.prompt-card-preview{font-size:11px;color:var(--text3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.prompt-card-actions{display:flex;gap:4px;margin-top:6px;opacity:0;transition:var(--trans)}
.prompt-card:hover .prompt-card-actions{opacity:1}
.prompt-card-del{background:none;border:none;color:var(--text3);font-size:10px;padding:2px 6px;border-radius:3px;transition:var(--trans)}
.prompt-card-del:hover{color:var(--danger);background:var(--danger-dim)}
.prompt-add-btn{
  width:100%;padding:8px;background:none;border:1px dashed var(--border3);
  border-radius:var(--radius-sm);color:var(--text3);font-size:12px;font-weight:600;
  display:flex;align-items:center;justify-content:center;gap:6px;
  transition:var(--trans);margin-top:6px;
}
.prompt-add-btn:hover{border-color:var(--accent3);color:var(--accent);background:var(--accent-dim)}

/* models panel */
#models-panel{padding:8px}
.model-card{
  padding:10px 12px;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);margin-bottom:5px;transition:var(--trans);cursor:pointer;
}
.model-card:hover{border-color:var(--border2);background:var(--bg4)}
.model-card-top{display:flex;align-items:center;justify-content:space-between}
.model-card-name{font-size:12px;font-weight:700;color:var(--text);font-family:var(--mono)}
.model-card-actions{display:flex;gap:3px}
.model-card-btn{
  background:none;border:none;color:var(--text3);padding:3px;
  border-radius:4px;display:flex;transition:var(--trans);
}
.model-card-btn:hover{color:var(--danger);background:var(--danger-dim)}
.model-card-btn.info:hover{color:var(--accent);background:var(--accent-dim)}
.model-card-meta{margin-top:4px;display:flex;gap:8px;flex-wrap:wrap}
.model-card-tag{font-size:10px;color:var(--text3);font-family:var(--mono);background:var(--bg4);padding:1px 5px;border-radius:3px;border:1px solid var(--border)}
.pull-wrap{display:flex;gap:6px;margin-bottom:8px}
#pull-input{
  flex:1;background:var(--bg4);border:1px solid var(--border2);border-radius:var(--radius-sm);
  color:var(--text);font-size:12px;padding:7px 9px;outline:none;transition:var(--trans);
}
#pull-input:focus{border-color:var(--accent3)}
#pull-btn{
  padding:7px 12px;background:var(--accent);border:none;border-radius:var(--radius-sm);
  color:#fff;font-size:12px;font-weight:700;transition:var(--trans);
}
#pull-btn:hover{background:var(--accent2)}
#pull-progress{
  background:var(--bg4);border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:8px 10px;font-size:11px;font-family:var(--mono);color:var(--text3);
  max-height:80px;overflow-y:auto;display:none;margin-bottom:8px;
}

/* sidebar footer */
#sidebar-footer{padding:10px 14px;border-top:1px solid var(--border)}
.status-row{display:flex;align-items:center;justify-content:space-between}
.status-wrap{display:flex;align-items:center;gap:6px}
.status-dot{width:6px;height:6px;border-radius:50%;background:var(--text3);transition:var(--trans)}
.status-dot.online{background:var(--green);box-shadow:0 0 7px var(--green)}
.status-dot.offline{background:var(--danger)}
.status-text{font-size:11px;color:var(--text3);font-weight:500}
.footer-btns{display:flex;gap:3px}

/* ══ MAIN ══ */
#main{flex:1;display:flex;flex-direction:column;height:100%;min-width:0;background:var(--bg);position:relative;overflow:hidden}
#main::before{
  content:'';position:absolute;top:-200px;right:-200px;
  width:600px;height:600px;
  background:radial-gradient(circle,rgba(124,111,247,0.04) 0%,transparent 65%);
  pointer-events:none;z-index:0;
}

/* topbar */
#topbar{
  display:flex;align-items:center;justify-content:space-between;
  padding:0 20px;height:54px;border-bottom:1px solid var(--border);
  background:var(--bg2);position:relative;z-index:5;flex-shrink:0;
}
#chat-title-wrap{display:flex;align-items:center;gap:8px;min-width:0;flex:1}
#chat-title{
  font-size:14px;font-weight:500;color:var(--text2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  max-width:340px;cursor:pointer;transition:var(--trans);padding:3px 6px;border-radius:5px;
}
#chat-title:hover{color:var(--text);background:var(--bg3)}
#chat-title[contenteditable="true"]{
  outline:none;border-bottom:1px solid var(--accent3);color:var(--text);background:transparent;
}
.topbar-chip{
  padding:3px 9px;background:var(--bg3);border:1px solid var(--border2);
  border-radius:99px;font-size:11px;font-weight:500;color:var(--accent);
  font-family:var(--mono);letter-spacing:.01em;flex-shrink:0;
}
.topbar-right{display:flex;align-items:center;gap:5px;flex-shrink:0}
#token-counter{
  font-size:10px;font-weight:500;color:var(--text3);font-family:var(--mono);
  padding:3px 8px;background:var(--bg3);border:1px solid var(--border);border-radius:99px;
}
.icon-btn{
  width:32px;height:32px;background:transparent;border:1px solid transparent;
  border-radius:var(--radius-sm);cursor:pointer;display:flex;
  align-items:center;justify-content:center;color:var(--text3);transition:var(--trans);flex-shrink:0;
}
.icon-btn:hover{border-color:var(--border2);color:var(--text);background:var(--bg3)}
.icon-btn svg{width:15px;height:15px}
.icon-btn.active{border-color:var(--accent3);color:var(--accent);background:var(--accent-dim)}

/* messages */
#messages{flex:1;overflow-y:auto;padding:24px 28px;display:flex;flex-direction:column;gap:0;position:relative;z-index:1;scroll-behavior:smooth}

/* empty state */
#empty-state{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;animation:fadeUp .4s ease both}
.empty-logo{
  width:64px;height:64px;background:var(--bg3);border:1px solid var(--border2);
  border-radius:20px;display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 40px var(--accent-glow);margin-bottom:4px;
}
.empty-logo svg{width:32px;height:32px;stroke:var(--accent)}
.empty-title{font-size:22px;font-weight:700;color:var(--text);letter-spacing:-.02em}
.empty-sub{font-size:13px;color:var(--text3);text-align:center;max-width:280px;line-height:1.7;font-weight:400}
.empty-pills{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;max-width:480px;margin-top:4px}
.e-pill{
  padding:7px 14px;background:var(--bg2);border:1px solid var(--border2);
  border-radius:99px;font-size:12px;color:var(--text3);cursor:pointer;
  transition:var(--trans);font-weight:400;
}
.e-pill:hover{background:var(--accent-dim);border-color:var(--accent3);color:var(--accent)}

/* message rows */
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}

.msg-group{display:flex;flex-direction:column;gap:2px;margin-bottom:20px;animation:fadeUp .2s ease both}

/* user messages */
.user-msg-wrap{display:flex;justify-content:flex-end}
.user-bubble{
  max-width:70%;padding:10px 14px;
  background:var(--user-bg);border:1px solid var(--border2);
  border-radius:var(--radius) var(--radius) 4px var(--radius);
  font-size:var(--font-size);line-height:1.7;color:var(--text);word-break:break-word;
}

/* assistant messages */
.ai-msg-wrap{display:flex;gap:10px;align-items:flex-start}
.ai-avatar{
  width:26px;height:26px;border-radius:8px;flex-shrink:0;margin-top:2px;
  background:var(--accent);display:flex;align-items:center;justify-content:center;
  box-shadow:0 0 10px var(--accent-glow);
}
.ai-avatar svg{width:13px;height:13px;stroke:#fff;fill:none}
.ai-bubble{
  flex:1;min-width:0;font-size:var(--font-size);line-height:1.8;color:var(--text);word-break:break-word;
  padding-top:2px;
}

/* message actions */
.msg-actions{display:flex;gap:3px;margin-top:8px;padding-left:36px;opacity:0;transition:opacity .15s}
.ai-msg-wrap:hover .msg-actions,.msg-actions:focus-within{opacity:1}
.msg-action-btn{
  display:flex;align-items:center;gap:3px;padding:3px 9px;
  background:var(--bg3);border:1px solid var(--border2);border-radius:99px;
  font-size:10px;font-weight:600;font-family:var(--font);color:var(--text3);
  cursor:pointer;transition:var(--trans);letter-spacing:.01em;
}
.msg-action-btn svg{width:10px;height:10px}
.msg-action-btn:hover{background:var(--accent-dim);border-color:var(--accent3);color:var(--accent)}
.msg-action-btn.copied{color:var(--green);border-color:var(--green);background:var(--green-dim)}
.msg-action-btn.danger:hover{color:var(--danger);border-color:var(--danger);background:var(--danger-dim)}

/* markdown */
.ai-bubble p{margin-bottom:10px}.ai-bubble p:last-child{margin-bottom:0}
.ai-bubble ul,.ai-bubble ol{padding-left:20px;margin:6px 0}
.ai-bubble li{margin-bottom:3px}
.ai-bubble strong{color:var(--text);font-weight:600}
.ai-bubble em{color:var(--text2);font-style:italic}
.ai-bubble h1,.ai-bubble h2,.ai-bubble h3{color:var(--text);margin:14px 0 6px;font-weight:700;letter-spacing:-.01em}
.ai-bubble h1{font-size:18px;border-bottom:1px solid var(--border);padding-bottom:6px}
.ai-bubble h2{font-size:16px}
.ai-bubble h3{font-size:14px;color:var(--accent)}
.ai-bubble blockquote{border-left:3px solid var(--accent3);padding:4px 0 4px 12px;color:var(--text2);margin:8px 0;background:var(--bg3);border-radius:0 6px 6px 0}
.ai-bubble table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}
.ai-bubble th{background:var(--bg4);border:1px solid var(--border2);padding:7px 12px;text-align:left;font-weight:600;color:var(--text)}
.ai-bubble td{border:1px solid var(--border);padding:7px 12px;color:var(--text2)}
.ai-bubble tr:nth-child(even) td{background:var(--bg2)}
.ai-bubble hr{border:none;border-top:1px solid var(--border);margin:14px 0}
.ai-bubble a{color:var(--accent);text-decoration:none}
.ai-bubble a:hover{text-decoration:underline}
.ai-bubble del{color:var(--text3)}
.ai-bubble code:not(pre code){
  font-family:var(--mono);font-size:12px;background:var(--bg3);
  padding:2px 6px;border-radius:4px;color:var(--accent);border:1px solid var(--border);
}

/* code blocks */
.code-block-wrap{margin:10px 0;border-radius:var(--radius-sm);overflow:hidden;border:1px solid var(--border2)}
.code-block-header{
  display:flex;align-items:center;justify-content:space-between;
  background:var(--bg4);padding:6px 12px;
}
.code-lang{font-size:10px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);font-family:var(--mono)}
.code-copy-btn{
  font-size:10px;font-weight:600;color:var(--text3);background:none;border:none;
  display:flex;align-items:center;gap:3px;padding:2px 6px;border-radius:4px;transition:var(--trans);
}
.code-copy-btn:hover{color:var(--accent);background:var(--accent-dim)}
.code-copy-btn.copied{color:var(--green)}
.ai-bubble pre{
  margin:0;padding:14px 16px;overflow-x:auto;background:var(--bg2) !important;
  font-family:var(--mono);font-size:12.5px;line-height:1.65;
}
.ai-bubble pre code.hljs{background:transparent !important;padding:0 !important;font-size:12.5px;font-family:var(--mono)}

/* thinking dots */
.thinking{display:flex;gap:4px;padding:8px 0;align-items:center}
.thinking span{width:5px;height:5px;background:var(--accent3);border-radius:50%;animation:think 1.2s infinite ease-in-out}
.thinking span:nth-child(2){animation-delay:.16s}
.thinking span:nth-child(3){animation-delay:.32s}
@keyframes think{0%,100%{transform:scale(.6);opacity:.3}50%{transform:scale(1);opacity:1}}

/* streaming cursor */
.cursor{display:inline-block;width:1.5px;height:14px;background:var(--accent);margin-left:2px;vertical-align:middle;animation:blink .9s infinite;border-radius:1px}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}

/* file attachments */
.bubble-img{max-width:280px;max-height:180px;border-radius:var(--radius-sm);border:1px solid var(--border2);margin-bottom:7px;display:block}
.bubble-file-chip{
  display:inline-flex;align-items:center;gap:5px;background:var(--bg3);
  border:1px solid var(--border2);border-radius:var(--radius-sm);
  padding:4px 9px;font-size:11px;font-family:var(--mono);color:var(--text2);margin-bottom:6px;
}

/* ── INPUT AREA ── */
#input-area{padding:12px 20px 18px;position:relative;z-index:5;flex-shrink:0}
#input-area::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--border2),transparent)}
#file-preview-bar{display:none;flex-wrap:wrap;gap:6px;margin-bottom:8px;padding:0 2px}
#file-preview-bar.visible{display:flex}
.file-chip{
  display:flex;align-items:center;gap:5px;background:var(--bg3);border:1px solid var(--border2);
  border-radius:var(--radius-sm);padding:4px 8px;font-size:11px;font-family:var(--mono);
  color:var(--text2);animation:fadeUp .15s ease both;max-width:200px;
}
.file-chip-thumb{width:24px;height:24px;border-radius:4px;object-fit:cover;flex-shrink:0}
.file-chip-icon{width:24px;height:24px;background:var(--bg4);border-radius:4px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.file-chip-icon svg{width:12px;height:12px;color:var(--accent)}
.file-chip-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.file-chip-remove{background:none;border:none;color:var(--text3);cursor:pointer;padding:2px;border-radius:2px;display:flex;transition:var(--trans)}
.file-chip-remove:hover{color:var(--danger)}

.input-wrap{
  display:flex;align-items:flex-end;gap:7px;background:var(--bg2);
  border:1px solid var(--border2);border-radius:14px;padding:8px 10px;
  transition:var(--trans);
}
.input-wrap:focus-within{border-color:var(--accent3);box-shadow:0 0 0 3px var(--accent-dim)}
.input-wrap.drag-over{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-dim)}

#input-shell{flex:1;position:relative;display:flex;align-items:flex-end}
#user-input{
  width:100%;background:none;border:none;outline:none;color:var(--text);
  font-size:14px;line-height:1.65;resize:none;max-height:200px;min-height:24px;
  overflow-y:auto;position:relative;z-index:2;
}
#user-input::placeholder{color:var(--text3)}
#autocomplete-ghost{
  position:absolute;top:0;left:0;width:100%;pointer-events:none;z-index:1;
  font-size:14px;line-height:1.65;white-space:pre-wrap;word-break:break-word;
}
.ghost-typed{color:transparent}
.ghost-suggestion{color:var(--text3);opacity:.4}
#tab-badge{display:none;background:var(--bg4);border:1px solid var(--border2);border-radius:3px;padding:0 3px;font-size:8px;font-family:var(--mono);color:var(--text3);vertical-align:middle;margin-left:3px;opacity:.7;line-height:1.7}
#tab-badge.visible{display:inline}

.input-side-btns{display:flex;align-items:flex-end;gap:4px}
.input-btn{
  width:32px;height:32px;background:none;border:1px solid transparent;
  border-radius:8px;cursor:pointer;display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:var(--trans);color:var(--text3);
}
.input-btn:hover{border-color:var(--border2);color:var(--text);background:var(--bg3)}
.input-btn.active{color:var(--accent)}
.input-btn svg{width:15px;height:15px}

#send-btn{
  width:34px;height:34px;border:none;border-radius:9px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;flex-shrink:0;
  transition:var(--trans);position:relative;overflow:hidden;
}
#send-btn.send-mode{background:var(--accent);box-shadow:0 0 14px var(--accent-glow)}
#send-btn.stop-mode{background:transparent;border:2px solid var(--danger);box-shadow:0 0 10px rgba(240,92,122,.2)}
#send-btn.send-mode:hover{background:var(--accent2);box-shadow:0 0 22px var(--accent-glow)}
#send-btn.stop-mode:hover{background:var(--danger-dim)}
#send-btn:active{transform:scale(0.93)}
#send-btn:disabled{opacity:.35;cursor:not-allowed;transform:none;box-shadow:none}
#send-btn svg{width:15px;height:15px;transition:var(--trans)}
#send-btn.send-mode svg{color:#fff}
#send-btn.stop-mode svg{color:var(--danger)}
#send-btn.stop-mode::before{
  content:'';position:absolute;inset:-2px;border-radius:11px;
  border:2px solid transparent;border-top-color:var(--danger);
  animation:spin 1s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}

.input-hint{text-align:center;font-size:10px;color:var(--text4);margin-top:7px;font-family:var(--mono);letter-spacing:.03em}
.input-hint kbd{background:var(--bg3);border:1px solid var(--border2);border-radius:3px;padding:1px 4px;font-family:var(--mono);font-size:9px;color:var(--text3)}

/* ══ SETTINGS ══ */
#settings-overlay{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;
  backdrop-filter:blur(4px);animation:fadeIn .18s ease;
}
#settings-panel{
  position:absolute;top:0;right:0;bottom:0;width:360px;
  background:var(--bg2);border-left:1px solid var(--border);
  overflow-y:auto;display:flex;flex-direction:column;
  animation:slideIn .18s ease;
}
@keyframes slideIn{from{transform:translateX(30px);opacity:0}to{transform:translateX(0);opacity:1}}
#settings-overlay.open{display:flex;align-items:stretch}
.settings-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:20px 22px 16px;border-bottom:1px solid var(--border);
  font-size:15px;font-weight:700;color:var(--text);flex-shrink:0;
}
.settings-close{
  width:28px;height:28px;background:var(--bg3);border:1px solid var(--border);
  border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:center;
  cursor:pointer;color:var(--text2);transition:var(--trans);
}
.settings-close:hover{color:var(--danger);border-color:var(--danger)}
.settings-body{padding:18px 22px;flex:1}
.settings-section{margin-bottom:24px}
.settings-section-title{
  font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--accent);margin-bottom:12px;display:flex;align-items:center;gap:7px;
}
.settings-section-title::after{content:'';flex:1;height:1px;background:var(--border)}
.setting-row{margin-bottom:13px}
.setting-label{font-size:12px;font-weight:600;color:var(--text2);margin-bottom:5px;display:flex;align-items:center;justify-content:space-between}
.setting-value{font-family:var(--mono);color:var(--accent);font-size:12px}
.setting-input{
  width:100%;background:var(--bg3);border:1px solid var(--border2);
  border-radius:var(--radius-sm);color:var(--text);font-size:13px;
  padding:8px 11px;outline:none;transition:var(--trans);
}
.setting-input:focus{border-color:var(--accent3)}
textarea.setting-input{resize:vertical;min-height:80px;line-height:1.6}
.setting-select{appearance:none;cursor:pointer}
.slider-wrap{display:flex;align-items:center;gap:10px}
input[type=range]{
  flex:1;height:4px;border-radius:99px;appearance:none;
  background:linear-gradient(90deg,var(--accent) 0%,var(--accent) var(--pct,50%),var(--border3) var(--pct,50%));
  outline:none;cursor:pointer;
}
input[type=range]::-webkit-slider-thumb{
  appearance:none;width:14px;height:14px;border-radius:50%;
  background:var(--accent);box-shadow:0 0 6px var(--accent-glow);
  border:2px solid var(--bg2);cursor:grab;transition:transform .1s;
}
input[type=range]::-webkit-slider-thumb:active{transform:scale(1.25);cursor:grabbing}

/* memory */
.memory-list{display:flex;flex-direction:column;gap:5px;margin-bottom:7px}
.memory-item{
  display:flex;align-items:center;gap:8px;background:var(--bg3);
  border:1px solid var(--border);border-radius:var(--radius-sm);
  padding:7px 9px;font-size:12px;
}
.memory-item-text{flex:1;color:var(--text2)}
.memory-item-del{background:none;border:none;color:var(--text3);cursor:pointer;padding:2px 4px;border-radius:3px;flex-shrink:0;transition:var(--trans)}
.memory-item-del:hover{color:var(--danger)}
.memory-add-row{display:flex;gap:6px}
.memory-add-row input{flex:1;background:var(--bg4);border:1px solid var(--border2);border-radius:var(--radius-sm);color:var(--text);font-size:12px;padding:6px 9px;outline:none;transition:var(--trans)}
.memory-add-row input:focus{border-color:var(--accent3)}
.memory-add-row button{padding:6px 12px;background:var(--accent);border:none;border-radius:var(--radius-sm);color:#fff;font-size:12px;font-weight:700;transition:var(--trans)}
.memory-add-row button:hover{background:var(--accent2)}

/* accent swatches */
.color-swatches{display:flex;gap:7px;flex-wrap:wrap}
.color-swatch{width:26px;height:26px;border-radius:7px;cursor:pointer;border:2px solid transparent;transition:var(--trans)}
.color-swatch.active,.color-swatch:hover{border-color:var(--text);transform:scale(1.1)}

.settings-save-btn{
  width:100%;padding:10px;background:var(--accent);border:none;
  border-radius:var(--radius-sm);color:#fff;font-size:14px;font-weight:700;
  transition:var(--trans);letter-spacing:.01em;
}
.settings-save-btn:hover{background:var(--accent2);box-shadow:0 0 18px var(--accent-glow)}

/* ══ MODALS (inline, no browser confirm) ══ */
.modal-overlay{
  display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:200;
  align-items:center;justify-content:center;backdrop-filter:blur(4px);
}
.modal-overlay.open{display:flex;animation:fadeIn .15s ease}
.modal-box{
  background:var(--bg2);border:1px solid var(--border2);border-radius:var(--radius);
  padding:24px;min-width:300px;max-width:380px;animation:fadeUp .15s ease;
  box-shadow:0 20px 60px rgba(0,0,0,.4);
}
.modal-title{font-size:15px;font-weight:700;color:var(--text);margin-bottom:8px}
.modal-body{font-size:13px;color:var(--text2);line-height:1.6;margin-bottom:18px}
.modal-btns{display:flex;gap:8px;justify-content:flex-end}
.modal-btn{padding:8px 16px;border-radius:var(--radius-sm);font-size:13px;font-weight:700;border:none;transition:var(--trans);cursor:pointer}
.modal-btn.cancel{background:var(--bg4);color:var(--text2);border:1px solid var(--border2)}
.modal-btn.cancel:hover{background:var(--bg5)}
.modal-btn.danger{background:var(--danger);color:#fff}
.modal-btn.danger:hover{filter:brightness(1.1)}
.modal-btn.primary{background:var(--accent);color:#fff}
.modal-btn.primary:hover{background:var(--accent2)}
.modal-input{
  width:100%;background:var(--bg3);border:1px solid var(--border2);
  border-radius:var(--radius-sm);color:var(--text);font-size:13px;
  padding:9px 12px;outline:none;transition:var(--trans);margin-bottom:16px;
}
.modal-input:focus{border-color:var(--accent3)}
textarea.modal-input{resize:vertical;min-height:70px;line-height:1.6}
.modal-label{font-size:11px;font-weight:600;color:var(--text3);margin-bottom:4px;letter-spacing:.04em;text-transform:uppercase}

/* param modal */
#param-modal .modal-box{width:320px}

/* ══ TOAST ══ */
#toast{
  position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(14px);
  background:var(--bg4);border:1px solid var(--border2);border-radius:99px;
  padding:8px 16px;font-size:12px;font-weight:600;color:var(--text2);
  opacity:0;pointer-events:none;transition:all .22s ease;z-index:999;
  display:flex;align-items:center;gap:6px;box-shadow:0 4px 20px rgba(0,0,0,.3);
}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#toast.success .toast-dot{background:var(--green)}
#toast.error .toast-dot{background:var(--danger)}
.toast-dot{width:5px;height:5px;border-radius:50%;background:var(--accent);flex-shrink:0}

/* ══ SEARCH ══ */
#search-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:150;align-items:flex-start;justify-content:center;backdrop-filter:blur(4px);padding-top:70px}
#search-overlay.open{display:flex;animation:fadeIn .15s ease}
.search-box{width:480px;background:var(--bg2);border:1px solid var(--border2);border-radius:var(--radius);overflow:hidden;animation:fadeUp .12s ease;box-shadow:0 20px 60px rgba(0,0,0,.4)}
#search-input{width:100%;background:none;border:none;border-bottom:1px solid var(--border);color:var(--text);font-size:15px;padding:15px 18px;outline:none;font-family:var(--font)}
#search-input::placeholder{color:var(--text3)}
#search-results{max-height:280px;overflow-y:auto}
.search-result-item{padding:10px 18px;cursor:pointer;transition:var(--trans);border-bottom:1px solid var(--border)}
.search-result-item:hover{background:var(--bg3)}
.search-result-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:2px}
.search-result-preview{font-size:11px;color:var(--text3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.search-result-preview mark{background:none;color:var(--accent);font-weight:700}
.search-empty{padding:20px;text-align:center;color:var(--text3);font-size:13px}

/* ══ MODEL INFO ══ */
#model-info-modal .modal-box{min-width:340px}
.model-info-row{display:flex;align-items:center;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)}
.model-info-row:last-child{border-bottom:none}
.model-info-key{font-size:11px;color:var(--text3);font-weight:600;text-transform:uppercase;letter-spacing:.06em}
.model-info-val{font-size:12px;color:var(--text);font-family:var(--mono)}

#file-input{display:none}
</style>
</head>
<body>
<div id="app">

<!-- ═══ SIDEBAR ═══ -->
<aside id="sidebar">
  <div id="sidebar-header">
    <a class="logo" href="#" onclick="return false">
      <div class="logo-mark">
        <!-- Llama head silhouette logo -->
        <svg class="logo-llama" viewBox="0 0 24 24">
          <path d="M12 3 C9.5 3 7.5 4.5 7 6.5 C6 6.2 5 6.8 4.5 7.8 C4 8.8 4.3 10 5 10.6 C4.8 11.2 4.8 11.8 5 12.4 C5 15 6.5 17.5 9 18.5 L9 21 L11 21 L11 19 L13 19 L13 21 L15 21 L15 18.5 C17.5 17.5 19 15 19 12.4 C19.5 11.6 19.5 10.6 19 9.8 C19.8 9 19.8 7.6 19 6.8 C18.2 6 17 6 16.2 6.6 C15.5 4.5 13.8 3 12 3Z"/>
          <circle cx="9.5" cy="10" r="0.8" fill="#fff" stroke="none"/>
          <circle cx="14.5" cy="10" r="0.8" fill="#fff" stroke="none"/>
        </svg>
      </div>
      <span class="logo-name">Wild<em>Llama</em></span>
      <span class="logo-badge">v3</span>
    </a>

    <div class="model-label">Model</div>
    <div class="model-wrap">
      <select id="model-select"><option value="">Loading…</option></select>
      <svg class="model-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
    </div>

    <div class="param-row">
      <div class="param-block" onclick="openParamModal('temp')" title="Temperature">
        <div class="param-block-label">Temp</div>
        <div class="param-block-value" id="param-temp-display">0.7</div>
      </div>
      <div class="param-block" onclick="openParamModal('ctx')" title="Context Window">
        <div class="param-block-label">Context</div>
        <div class="param-block-value" id="param-ctx-display">4K</div>
      </div>
    </div>

    <button id="new-chat-btn">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      New Chat
    </button>
  </div>

  <div class="sidebar-tabs">
    <button class="sidebar-tab active" onclick="switchSideTab('chats',this)">Chats</button>
    <button class="sidebar-tab" onclick="switchSideTab('prompts',this)">Prompts</button>
    <button class="sidebar-tab" onclick="switchSideTab('models',this)">Models</button>
  </div>

  <div class="sidebar-panel active" id="chats-panel">
    <div id="history-list"></div>
  </div>

  <div class="sidebar-panel" id="prompts-panel">
    <div style="padding:8px">
      <div id="prompt-cards"></div>
      <button class="prompt-add-btn" onclick="openAddPromptModal()">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Add Prompt
      </button>
    </div>
  </div>

  <div class="sidebar-panel" id="models-panel">
    <div style="padding:8px">
      <div class="pull-wrap">
        <input type="text" id="pull-input" placeholder="llama3:8b, qwen2.5:7b…" onkeydown="if(event.key==='Enter')pullModel()"/>
        <button id="pull-btn" onclick="pullModel()">Pull</button>
      </div>
      <div id="pull-progress"></div>
      <div id="model-cards"></div>
    </div>
  </div>

  <div id="sidebar-footer">
    <div class="status-row">
      <div class="status-wrap">
        <span class="status-dot" id="status-dot"></span>
        <span class="status-text" id="status-text">Connecting…</span>
      </div>
      <div class="footer-btns">
        <button class="icon-btn" onclick="openSettings()" title="Settings (Ctrl+,)">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </button>
      </div>
    </div>
  </div>
</aside>

<!-- ═══ MAIN ═══ -->
<main id="main">
  <div id="topbar">
    <div id="chat-title-wrap">
      <div id="chat-title" title="Double-click to rename">New Conversation</div>
    </div>
    <div class="topbar-right">
      <div id="token-counter" style="display:none">0 tokens</div>
      <div class="topbar-chip" id="topbar-model">—</div>
      <button class="icon-btn" id="search-btn" onclick="openSearch()" title="Search (Ctrl+F)">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      </button>
      <button class="icon-btn" onclick="openSettings('system')" title="System prompt">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
      </button>
      <button class="icon-btn" onclick="exportCurrentChat()" title="Export chat">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
      </button>
      <button class="icon-btn" id="theme-btn" title="Toggle theme">
        <svg id="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg id="icon-sun" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      </button>
    </div>
  </div>

  <div id="messages"></div>

  <div id="input-area">
    <div id="file-preview-bar"></div>
    <div class="input-wrap" id="input-wrap">
      <div class="input-side-btns">
        <button class="input-btn" id="attach-btn" title="Attach file">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        </button>
        <button class="input-btn" id="voice-btn" title="Voice input">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
        </button>
      </div>
      <input type="file" id="file-input" multiple accept="image/*,.pdf,.txt,.md,.py,.js,.ts,.jsx,.tsx,.html,.css,.json,.csv,.xml,.yaml,.yml,.sh,.c,.cpp,.java,.rs,.go"/>
      <div id="input-shell">
        <div id="autocomplete-ghost"><span class="ghost-typed"></span><span class="ghost-suggestion"></span><span id="tab-badge">tab</span></div>
        <textarea id="user-input" placeholder="Message WildLlama…" rows="1"></textarea>
      </div>
      <div class="input-side-btns">
        <button id="send-btn" class="send-mode" title="Send (Enter)">
          <svg id="send-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          <svg id="stop-icon" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        </button>
      </div>
    </div>
    <div class="input-hint">
      <kbd>Enter</kbd> send &nbsp;·&nbsp; <kbd>Shift+Enter</kbd> newline &nbsp;·&nbsp; <kbd>Tab</kbd> complete &nbsp;·&nbsp; <kbd>Ctrl+K</kbd> new chat &nbsp;·&nbsp; <kbd>Ctrl+F</kbd> search
    </div>
  </div>
</main>
</div>

<!-- ═══ SETTINGS ═══ -->
<div id="settings-overlay" onclick="maybeCloseSettings(event)">
  <div id="settings-panel">
    <div class="settings-header">
      <span>Settings</span>
      <button class="settings-close" onclick="closeSettings()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="settings-body">
      <div class="settings-section">
        <div class="settings-section-title">Model Defaults</div>
        <div class="setting-row">
          <div class="setting-label">Temperature <span class="setting-value" id="s-temp-val">0.7</span></div>
          <div class="slider-wrap"><input type="range" id="s-temp" min="0" max="2" step="0.05" value="0.7" oninput="sliderUpdate(this,'s-temp-val')"></div>
        </div>
        <div class="setting-row">
          <div class="setting-label">Context Window <span class="setting-value" id="s-ctx-val">4096</span></div>
          <div class="slider-wrap"><input type="range" id="s-ctx" min="512" max="131072" step="512" value="4096" oninput="sliderUpdate(this,'s-ctx-val')"></div>
        </div>
        <div class="setting-row">
          <div class="setting-label">Ollama Server URL</div>
          <input class="setting-input" type="text" id="s-url" value="http://localhost:11434"/>
        </div>
      </div>
      <div class="settings-section" id="settings-system-section">
        <div class="settings-section-title">System Prompt</div>
        <div class="setting-row">
          <textarea class="setting-input" id="s-system" rows="4" placeholder="You are a helpful assistant…"></textarea>
        </div>
      </div>
      <div class="settings-section">
        <div class="settings-section-title">Personal Memory</div>
        <div class="memory-list" id="memory-list"></div>
        <div class="memory-add-row">
          <input type="text" id="memory-input" placeholder="e.g. I prefer Python" onkeydown="if(event.key==='Enter')addMemory()"/>
          <button onclick="addMemory()">Add</button>
        </div>
      </div>
      <div class="settings-section">
        <div class="settings-section-title">Appearance</div>
        <div class="setting-row">
          <div class="setting-label">Font Size <span class="setting-value" id="s-fs-val">14px</span></div>
          <div class="slider-wrap"><input type="range" id="s-fs" min="12" max="18" step="1" value="14" oninput="sliderUpdate(this,'s-fs-val',true)"></div>
        </div>
        <div class="setting-row">
          <div class="setting-label">Accent Color</div>
          <div class="color-swatches" id="color-swatches"></div>
        </div>
        <div class="setting-row">
          <div class="setting-label">Show token count</div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="s-tokens" checked style="accent-color:var(--accent);width:15px;height:15px"/>
          </label>
        </div>
      </div>
      <button class="settings-save-btn" onclick="saveSettings()">Save Settings</button>
    </div>
  </div>
</div>

<!-- ═══ PARAM MODAL ═══ -->
<div class="modal-overlay" id="param-modal" onclick="closeParamModal(event)">
  <div class="modal-box">
    <div class="modal-title" id="param-modal-title">Temperature</div>
    <div class="setting-row" style="margin-bottom:0">
      <div class="setting-label" id="param-label">Value <span class="setting-value" id="param-val-display">0.7</span></div>
      <div class="slider-wrap"><input type="range" id="param-slider" min="0" max="2" step="0.05" value="0.7" oninput="paramSliderUpdate()"></div>
    </div>
    <div class="modal-btns" style="margin-top:18px">
      <button class="modal-btn cancel" onclick="closeParamModal()">Cancel</button>
      <button class="modal-btn primary" onclick="applyParam()">Apply</button>
    </div>
  </div>
</div>

<!-- ═══ DELETE CONFIRM MODAL ═══ -->
<div class="modal-overlay" id="delete-modal">
  <div class="modal-box">
    <div class="modal-title">Delete conversation?</div>
    <div class="modal-body" id="delete-modal-body">This cannot be undone.</div>
    <div class="modal-btns">
      <button class="modal-btn cancel" onclick="closeDeleteModal()">Cancel</button>
      <button class="modal-btn danger" id="delete-modal-confirm">Delete</button>
    </div>
  </div>
</div>

<!-- ═══ ADD PROMPT MODAL ═══ -->
<div class="modal-overlay" id="prompt-modal">
  <div class="modal-box">
    <div class="modal-title">Add Prompt</div>
    <div class="modal-label">Name</div>
    <input class="modal-input" id="prompt-modal-name" placeholder="e.g. Code Review" onkeydown="if(event.key==='Enter')document.getElementById('prompt-modal-text').focus()"/>
    <div class="modal-label">Prompt Text</div>
    <textarea class="modal-input" id="prompt-modal-text" rows="3" placeholder="Review this code for…"></textarea>
    <div class="modal-btns">
      <button class="modal-btn cancel" onclick="closePromptModal()">Cancel</button>
      <button class="modal-btn primary" onclick="savePromptModal()">Add</button>
    </div>
  </div>
</div>

<!-- ═══ MODEL INFO MODAL ═══ -->
<div class="modal-overlay" id="model-info-modal" onclick="if(event.target===this)this.classList.remove('open')">
  <div class="modal-box">
    <div class="modal-title" id="model-info-title">Model Info</div>
    <div id="model-info-content" style="margin-top:8px"></div>
    <div class="modal-btns" style="margin-top:16px">
      <button class="modal-btn cancel" onclick="document.getElementById('model-info-modal').classList.remove('open')">Close</button>
    </div>
  </div>
</div>

<!-- ═══ SEARCH ═══ -->
<div id="search-overlay" onclick="maybeCloseSearch(event)">
  <div class="search-box">
    <input type="text" id="search-input" placeholder="Search conversations…" oninput="doSearch(this.value)" onkeydown="searchKeydown(event)"/>
    <div id="search-results"></div>
  </div>
</div>

<div id="toast"><span class="toast-dot"></span><span id="toast-text"></span></div>

<script>
'use strict';

// ══════════════════════════════════════════════════════════════
// STATE
// ══════════════════════════════════════════════════════════════
const state = {
  chats: [], activeChatId: null,
  streaming: false, abortController: null,
  models: [], pendingFiles: [],
  config: {
    system_prompt: '', temperature: 0.7, context_window: 4096,
    memory: [], ollama_url: 'http://localhost:11434',
    theme: 'dark', accent: '#7c6ff7', font_size: 14,
    show_token_count: true,
    prompts: [
      { name: 'Code Review', text: 'Review this code for bugs, security issues, and improvements:' },
      { name: 'Explain Simply', text: "Explain this like I'm 5 years old:" },
      { name: 'Write Tests', text: 'Write comprehensive unit tests for:' },
      { name: 'Debug Helper', text: 'Help me debug this issue:' },
    ]
  },
  currentParam: null,
  lastAiContent: '',
  lastAiMessages: null,
};

// ══════════════════════════════════════════════════════════════
// DOM REFS
// ══════════════════════════════════════════════════════════════
const $messages    = document.getElementById('messages');
const $input       = document.getElementById('user-input');
const $sendBtn     = document.getElementById('send-btn');
const $sendIcon    = document.getElementById('send-icon');
const $stopIcon    = document.getElementById('stop-icon');
const $modelSelect = document.getElementById('model-select');
const $historyList = document.getElementById('history-list');
const $chatTitle   = document.getElementById('chat-title');
const $topbarModel = document.getElementById('topbar-model');
const $statusDot   = document.getElementById('status-dot');
const $statusText  = document.getElementById('status-text');
const $attachBtn   = document.getElementById('attach-btn');
const $fileInput   = document.getElementById('file-input');
const $previewBar  = document.getElementById('file-preview-bar');
const $ghostTyped  = document.querySelector('.ghost-typed');
const $ghostSug    = document.querySelector('.ghost-suggestion');
const $tabBadge    = document.getElementById('tab-badge');
const $tokenCtr    = document.getElementById('token-counter');
const $voiceBtn    = document.getElementById('voice-btn');

// ══════════════════════════════════════════════════════════════
// TOAST
// ══════════════════════════════════════════════════════════════
let toastTimer;
function showToast(msg, type='info') {
  const t=document.getElementById('toast');
  t.className = type==='success'?'show success':type==='error'?'show error':'show';
  document.getElementById('toast-text').textContent=msg;
  clearTimeout(toastTimer);
  toastTimer=setTimeout(()=>t.classList.remove('show'),2800);
}

// ══════════════════════════════════════════════════════════════
// CONFIRM MODAL (replaces window.confirm)
// ══════════════════════════════════════════════════════════════
function openDeleteModal(title, body, onConfirm) {
  document.getElementById('delete-modal').classList.add('open');
  if(body) document.getElementById('delete-modal-body').textContent = body;
  const btn = document.getElementById('delete-modal-confirm');
  btn.onclick = () => { closeDeleteModal(); onConfirm(); };
}
function closeDeleteModal() { document.getElementById('delete-modal').classList.remove('open'); }

// ══════════════════════════════════════════════════════════════
// PROMPT MODAL
// ══════════════════════════════════════════════════════════════
function openAddPromptModal() {
  document.getElementById('prompt-modal-name').value='';
  document.getElementById('prompt-modal-text').value='';
  document.getElementById('prompt-modal').classList.add('open');
  setTimeout(()=>document.getElementById('prompt-modal-name').focus(),100);
}
function closePromptModal() { document.getElementById('prompt-modal').classList.remove('open'); }
function savePromptModal() {
  const name=document.getElementById('prompt-modal-name').value.trim();
  const text=document.getElementById('prompt-modal-text').value.trim();
  if(!name||!text){showToast('Name and text required','error');return;}
  if(!state.config.prompts) state.config.prompts=[];
  state.config.prompts.push({name,text});
  renderPromptCards();
  closePromptModal();
  showToast('Prompt added','success');
}

// ══════════════════════════════════════════════════════════════
// CONFIG
// ══════════════════════════════════════════════════════════════
async function loadConfig() {
  try {
    const r = await fetch('/api/config');
    if(r.ok) state.config = {...state.config, ...await r.json()};
  } catch {}
  applyConfig();
}

async function saveSettings() {
  const cfg = state.config;
  cfg.temperature    = parseFloat(document.getElementById('s-temp').value);
  cfg.context_window = parseInt(document.getElementById('s-ctx').value);
  cfg.system_prompt  = document.getElementById('s-system').value.trim();
  cfg.ollama_url     = document.getElementById('s-url').value.trim();
  cfg.font_size      = parseInt(document.getElementById('s-fs').value);
  cfg.show_token_count = document.getElementById('s-tokens').checked;
  try {
    await fetch('/api/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(cfg)});
    applyConfig(); closeSettings(); showToast('Settings saved','success');
  } catch { showToast('Could not save settings','error'); }
}

function applyConfig() {
  const cfg=state.config, a=cfg.accent||'#7c6ff7';
  document.documentElement.style.setProperty('--accent',a);
  document.documentElement.style.setProperty('--accent-glow',hexToRgba(a,.2));
  document.documentElement.style.setProperty('--accent-dim',hexToRgba(a,.08));
  document.documentElement.style.setProperty('--accent-mid',hexToRgba(a,.14));
  document.documentElement.style.setProperty('--font-size',(cfg.font_size||14)+'px');
  document.getElementById('param-temp-display').textContent = cfg.temperature.toFixed(1);
  document.getElementById('param-ctx-display').textContent  = fmtCtx(cfg.context_window);
  $tokenCtr.style.display = cfg.show_token_count ? '' : 'none';
  applyTheme(cfg.theme==='light');
}

function hexToRgba(hex,a){
  const r=parseInt(hex.slice(1,3),16),g=parseInt(hex.slice(3,5),16),b=parseInt(hex.slice(5,7),16);
  return `rgba(${r},${g},${b},${a})`;
}
function fmtCtx(n){return n>=1024?Math.round(n/1024)+'K':n+''}

function openSettings(section) {
  const cfg=state.config;
  document.getElementById('s-temp').value=cfg.temperature;
  sliderUpdate(document.getElementById('s-temp'),'s-temp-val');
  document.getElementById('s-ctx').value=cfg.context_window;
  sliderUpdate(document.getElementById('s-ctx'),'s-ctx-val');
  document.getElementById('s-system').value=cfg.system_prompt||'';
  document.getElementById('s-url').value=cfg.ollama_url||'http://localhost:11434';
  document.getElementById('s-fs').value=cfg.font_size||14;
  sliderUpdate(document.getElementById('s-fs'),'s-fs-val',true);
  document.getElementById('s-tokens').checked=cfg.show_token_count!==false;
  renderMemoryList(); renderColorSwatches();
  document.getElementById('settings-overlay').classList.add('open');
  if(section==='system') setTimeout(()=>document.getElementById('s-system').focus(),200);
}
function closeSettings(){document.getElementById('settings-overlay').classList.remove('open');}
function maybeCloseSettings(e){if(e.target.id==='settings-overlay') closeSettings();}

function sliderUpdate(el,valId,px=false){
  const v=parseFloat(el.value),min=parseFloat(el.min),max=parseFloat(el.max);
  el.style.setProperty('--pct',((v-min)/(max-min)*100).toFixed(1)+'%');
  document.getElementById(valId).textContent=px?v+'px':(v%1===0?v:v.toFixed(2));
}

// ── ACCENT COLORS ──
const ACCENT_PRESETS=['#7c6ff7','#ec4899','#f59e0b','#10b981','#3b82f6','#ef4444','#f97316','#06b6d4'];
function renderColorSwatches(){
  const wrap=document.getElementById('color-swatches');
  wrap.innerHTML='';
  ACCENT_PRESETS.forEach(c=>{
    const s=document.createElement('div');
    s.className='color-swatch'+(state.config.accent===c?' active':'');
    s.style.background=c;
    s.onclick=()=>{state.config.accent=c;renderColorSwatches();applyConfig();};
    wrap.appendChild(s);
  });
}

// ── MEMORY ──
function renderMemoryList(){
  const list=document.getElementById('memory-list');list.innerHTML='';
  (state.config.memory||[]).forEach((m,i)=>{
    const item=document.createElement('div');item.className='memory-item';
    item.innerHTML=`<span class="memory-item-text">${escHtml(m)}</span><button class="memory-item-del" onclick="deleteMemory(${i})">✕</button>`;
    list.appendChild(item);
  });
}
function addMemory(){
  const inp=document.getElementById('memory-input');
  const v=inp.value.trim();if(!v)return;
  if(!state.config.memory) state.config.memory=[];
  state.config.memory.push(v);inp.value='';renderMemoryList();
}
function deleteMemory(i){state.config.memory.splice(i,1);renderMemoryList();}

// ══════════════════════════════════════════════════════════════
// PARAM MODAL
// ══════════════════════════════════════════════════════════════
function openParamModal(type){
  state.currentParam=type;
  const isTemp=type==='temp';
  const sl=document.getElementById('param-slider');
  document.getElementById('param-modal-title').textContent=isTemp?'Temperature':'Context Window';
  document.getElementById('param-label').childNodes[0].textContent=isTemp?'Creativity ':'Tokens ';
  sl.min=isTemp?0:512;sl.max=isTemp?2:131072;sl.step=isTemp?0.05:512;
  sl.value=isTemp?state.config.temperature:state.config.context_window;
  paramSliderUpdate();
  document.getElementById('param-modal').classList.add('open');
}
function closeParamModal(e){if(!e||e.target.id==='param-modal') document.getElementById('param-modal').classList.remove('open');}
function paramSliderUpdate(){
  const sl=document.getElementById('param-slider');
  const v=parseFloat(sl.value),min=parseFloat(sl.min),max=parseFloat(sl.max);
  sl.style.setProperty('--pct',((v-min)/(max-min)*100).toFixed(1)+'%');
  document.getElementById('param-val-display').textContent=state.currentParam==='temp'?v.toFixed(2):fmtCtx(v);
}
function applyParam(){
  const v=parseFloat(document.getElementById('param-slider').value);
  if(state.currentParam==='temp') state.config.temperature=v;
  else state.config.context_window=v;
  applyConfig();
  document.getElementById('param-modal').classList.remove('open');
  showToast('Updated','success');
}

// ══════════════════════════════════════════════════════════════
// THEME
// ══════════════════════════════════════════════════════════════
function applyTheme(light){
  document.documentElement.classList.toggle('light',light);
  document.getElementById('icon-moon').style.display=light?'none':'';
  document.getElementById('icon-sun').style.display=light?'':'none';
  state.config.theme=light?'light':'dark';
  localStorage.setItem('wl_theme',light?'light':'dark');
}
document.getElementById('theme-btn').addEventListener('click',()=>applyTheme(!document.documentElement.classList.contains('light')));

// ══════════════════════════════════════════════════════════════
// SIDEBAR TABS
// ══════════════════════════════════════════════════════════════
function switchSideTab(name,el){
  document.querySelectorAll('.sidebar-tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.sidebar-panel').forEach(p=>p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById(name+'-panel').classList.add('active');
  if(name==='models') renderModelCards();
}

// ══════════════════════════════════════════════════════════════
// CHAT TITLE (inline edit)
// ══════════════════════════════════════════════════════════════
$chatTitle.addEventListener('dblclick',()=>{
  $chatTitle.contentEditable='true';$chatTitle.focus();
  const sel=window.getSelection(),range=document.createRange();
  range.selectNodeContents($chatTitle);sel.removeAllRanges();sel.addRange(range);
});
$chatTitle.addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();$chatTitle.blur();}
  if(e.key==='Escape'){$chatTitle.contentEditable='false';}
});
$chatTitle.addEventListener('blur',async()=>{
  $chatTitle.contentEditable='false';
  const chat=getActiveChat();if(!chat)return;
  const nt=$chatTitle.textContent.trim()||'New Chat';
  chat.title=nt;await saveChat(chat);renderHistory();
});

// ══════════════════════════════════════════════════════════════
// SEARCH
// ══════════════════════════════════════════════════════════════
function openSearch(){
  document.getElementById('search-overlay').classList.add('open');
  setTimeout(()=>document.getElementById('search-input').focus(),50);
}
function maybeCloseSearch(e){if(e.target.id==='search-overlay') closeSearch();}
function closeSearch(){
  document.getElementById('search-overlay').classList.remove('open');
  document.getElementById('search-input').value='';
  document.getElementById('search-results').innerHTML='';
}
function doSearch(q){
  const res=document.getElementById('search-results');
  if(!q.trim()){res.innerHTML='';return;}
  const matches=[];const lq=q.toLowerCase();
  state.chats.forEach(chat=>{
    let preview='';
    chat.messages.forEach(m=>{
      if(m.content&&m.content.toLowerCase().includes(lq)){
        const idx=m.content.toLowerCase().indexOf(lq);
        preview=m.content.slice(Math.max(0,idx-30),idx+80);
      }
    });
    if(chat.title.toLowerCase().includes(lq)||preview) matches.push({chat,preview});
  });
  if(!matches.length){res.innerHTML='<div class="search-empty">No results found</div>';return;}
  res.innerHTML=matches.map(({chat,preview})=>`
    <div class="search-result-item" onclick="switchChat('${chat.id}');closeSearch()">
      <div class="search-result-title">${escHtml(chat.title)}</div>
      ${preview?`<div class="search-result-preview">${escHtml(preview).replace(new RegExp(escHtml(q),'gi'),m=>`<mark>${m}</mark>`)}</div>`:''}
    </div>`).join('');
}
function searchKeydown(e){if(e.key==='Escape') closeSearch();}

// ══════════════════════════════════════════════════════════════
// PROMPTS
// ══════════════════════════════════════════════════════════════
function renderPromptCards(){
  const wrap=document.getElementById('prompt-cards');wrap.innerHTML='';
  (state.config.prompts||[]).forEach((p,i)=>{
    const card=document.createElement('div');card.className='prompt-card';
    card.innerHTML=`
      <div class="prompt-card-name">${escHtml(p.name)}</div>
      <div class="prompt-card-preview">${escHtml(p.text)}</div>
      <div class="prompt-card-actions">
        <button class="prompt-card-del" onclick="event.stopPropagation();deletePrompt(${i})">Remove</button>
      </div>`;
    card.onclick=()=>{$input.value=p.text+' ';$input.focus();autoResize();};
    wrap.appendChild(card);
  });
}
function deletePrompt(i){
  openDeleteModal('Delete prompt?','Remove this saved prompt?',()=>{
    state.config.prompts.splice(i,1);renderPromptCards();showToast('Prompt removed');
  });
}

// ══════════════════════════════════════════════════════════════
// MODELS PANEL
// ══════════════════════════════════════════════════════════════
function renderModelCards(){
  const wrap=document.getElementById('model-cards');wrap.innerHTML='';
  if(!state.models.length){wrap.innerHTML='<div style="padding:12px;text-align:center;color:var(--text3);font-size:12px">No models found</div>';return;}
  state.models.forEach(m=>{
    const card=document.createElement('div');card.className='model-card';
    card.innerHTML=`
      <div class="model-card-top">
        <div class="model-card-name">${escHtml(m)}</div>
        <div class="model-card-actions">
          <button class="model-card-btn info" onclick="event.stopPropagation();showModelInfo('${m}')" title="Info">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          </button>
          <button class="model-card-btn" onclick="event.stopPropagation();deleteModel('${m}')" title="Remove">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
          </button>
        </div>
      </div>`;
    card.addEventListener('click',()=>{$modelSelect.value=m;$topbarModel.textContent=m;showToast('Switched to '+m,'success');});
    wrap.appendChild(card);
  });
}

async function showModelInfo(name){
  document.getElementById('model-info-title').textContent=name;
  document.getElementById('model-info-content').innerHTML='<div style="color:var(--text3);font-size:12px;padding:8px 0">Loading…</div>';
  document.getElementById('model-info-modal').classList.add('open');
  try{
    const r=await fetch('/api/model-info',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
    if(!r.ok) throw new Error('Not found');
    const d=await r.json();
    const rows=[];
    if(d.details){
      const det=d.details;
      if(det.family) rows.push(['Family',det.family]);
      if(det.parameter_size) rows.push(['Parameters',det.parameter_size]);
      if(det.quantization_level) rows.push(['Quantization',det.quantization_level]);
      if(det.format) rows.push(['Format',det.format]);
    }
    if(d.model_info){
      const mi=d.model_info;
      const ctx=mi['llama.context_length']||mi['context_length'];
      if(ctx) rows.push(['Context Length',ctx.toLocaleString()+' tokens']);
    }
    if(d.size) rows.push(['Size',Math.round(d.size/1024/1024/1024*10)/10+' GB']);
    const html=rows.length
      ? rows.map(([k,v])=>`<div class="model-info-row"><span class="model-info-key">${k}</span><span class="model-info-val">${v}</span></div>`).join('')
      : '<div style="color:var(--text3);font-size:12px">No details available</div>';
    document.getElementById('model-info-content').innerHTML=html;
  }catch{
    document.getElementById('model-info-content').innerHTML='<div style="color:var(--text3);font-size:12px">Could not load model info</div>';
  }
}

async function pullModel(){
  const name=document.getElementById('pull-input').value.trim();if(!name)return;
  const prog=document.getElementById('pull-progress');
  prog.style.display='block';prog.textContent='Pulling '+name+'…';
  document.getElementById('pull-btn').disabled=true;
  try{
    const resp=await fetch('/api/pull',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:name})});
    const reader=resp.body.getReader(),dec=new TextDecoder();let buf='';
    while(true){
      const{done,value}=await reader.read();if(done)break;
      buf+=dec.decode(value,{stream:true});
      const lines=buf.split('\n');buf=lines.pop();
      for(const l of lines){
        if(!l.trim())continue;
        try{const o=JSON.parse(l);if(o.status) prog.textContent=o.status+(o.completed&&o.total?` ${Math.round(o.completed/o.total*100)}%`:'');}catch{}
      }
    }
    prog.textContent='✓ Done!';
    await loadModels();renderModelCards();showToast('Pulled: '+name,'success');
    document.getElementById('pull-input').value='';
  }catch(e){prog.textContent='Error: '+e.message;showToast('Pull failed','error');}
  document.getElementById('pull-btn').disabled=false;
}

async function deleteModel(name){
  openDeleteModal('Remove model?',`Remove "${name}"? This cannot be undone.`,async()=>{
    try{
      await fetch(state.config.ollama_url+'/api/delete',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})});
      await loadModels();renderModelCards();showToast('Removed: '+name,'success');
    }catch{showToast('Could not remove model','error');}
  });
}

// ══════════════════════════════════════════════════════════════
// TOKEN COUNTER
// ══════════════════════════════════════════════════════════════
function countTokensApprox(chat){
  let chars=0;(chat.messages||[]).forEach(m=>{if(m.content)chars+=m.content.length;});
  return Math.round(chars/4);
}
function updateTokenCounter(){
  if(!state.config.show_token_count)return;
  const chat=getActiveChat();
  if(!chat){$tokenCtr.style.display='none';return;}
  $tokenCtr.style.display='';
  $tokenCtr.textContent='~'+countTokensApprox(chat).toLocaleString()+' tokens';
}

// ══════════════════════════════════════════════════════════════
// EXPORT
// ══════════════════════════════════════════════════════════════
async function exportCurrentChat(){
  const chat=getActiveChat();if(!chat){showToast('No active chat','error');return;}
  try{
    const r=await fetch('/api/chats/'+chat.id+'/export');
    const md=await r.text();
    const a=document.createElement('a');
    a.href=URL.createObjectURL(new Blob([md],{type:'text/markdown'}));
    a.download=(chat.title||'chat').replace(/[^\w\s-]/g,'').replace(/\s+/g,'-')+'.md';
    a.click();showToast('Exported','success');
  }catch{showToast('Export failed','error');}
}
function exportChatById(id){state.activeChatId=id;exportCurrentChat();}

// ══════════════════════════════════════════════════════════════
// VOICE INPUT
// ══════════════════════════════════════════════════════════════
let recognition=null;
function initVoice(){
  const SpeechRec=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SpeechRec){$voiceBtn.style.display='none';return;}
  recognition=new SpeechRec();
  recognition.continuous=false;recognition.interimResults=true;recognition.lang='en-US';
  recognition.onstart=()=>{$voiceBtn.classList.add('active');showToast('Listening…');};
  recognition.onresult=e=>{
    let final='',interim='';
    for(const r of e.results){if(r.isFinal)final+=r[0].transcript;else interim+=r[0].transcript;}
    $input.value=($input.value+final).trimStart();
    autoResize();
  };
  recognition.onend=()=>{$voiceBtn.classList.remove('active');};
  recognition.onerror=()=>{$voiceBtn.classList.remove('active');showToast('Voice error','error');};
}
$voiceBtn.addEventListener('click',()=>{
  if(!recognition){showToast('Speech not supported in this browser','error');return;}
  if($voiceBtn.classList.contains('active')){recognition.stop();}
  else{recognition.start();}
});

// ══════════════════════════════════════════════════════════════
// SEND / STOP
// ══════════════════════════════════════════════════════════════
function setStreamingUI(streaming){
  state.streaming=streaming;
  $sendBtn.classList.toggle('send-mode',!streaming);
  $sendBtn.classList.toggle('stop-mode',streaming);
  $sendIcon.style.display=streaming?'none':'';
  $stopIcon.style.display=streaming?'':'none';
  $sendBtn.title=streaming?'Stop generating':'Send (Enter)';
}
function stopGeneration(){if(state.abortController) state.abortController.abort();}
$sendBtn.addEventListener('click',()=>{if(state.streaming)stopGeneration();else sendMessage();});

// ══════════════════════════════════════════════════════════════
// STORAGE
// ══════════════════════════════════════════════════════════════
function getActiveChat(){return state.chats.find(c=>c.id===state.activeChatId);}
async function saveChat(chat){
  await fetch('/api/chats/'+chat.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(chat)});
}
async function loadChats(){const res=await fetch('/api/chats');state.chats=await res.json();}
async function apiDeleteChat(id){await fetch('/api/chats/'+id,{method:'DELETE'});}

// ══════════════════════════════════════════════════════════════
// AUTOCOMPLETE
// ══════════════════════════════════════════════════════════════
const AC_SUGGESTIONS=[
  'Explain how ','Write a Python function to ','What is the difference between ',
  'Help me debug ','Summarize this: ','Translate to ','Write a regex to ',
  'How do I ','Give me an example of ','What are the best practices for ',
  'Refactor this code: ','Write unit tests for ','Create a bash script to ',
];
let acSuggestion='';
function updateAutocomplete(){
  const v=$input.value;if(!v||v.length<3){clearAutocomplete();return;}
  const lv=v.toLowerCase();
  const match=AC_SUGGESTIONS.find(s=>s.toLowerCase().startsWith(lv)&&s.length>v.length);
  if(match){acSuggestion=match.slice(v.length);$ghostTyped.textContent=v;$ghostSug.textContent=acSuggestion;$tabBadge.classList.add('visible');}
  else clearAutocomplete();
}
function clearAutocomplete(){acSuggestion='';$ghostTyped.textContent='';$ghostSug.textContent='';$tabBadge.classList.remove('visible');}
function acceptAutocomplete(){if(!acSuggestion)return false;$input.value+=acSuggestion;autoResize();clearAutocomplete();return true;}

// ══════════════════════════════════════════════════════════════
// TEXTAREA
// ══════════════════════════════════════════════════════════════
function autoResize(){$input.style.height='auto';$input.style.height=Math.min($input.scrollHeight,200)+'px';}
$input.addEventListener('input',()=>{autoResize();updateAutocomplete();});
$input.addEventListener('keydown',e=>{
  if(e.key==='Tab'){e.preventDefault();acceptAutocomplete();return;}
  if(e.key==='Escape'){clearAutocomplete();return;}
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
});
$input.addEventListener('blur',clearAutocomplete);

// ══════════════════════════════════════════════════════════════
// FILES + DRAG & DROP
// ══════════════════════════════════════════════════════════════
$attachBtn.addEventListener('click',()=>$fileInput.click());
$fileInput.addEventListener('change',async()=>{
  for(const f of Array.from($fileInput.files)) await processFile(f);
  $fileInput.value='';renderPreviewBar();
});
const $inputWrap=document.getElementById('input-wrap');
['dragover','dragleave','drop'].forEach(ev=>{
  document.getElementById('input-area').addEventListener(ev,e=>{
    e.preventDefault();
    if(ev==='dragover') $inputWrap.classList.add('drag-over');
    else if(ev==='dragleave') $inputWrap.classList.remove('drag-over');
    else{$inputWrap.classList.remove('drag-over');Array.from(e.dataTransfer.files).forEach(f=>processFile(f));renderPreviewBar();}
  });
});

async function processFile(file){
  if(file.size>20*1024*1024){showToast(file.name+' too large (max 20MB)','error');return;}
  if(file.type.startsWith('image/')){
    state.pendingFiles.push({name:file.name,type:'image',dataURL:await readAsDataURL(file)});
  } else if(file.type==='application/pdf'){
    const b64=(await readAsDataURL(file)).split(',')[1];
    try{
      const d=await(await fetch('/api/extract-pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base64:b64,name:file.name})})).json();
      state.pendingFiles.push({name:file.name,type:'pdf',textContent:d.text});
      showToast('PDF extracted','success');
    }catch{showToast('Could not extract PDF','error');}
  } else {
    state.pendingFiles.push({name:file.name,type:'text',textContent:await readAsText(file)});
    showToast('File attached: '+file.name,'success');
  }
}
const readAsDataURL=f=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=rej;r.readAsDataURL(f);});
const readAsText  =f=>new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=rej;r.readAsText(f);});

function renderPreviewBar(){
  $previewBar.innerHTML='';
  if(!state.pendingFiles.length){$previewBar.classList.remove('visible');return;}
  $previewBar.classList.add('visible');
  state.pendingFiles.forEach((f,i)=>{
    const chip=document.createElement('div');chip.className='file-chip';
    if(f.type==='image'){const img=document.createElement('img');img.className='file-chip-thumb';img.src=f.dataURL;chip.appendChild(img);}
    else{const icon=document.createElement('div');icon.className='file-chip-icon';icon.innerHTML=f.type==='pdf'?PDF_ICON:CODE_ICON;chip.appendChild(icon);}
    const nm=document.createElement('span');nm.className='file-chip-name';nm.textContent=f.name;chip.appendChild(nm);
    const rm=document.createElement('button');rm.className='file-chip-remove';rm.innerHTML=X_ICON;
    rm.addEventListener('click',()=>{state.pendingFiles.splice(i,1);renderPreviewBar();});
    chip.appendChild(rm);$previewBar.appendChild(chip);
  });
}

// ══════════════════════════════════════════════════════════════
// SVG ICONS
// ══════════════════════════════════════════════════════════════
const COPY_SVG='<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
const CHECK_SVG='<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>';
const REGEN_SVG='<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-4.5"/></svg>';
const DL_SVG='<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
const PDF_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
const CODE_ICON='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';
const X_ICON='<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

// ══════════════════════════════════════════════════════════════
// MARKDOWN with highlight.js
// ══════════════════════════════════════════════════════════════
function renderMarkdown(text){
  let h=text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    // tables
    .replace(/^\|(.+)\|\s*\n\|[-| :]+\|\s*\n((?:\|.+\|\s*\n?)*)/gm,(_,hdr,body)=>{
      const ths=hdr.split('|').filter(c=>c.trim()).map(c=>`<th>${c.trim()}</th>`).join('');
      const rows=body.trim().split('\n').map(r=>`<tr>${r.split('|').filter(c=>c.trim()).map(c=>`<td>${c.trim()}</td>`).join('')}</tr>`).join('');
      return `<table><thead><tr>${ths}</tr></thead><tbody>${rows}</tbody></table>`;
    })
    // fenced code blocks
    .replace(/```(\w*)\n?([\s\S]*?)```/g,(_,lang,code)=>{
      const raw=code.trim();
      let highlighted;
      try{
        if(lang&&hljs.getLanguage(lang)) highlighted=hljs.highlight(raw,{language:lang}).value;
        else highlighted=hljs.highlightAuto(raw).value;
      }catch{highlighted=raw;}
      const langLabel=lang||'code';
      return `<div class="code-block-wrap"><div class="code-block-header"><span class="code-lang">${langLabel}</span><button class="code-copy-btn" onclick="copyCode(this)">${COPY_SVG} Copy</button></div><pre><code class="hljs">${highlighted}</code></pre></div>`;
    })
    .replace(/`([^`\n]+)`/g,'<code>$1</code>')
    .replace(/^&gt; (.+)$/gm,'<blockquote>$1</blockquote>')
    .replace(/^---+$/gm,'<hr>')
    .replace(/\*\*\*(.+?)\*\*\*/g,'<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/~~(.+?)~~/g,'<del>$1</del>')
    .replace(/\[(.+?)\]\((.+?)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>')
    .replace(/^## (.+)$/gm,'<h2>$1</h2>')
    .replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/^\s*[-*] (.+)$/gm,'<li>$1</li>')
    .replace(/(<li>.*?<\/li>(\n|$))+/gs,m=>`<ul>${m}</ul>`)
    .replace(/^\d+\. (.+)$/gm,'<li>$1</li>')
    .replace(/\n\n+/g,'</p><p>')
    .replace(/\n/g,'<br>');
  return `<p>${h}</p>`;
}

function copyCode(btn){
  const code=btn.closest('.code-block-wrap').querySelector('code').textContent;
  navigator.clipboard.writeText(code).then(()=>{
    btn.innerHTML=CHECK_SVG+' Copied!';btn.classList.add('copied');
    setTimeout(()=>{btn.innerHTML=COPY_SVG+' Copy';btn.classList.remove('copied');},2000);
  });
}

function escHtml(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ══════════════════════════════════════════════════════════════
// RENDER MESSAGES
// ══════════════════════════════════════════════════════════════
function renderMessages(){
  const chat=getActiveChat();
  if(!chat||!chat.messages.filter(m=>m.role!=='system').length){
    $messages.innerHTML='';$messages.appendChild(buildEmptyState());return;
  }
  $messages.innerHTML='';
  const msgs=chat.messages.filter(m=>m.role!=='system');
  let i=0;
  while(i<msgs.length){
    const m=msgs[i];
    if(m.role==='user'){
      appendUserMessage(m.content,m.images,m.fileChips);i++;
    } else if(m.role==='assistant'){
      const el=appendAiMessage(m.content,false);
      // store last for regenerate
      if(i===msgs.length-1){state.lastAiContent=m.content;}
      i++;
    } else i++;
  }
  scrollBottom();updateTokenCounter();
}

function buildEmptyState(){
  const d=document.createElement('div');d.id='empty-state';
  const model=$modelSelect.value||'your model';
  d.innerHTML=`
    <div class="empty-logo">
      <svg viewBox="0 0 24 24" fill="none" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 3 C9.5 3 7.5 4.5 7 6.5 C6 6.2 5 6.8 4.5 7.8 C4 8.8 4.3 10 5 10.6 C4.8 11.2 4.8 11.8 5 12.4 C5 15 6.5 17.5 9 18.5 L9 21 L11 21 L11 19 L13 19 L13 21 L15 21 L15 18.5 C17.5 17.5 19 15 19 12.4 C19.5 11.6 19.5 10.6 19 9.8 C19.8 9 19.8 7.6 19 6.8 C18.2 6 17 6 16.2 6.6 C15.5 4.5 13.8 3 12 3Z" stroke-width="1.5"/>
      </svg>
    </div>
    <div class="empty-title">WildLlama</div>
    <div class="empty-sub">Running <strong style="color:var(--accent)">${escHtml(model)}</strong> locally</div>
    <div class="empty-pills">
      <div class="e-pill" onclick="useSuggestion(this)">Explain a concept</div>
      <div class="e-pill" onclick="useSuggestion(this)">Write a Python function</div>
      <div class="e-pill" onclick="useSuggestion(this)">Debug my code</div>
      <div class="e-pill" onclick="useSuggestion(this)">Summarize a document</div>
      <div class="e-pill" onclick="useSuggestion(this)">Write me a regex</div>
      <div class="e-pill" onclick="useSuggestion(this)">Translate to Spanish</div>
    </div>`;
  return d;
}

function appendUserMessage(content,images=[],fileChips=[]){
  const group=document.createElement('div');group.className='msg-group';
  const wrap=document.createElement('div');wrap.className='user-msg-wrap';
  const bubble=document.createElement('div');bubble.className='user-bubble';
  if(images&&images.length) images.forEach(src=>{const img=document.createElement('img');img.className='bubble-img';img.src=src;bubble.appendChild(img);});
  if(fileChips&&fileChips.length) fileChips.forEach(fc=>{
    const c=document.createElement('div');c.className='bubble-file-chip';
    c.innerHTML=PDF_ICON+' '+escHtml(fc);bubble.appendChild(c);
  });
  const p=document.createElement('p');p.textContent=content;bubble.appendChild(p);
  wrap.appendChild(bubble);group.appendChild(wrap);$messages.appendChild(group);
  scrollBottom();
}

function appendAiMessage(content,streaming=false){
  const group=document.createElement('div');group.className='msg-group';
  const wrap=document.createElement('div');wrap.className='ai-msg-wrap';

  const avatar=document.createElement('div');avatar.className='ai-avatar';
  avatar.innerHTML='<svg viewBox="0 0 24 24" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 C9.5 3 7.5 4.5 7 6.5 C6 6.2 5 6.8 4.5 7.8 C4 8.8 4.3 10 5 10.6 C4.8 11.2 4.8 11.8 5 12.4 C5 15 6.5 17.5 9 18.5 L9 21 L11 21 L11 19 L13 19 L13 21 L15 21 L15 18.5 C17.5 17.5 19 15 19 12.4 C19.5 11.6 19.5 10.6 19 9.8 C19.8 9 19.8 7.6 19 6.8 C18.2 6 17 6 16.2 6.6 C15.5 4.5 13.8 3 12 3Z"/></svg>';

  const col=document.createElement('div');col.style.flex='1';col.style.minWidth='0';
  const bubble=document.createElement('div');bubble.className='ai-bubble';

  if(streaming) bubble.innerHTML='<div class="thinking"><span></span><span></span><span></span></div>';
  else bubble.innerHTML=renderMarkdown(content);

  col.appendChild(bubble);
  wrap.appendChild(avatar);wrap.appendChild(col);
  group.appendChild(wrap);

  if(!streaming){
    const actions=buildMessageActions(content,group);
    col.appendChild(actions);
  }

  $messages.appendChild(group);scrollBottom();
  return bubble;
}

function buildMessageActions(content,group){
  const a=document.createElement('div');a.className='msg-actions';
  const mk=(svg,label,cls,fn)=>{
    const b=document.createElement('button');b.className='msg-action-btn'+(cls?' '+cls:'');
    b.innerHTML=svg+' '+label;b.addEventListener('click',fn);return b;
  };
  const copyBtn=mk(COPY_SVG,'Copy','',()=>{
    navigator.clipboard.writeText(content).then(()=>{
      copyBtn.innerHTML=CHECK_SVG+' Copied!';copyBtn.classList.add('copied');
      setTimeout(()=>{copyBtn.innerHTML=COPY_SVG+' Copy';copyBtn.classList.remove('copied');},2000);
    });
  });
  const regenBtn=mk(REGEN_SVG,'Regenerate','',()=>regenerateLast(group));
  const dlBtn=mk(DL_SVG,'Save','',()=>{
    const blob=new Blob([content],{type:'text/markdown'});
    const url=URL.createObjectURL(blob);const aa=document.createElement('a');
    aa.href=url;aa.download='wildllama-response-'+Date.now()+'.md';aa.click();
    showToast('Saved','success');
  });
  a.appendChild(copyBtn);a.appendChild(regenBtn);a.appendChild(dlBtn);
  return a;
}

// ══════════════════════════════════════════════════════════════
// REGENERATE
// ══════════════════════════════════════════════════════════════
async function regenerateLast(groupEl){
  const chat=getActiveChat();if(!chat||state.streaming)return;
  // remove last assistant message from state
  const msgs=chat.messages;
  if(msgs[msgs.length-1]?.role==='assistant'){
    msgs.pop();await saveChat(chat);
  }
  // remove group from DOM
  if(groupEl&&groupEl.parentNode) groupEl.parentNode.removeChild(groupEl);
  // re-send
  await streamResponse(chat);
}

// ══════════════════════════════════════════════════════════════
// HISTORY GROUPING (smarter)
// ══════════════════════════════════════════════════════════════
function renderHistory(){
  $historyList.innerHTML='';
  if(!state.chats.length){
    $historyList.innerHTML='<div style="padding:20px;text-align:center;color:var(--text3);font-size:12px">No conversations yet</div>';return;
  }
  const now=Date.now(),day=86400000;
  const groups={'Today':[],'Yesterday':[],'This Week':[],'This Month':[],'Older':[]};
  [...state.chats].reverse().forEach(chat=>{
    const age=now-(chat.createdAt||0);
    let g;
    if(age<day) g='Today';
    else if(age<2*day) g='Yesterday';
    else if(age<7*day) g='This Week';
    else if(age<30*day) g='This Month';
    else g='Older';
    groups[g].push(chat);
  });
  Object.entries(groups).forEach(([label,chats])=>{
    if(!chats.length)return;
    const lbl=document.createElement('div');lbl.className='history-group-label';lbl.textContent=label;
    $historyList.appendChild(lbl);
    chats.forEach(chat=>{
      const item=document.createElement('div');
      item.className='history-item'+(chat.id===state.activeChatId?' active':'');
      item.innerHTML=`
        <div class="history-item-title">${escHtml(chat.title||'New Chat')}</div>
        <div class="history-item-meta">${escHtml(chat.model||'')}</div>
        <div class="history-item-actions">
          <button class="history-action-btn export" title="Export" onclick="event.stopPropagation();exportChatById('${chat.id}')">
            ${DL_SVG}
          </button>
          <button class="history-action-btn" title="Delete" onclick="event.stopPropagation();deleteChatUI('${chat.id}')">
            ${X_ICON}
          </button>
        </div>`;
      item.addEventListener('click',()=>switchChat(chat.id));
      $historyList.appendChild(item);
    });
  });
}

// ══════════════════════════════════════════════════════════════
// CHAT MANAGEMENT
// ══════════════════════════════════════════════════════════════
function makeTitle(text){return text.trim().replace(/[^\w\s]/g,'').split(/\s+/).filter(Boolean).slice(0,5).join(' ')||'New Chat';}

async function createNewChat(){
  const id=Date.now().toString();
  const model=$modelSelect.value||'';
  const chat={id,title:'New Chat',model,messages:[],createdAt:Date.now()};
  const mem=(state.config.memory||[]).join('\n');
  if(mem||state.config.system_prompt){
    const sysParts=[];
    if(state.config.system_prompt) sysParts.push(state.config.system_prompt);
    if(mem) sysParts.push('User context:\n'+mem);
    chat.messages.push({role:'system',content:sysParts.join('\n\n')});
  }
  state.chats.push(chat);await saveChat(chat);switchChat(id);
}

function switchChat(id){
  state.activeChatId=id;const chat=getActiveChat();
  $chatTitle.textContent=chat?chat.title:'New Conversation';
  $topbarModel.textContent=chat?(chat.model||'—'):'—';
  renderMessages();renderHistory();updateTokenCounter();
}

async function deleteChatUI(id){
  const chat=state.chats.find(c=>c.id===id);
  const title=chat?chat.title:'this conversation';
  openDeleteModal('Delete conversation?',`Delete "${title}"? This cannot be undone.`,async()=>{
    state.chats=state.chats.filter(c=>c.id!==id);
    await apiDeleteChat(id);
    if(state.activeChatId===id){
      if(state.chats.length) switchChat(state.chats[state.chats.length-1].id);
      else{state.activeChatId=null;$chatTitle.textContent='New Conversation';$topbarModel.textContent='—';renderMessages();}
    }
    renderHistory();showToast('Conversation deleted');
  });
}

// ══════════════════════════════════════════════════════════════
// MODELS
// ══════════════════════════════════════════════════════════════
async function loadModels(){
  try{
    const data=await(await fetch('/api/models')).json();
    state.models=data.models||[];
    $modelSelect.innerHTML='';
    if(!state.models.length){$modelSelect.innerHTML='<option value="">No models found</option>';setStatus(false,'No models');return;}
    state.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;$modelSelect.appendChild(o);});
    setStatus(true,'Ollama connected');$topbarModel.textContent=$modelSelect.value;
  }catch{$modelSelect.innerHTML='<option value="">Ollama not running</option>';setStatus(false,'Ollama offline');}
}
function setStatus(online,text){
  $statusDot.className='status-dot '+(online?'online':'offline');
  $statusText.textContent=text;
}
$modelSelect.addEventListener('change',()=>{
  $topbarModel.textContent=$modelSelect.value;
  const chat=getActiveChat();if(chat){chat.model=$modelSelect.value;saveChat(chat);}
});

// ══════════════════════════════════════════════════════════════
// SEND MESSAGE
// ══════════════════════════════════════════════════════════════
async function sendMessage(){
  const text=$input.value.trim(),files=[...state.pendingFiles];
  if(!text&&!files.length)return;
  const model=$modelSelect.value;
  if(!model){showToast('No model selected','error');return;}
  if(!state.activeChatId) await createNewChat();
  const chat=getActiveChat();
  const es=document.getElementById('empty-state');if(es)es.remove();

  let fullContent=text;
  const imageDataURLs=[],fileChipNames=[];
  for(const f of files){
    if(f.type==='image') imageDataURLs.push(f.dataURL);
    else{fileChipNames.push(f.name);fullContent+=`\n\n---\n**File: ${f.name}**\n\`\`\`\n${f.textContent}\n\`\`\``;}
  }

  const userMsg={role:'user',content:fullContent,images:imageDataURLs.length?imageDataURLs:undefined,fileChips:fileChipNames.length?fileChipNames:undefined};
  chat.messages.push(userMsg);
  if(chat.title==='New Chat'){chat.title=makeTitle(text||files[0]?.name||'Attachment');$chatTitle.textContent=chat.title;}
  await saveChat(chat);
  appendUserMessage(fullContent,imageDataURLs,fileChipNames);
  renderHistory();

  $input.value='';$input.style.height='auto';
  state.pendingFiles=[];renderPreviewBar();clearAutocomplete();

  await streamResponse(chat);
}

async function streamResponse(chat){
  setStreamingUI(true);
  const aiBubble=appendAiMessage('',true);
  let fullResponse='';
  state.abortController=new AbortController();

  try{
    const apiMessages=chat.messages.map(m=>{
      const msg={role:m.role,content:m.content};
      if(m.images&&m.images.length) msg.images=m.images.map(d=>typeof d==='string'&&d.startsWith('data:')?d.split(',')[1]:d);
      return msg;
    });
    const response=await fetch('/api/chat',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({
        model:$modelSelect.value,
        messages:apiMessages,
        options:{temperature:state.config.temperature,num_ctx:state.config.context_window}
      }),
      signal:state.abortController.signal
    });
    if(!response.ok) throw new Error('Chat request failed');
    const reader=response.body.getReader(),decoder=new TextDecoder();
    let buffer='';
    aiBubble.innerHTML='<span class="cursor"></span>';
    while(true){
      const{done,value}=await reader.read();if(done)break;
      buffer+=decoder.decode(value,{stream:true});
      const lines=buffer.split('\n');buffer=lines.pop();
      for(const line of lines){
        if(!line.trim())continue;
        try{
          const obj=JSON.parse(line);
          if(obj.message?.content){fullResponse+=obj.message.content;aiBubble.innerHTML=renderMarkdown(fullResponse)+'<span class="cursor"></span>';scrollBottom();}
          if(obj.done) aiBubble.innerHTML=renderMarkdown(fullResponse);
        }catch{}
      }
    }
    aiBubble.innerHTML=renderMarkdown(fullResponse);
    const group=aiBubble.closest('.msg-group');
    const col=aiBubble.parentNode;
    const actions=buildMessageActions(fullResponse,group);
    col.appendChild(actions);
    chat.messages.push({role:'assistant',content:fullResponse});
    state.lastAiContent=fullResponse;
    await saveChat(chat);
    updateTokenCounter();
  }catch(e){
    if(e.name==='AbortError'){
      if(fullResponse){
        aiBubble.innerHTML=renderMarkdown(fullResponse);
        const group=aiBubble.closest('.msg-group');
        const col=aiBubble.parentNode;
        const stopped=document.createElement('em');stopped.style.cssText='font-size:11px;color:var(--text3);margin-left:6px';stopped.textContent='[stopped]';
        aiBubble.appendChild(stopped);
        col.appendChild(buildMessageActions(fullResponse,group));
        chat.messages.push({role:'assistant',content:fullResponse});await saveChat(chat);
      } else {
        aiBubble.innerHTML='<em style="color:var(--text3);font-size:13px">Stopped.</em>';
      }
    } else {
      aiBubble.innerHTML='<em style="color:var(--danger)">Could not reach Ollama. Make sure it\'s running: <code>ollama serve</code></em>';
    }
  }
  setStreamingUI(false);state.abortController=null;scrollBottom();
}

function scrollBottom(){$messages.scrollTop=$messages.scrollHeight;}
function useSuggestion(el){$input.value=el.textContent;$input.dispatchEvent(new Event('input'));$input.focus();}

// ══════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS
// ══════════════════════════════════════════════════════════════
document.addEventListener('keydown',e=>{
  if(e.ctrlKey&&e.key==='f'){e.preventDefault();openSearch();}
  if(e.ctrlKey&&e.key==='k'){e.preventDefault();createNewChat();}
  if(e.ctrlKey&&e.key===','){e.preventDefault();openSettings();}
  if(e.key==='Escape'){
    closeSearch();
    closeDeleteModal();
    closePromptModal();
    document.getElementById('model-info-modal').classList.remove('open');
  }
});

document.getElementById('new-chat-btn').addEventListener('click',createNewChat);

// ══════════════════════════════════════════════════════════════
// INIT
// ══════════════════════════════════════════════════════════════
(async()=>{
  const savedTheme=localStorage.getItem('wl_theme');
  applyTheme(savedTheme==='light');
  await loadConfig();
  await loadModels();
  await loadChats();
  renderPromptCards();
  initVoice();
  if(state.chats.length) switchChat(state.chats[state.chats.length-1].id);
  else{renderMessages();renderHistory();}
  $input.focus();
})();
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, ct="text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_GET(self):
        p = self.path.split("?")[0]

        if p in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif p == "/api/models":
            try:
                cfg = load_config()
                base = cfg.get("ollama_url", OLLAMA_BASE)
                with urllib.request.urlopen(f"{base}/api/tags", timeout=5) as r:
                    data = json.loads(r.read())
                self.send_json({"models": [m["name"] for m in data.get("models", [])]})
            except Exception as e:
                self.send_json({"models": [], "error": str(e)}, 503)

        elif p == "/api/chats":
            self.send_json(load_all_chats())

        elif p == "/api/config":
            self.send_json(load_config())

        elif p.startswith("/api/chats/") and p.endswith("/export"):
            chat_id = p[len("/api/chats/"):-len("/export")]
            chats = load_all_chats()
            chat = next((c for c in chats if c["id"] == chat_id), None)
            if chat:
                self.send_text(export_chat_md(chat), ct="text/markdown; charset=utf-8")
            else:
                self.send_response(404); self.end_headers()

        else:
            self.send_response(404); self.end_headers()

    def do_PUT(self):
        p = self.path
        if p.startswith("/api/chats/"):
            save_chat(json.loads(self.read_body()))
            self.send_json({"ok": True})
        elif p == "/api/config":
            cfg = json.loads(self.read_body())
            save_config(cfg)
            self.send_json({"ok": True})
        else:
            self.send_response(404); self.end_headers()

    def do_DELETE(self):
        if self.path.startswith("/api/chats/"):
            delete_chat(self.path[len("/api/chats/"):])
            self.send_json({"ok": True})
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        p = self.path

        if p == "/api/chat":
            body = json.loads(self.read_body())
            cfg = load_config()
            base = cfg.get("ollama_url", OLLAMA_BASE)
            payload = json.dumps({
                "model": body.get("model", ""),
                "messages": body.get("messages", []),
                "stream": True,
                "options": body.get("options", {})
            }).encode()
            try:
                req = urllib.request.Request(
                    f"{base}/api/chat", data=payload,
                    headers={"Content-Type": "application/json"}, method="POST"
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                with urllib.request.urlopen(req, timeout=300) as resp:
                    while True:
                        line = resp.readline()
                        if not line: break
                        self.wfile.write(line); self.wfile.flush()
            except Exception as e:
                try: self.send_json({"error": str(e)}, 502)
                except: pass

        elif p == "/api/extract-pdf":
            body = json.loads(self.read_body())
            try: self.send_json({"text": extract_pdf_text(body.get("base64", ""))})
            except Exception as e: self.send_json({"text": f"[Error: {e}]"})

        elif p == "/api/model-info":
            body = json.loads(self.read_body())
            cfg = load_config()
            base = cfg.get("ollama_url", OLLAMA_BASE)
            info = get_model_info(body.get("name", ""), base)
            self.send_json(info)

        elif p == "/api/pull":
            body = json.loads(self.read_body())
            model_name = body.get("model", "")
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                def write_fn(line):
                    self.wfile.write(line); self.wfile.flush()
                stream_pull(model_name, write_fn)
            except Exception as e:
                try: self.send_json({"error": str(e)}, 502)
                except: pass

        else:
            self.send_response(404); self.end_headers()

def main():
    host = HOST
    print(f"\n  🦙  WildLlama v3")
    print(f"  →  http://{'localhost' if host=='127.0.0.1' else host}:{PORT}")
    print(f"  →  Data: {DATA_DIR}")
    try:
        import fitz
        print(f"  ✓  PDF (PyMuPDF): enabled")
    except ImportError:
        try:
            from pdfminer.high_level import extract_text_to_fp
            print(f"  ✓  PDF (pdfminer): enabled")
        except ImportError:
            print(f"  ·  PDF support:   pip install pymupdf")
    print(f"\n  Ctrl+K  new chat   ·   Ctrl+F  search   ·   Ctrl+,  settings")
    print(f"  Press Ctrl+C to stop.\n")
    server = HTTPServer((host, PORT), Handler)
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  Stopped. Goodbye.\n")

if __name__ == "__main__":
    main()
PYTHON_EOF

Output




