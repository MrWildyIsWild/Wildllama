#!/usr/bin/env python3
"""
Ollama UI — BBB.py
Run: python3 BBB.py  →  open http://localhost:8080
Chats saved to ./ollama-chats/ as named JSON files.
"""

import json, os, glob, re, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

OLLAMA_BASE = "http://localhost:11434"
CHATS_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ollama-chats")
os.makedirs(CHATS_DIR, exist_ok=True)

# ── STORAGE ──
def safe_filename(title, chat_id):
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'\s+', '-', slug.strip())[:40]
    return f"{slug}-{chat_id}.json" if slug else f"chat-{chat_id}.json"

def chat_path_by_id(chat_id):
    matches = glob.glob(os.path.join(CHATS_DIR, f"*-{chat_id}.json"))
    return matches[0] if matches else os.path.join(CHATS_DIR, f"chat-{chat_id}.json")

def load_all_chats():
    chats = []
    for p in sorted(glob.glob(os.path.join(CHATS_DIR, "*.json"))):
        try:
            with open(p, "r", encoding="utf-8") as f:
                chats.append(json.load(f))
        except Exception:
            pass
    return chats

def save_chat(chat):
    # remove old file if title/name changed
    old = glob.glob(os.path.join(CHATS_DIR, f"*-{chat['id']}.json"))
    new_path = os.path.join(CHATS_DIR, safe_filename(chat.get("title","chat"), chat["id"]))
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

# ── PDF ──
def extract_pdf_text(b64):
    import base64, io
    raw = base64.b64decode(b64)
    try:
        import fitz
        doc = fitz.open(stream=raw, filetype="pdf")
        return "\n\n".join(p.get_text() for p in doc)
    except ImportError: pass
    try:
        from pdfminer.high_level import extract_text_to_fp
        from pdfminer.layout import LAParams
        buf=io.BytesIO(raw); out=io.StringIO()
        extract_text_to_fp(buf,out,laparams=LAParams())
        return out.getvalue()
    except ImportError: pass
    return "[PDF extraction needs: pip install pymupdf  or  pip install pdfminer.six]"

# ── HTML ───
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Wildllama</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#080c10;--bg2:#0d1117;--bg3:#111820;--bg4:#16202b;
  --border:#1e2d3d;--border2:#243447;
  --cyan:#00d4d4;--cyan2:#00b8b8;--cyan3:#009999;
  --cyan-glow:rgba(0,212,212,0.15);--cyan-dim:rgba(0,212,212,0.06);
  --text:#e8f0f7;--text2:#8ba0b4;--text3:#4a6175;
  --danger:#ff4f6a;--warn:#f0a500;
  --radius:14px;--radius-sm:8px;
  --font-ui:'Syne',sans-serif;--font-mono:'JetBrains Mono',monospace;
  --sidebar-w:280px;--trans:all 0.2s cubic-bezier(0.4,0,0.2,1);
}
html.light{
  --bg:#f5f0e8;--bg2:#fdfaf4;--bg3:#ede8de;--bg4:#e3ddd2;
  --border:#d4ccbc;--border2:#c8bfad;
  --cyan:#006b6b;--cyan2:#005a5a;--cyan3:#004a4a;
  --cyan-glow:rgba(0,107,107,0.12);--cyan-dim:rgba(0,107,107,0.07);
  --text:#1a1208;--text2:#4a3f2e;--text3:#8a7d6a;
  --danger:#c42840;--warn:#b06800;
}
html,body{height:100%;background:var(--bg);color:var(--text);font-family:var(--font-ui);overflow:hidden;transition:background .3s,color .3s}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border2);border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:var(--cyan3)}

#app{display:flex;height:100vh}

/* ── SIDEBAR ── */
#sidebar{width:var(--sidebar-w);min-width:var(--sidebar-w);background:var(--bg2);border-right:1px solid var(--border);display:flex;flex-direction:column;height:100%;z-index:10;transition:background .3s,border-color .3s}
#sidebar-header{padding:28px 20px 20px;border-bottom:1px solid var(--border)}
.logo{display:flex;align-items:center;gap:10px;margin-bottom:20px}
.logo-icon{width:34px;height:34px;background:linear-gradient(135deg,var(--cyan),var(--cyan3));border-radius:10px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 18px var(--cyan-glow);flex-shrink:0}
.logo-icon svg{width:18px;height:18px}
.logo-text{font-size:17px;font-weight:800;letter-spacing:.04em;color:var(--text)}
.logo-text span{color:var(--cyan)}
.model-label{font-size:10px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--text3);margin-bottom:6px}
.model-wrap{position:relative}
#model-select{width:100%;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);color:var(--text);font-family:var(--font-ui);font-size:13px;font-weight:600;padding:9px 32px 9px 12px;appearance:none;cursor:pointer;transition:var(--trans);outline:none}
#model-select:hover,#model-select:focus{border-color:var(--cyan3);background:var(--bg4)}
.model-chevron{position:absolute;right:10px;bottom:11px;pointer-events:none;color:var(--text3)}
#new-chat-btn{margin-top:14px;width:100%;padding:10px;background:var(--cyan-dim);border:1px solid var(--border2);border-radius:var(--radius-sm);color:var(--cyan);font-family:var(--font-ui);font-size:13px;font-weight:700;letter-spacing:.04em;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:7px;transition:var(--trans);outline:none}
#new-chat-btn:hover{background:rgba(0,212,212,0.12);border-color:var(--cyan3);box-shadow:0 0 20px var(--cyan-glow)}
#history-list{flex:1;overflow-y:auto;padding:12px 10px;display:flex;flex-direction:column;gap:2px}
.history-section-label{font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--text3);padding:8px 10px 4px}
.history-item{padding:10px 12px;border-radius:var(--radius-sm);cursor:pointer;transition:var(--trans);border:1px solid transparent;position:relative}
.history-item:hover{background:var(--bg3);border-color:var(--border)}
.history-item.active{background:var(--cyan-dim);border-color:var(--border2)}
.history-item-title{font-size:13px;font-weight:600;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;transition:var(--trans)}
.history-item:hover .history-item-title,.history-item.active .history-item-title{color:var(--text)}
.history-item-meta{font-size:11px;color:var(--text3);margin-top:2px;font-family:var(--font-mono)}
.history-item-delete{position:absolute;right:8px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--text3);cursor:pointer;padding:4px;border-radius:4px;opacity:0;transition:var(--trans);display:flex}
.history-item:hover .history-item-delete{opacity:1}
.history-item-delete:hover{color:var(--danger);background:rgba(255,79,106,0.1)}
#sidebar-footer{padding:16px 20px;border-top:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.status-wrap{display:flex;align-items:center}
.status-dot{width:7px;height:7px;border-radius:50%;background:var(--text3);display:inline-block;margin-right:7px;transition:var(--trans)}
.status-dot.online{background:var(--cyan);box-shadow:0 0 8px var(--cyan)}
.status-dot.offline{background:var(--danger)}
.status-text{font-size:12px;color:var(--text3);font-weight:600}

/* ── MAIN ── */
#main{flex:1;display:flex;flex-direction:column;height:100%;min-width:0;background:var(--bg);position:relative;transition:background .3s}
#main::before{content:'';position:absolute;top:-200px;right:-200px;width:600px;height:600px;background:radial-gradient(circle,rgba(0,212,212,0.04) 0%,transparent 70%);pointer-events:none;z-index:0}

/* ── TOPBAR ── */
#topbar{display:flex;align-items:center;justify-content:space-between;padding:0 28px;height:62px;border-bottom:1px solid var(--border);background:var(--bg2);position:relative;z-index:5;flex-shrink:0;transition:background .3s,border-color .3s}
#chat-title{font-size:15px;font-weight:700;color:var(--text2);letter-spacing:.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:400px}
.topbar-right{display:flex;align-items:center;gap:8px}
.topbar-chip{padding:5px 12px;background:var(--bg3);border:1px solid var(--border2);border-radius:99px;font-size:12px;font-weight:600;color:var(--cyan);font-family:var(--font-mono);letter-spacing:.02em}
.icon-btn{width:34px;height:34px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--text2);transition:var(--trans);flex-shrink:0}
.icon-btn:hover{border-color:var(--cyan3);color:var(--cyan);background:var(--cyan-dim)}
.icon-btn svg{width:16px;height:16px}

/* ── MESSAGES ── */
#messages{flex:1;overflow-y:auto;padding:32px 28px;display:flex;flex-direction:column;gap:20px;position:relative;z-index:1}
#empty-state{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;opacity:.9;animation:fadeUp .6s ease both}
.empty-icon{width:72px;height:72px;background:var(--bg3);border:1px solid var(--border2);border-radius:20px;display:flex;align-items:center;justify-content:center;box-shadow:0 0 40px var(--cyan-glow)}
.empty-icon svg{width:34px;height:34px;color:var(--cyan)}
.empty-title{font-size:22px;font-weight:800;color:var(--text);letter-spacing:-.01em}
.empty-sub{font-size:14px;color:var(--text3);text-align:center;max-width:320px;line-height:1.6}
.empty-suggestions{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;max-width:480px;margin-top:8px}
.suggestion-pill{padding:8px 16px;background:var(--bg3);border:1px solid var(--border2);border-radius:99px;font-size:13px;color:var(--text2);cursor:pointer;transition:var(--trans);font-family:var(--font-ui);font-weight:600}
.suggestion-pill:hover{background:var(--cyan-dim);border-color:var(--cyan3);color:var(--cyan)}

/* ── MESSAGE ROWS ── */
.msg-row{display:flex;gap:12px;animation:fadeUp .3s ease both;max-width:820px;width:100%}
.msg-row.user{align-self:flex-end;flex-direction:row-reverse}
.msg-row.assistant{align-self:flex-start}
@keyframes fadeUp{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

/* ai avatar only */
.avatar{width:30px;height:30px;border-radius:9px;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-top:4px;font-size:11px;font-weight:800}
.avatar.ai-av{background:linear-gradient(135deg,var(--cyan3),#007a7a);box-shadow:0 0 14px var(--cyan-glow);color:#fff;letter-spacing:.02em}

.bubble{padding:13px 17px;border-radius:var(--radius);font-size:14.5px;line-height:1.75;max-width:700px;word-break:break-word}
.msg-row.user .bubble{background:var(--bg3);border:1px solid var(--border2);color:var(--text);border-bottom-right-radius:4px;margin-left:42px}
.msg-row.assistant .bubble{background:var(--bg2);border:1px solid var(--border);color:var(--text);border-bottom-left-radius:4px}
.bubble pre{background:var(--bg);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:14px 16px;overflow-x:auto;margin:10px 0;font-family:var(--font-mono);font-size:13px;line-height:1.6}
.bubble code{font-family:var(--font-mono);font-size:13px;background:var(--bg3);padding:2px 6px;border-radius:4px;color:var(--cyan)}
.bubble pre code{background:none;padding:0;color:#a8c7d8}
.bubble p{margin-bottom:8px}.bubble p:last-child{margin-bottom:0}
.bubble ul,.bubble ol{padding-left:20px;margin:6px 0}
.bubble li{margin-bottom:4px}
.bubble strong{color:var(--text);font-weight:700}
.bubble em{color:var(--text2)}
.bubble h1,.bubble h2,.bubble h3{color:var(--cyan);margin:12px 0 6px;font-weight:700}
.bubble-img{max-width:320px;max-height:240px;border-radius:var(--radius-sm);border:1px solid var(--border2);margin-bottom:10px;display:block}
.bubble-file-chip{display:inline-flex;align-items:center;gap:6px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:6px 10px;font-size:12px;font-family:var(--font-mono);color:var(--text2);margin-bottom:10px}
.bubble-file-chip svg{color:var(--cyan);flex-shrink:0}
.cursor{display:inline-block;width:2px;height:16px;background:var(--cyan);margin-left:2px;vertical-align:middle;animation:blink .9s infinite;border-radius:1px}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}

/* ── MESSAGE ACTIONS ── */
.msg-actions{display:flex;gap:5px;margin-top:7px;opacity:0;transition:opacity .2s ease}
.msg-row.assistant:hover .msg-actions{opacity:1}
.msg-action-btn{display:flex;align-items:center;gap:5px;padding:4px 10px;background:var(--bg3);border:1px solid var(--border2);border-radius:99px;font-size:11px;font-weight:600;font-family:var(--font-ui);color:var(--text3);cursor:pointer;transition:var(--trans)}
.msg-action-btn svg{width:12px;height:12px;flex-shrink:0}
.msg-action-btn:hover{background:var(--cyan-dim);border-color:var(--cyan3);color:var(--cyan)}
.msg-action-btn.copied{color:var(--cyan);border-color:var(--cyan3);background:var(--cyan-dim)}

/* ── INPUT AREA ── */
#input-area{padding:16px 28px 24px;position:relative;z-index:5;flex-shrink:0}
#input-area::before{content:'';position:absolute;top:0;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,var(--border2),transparent)}
#file-preview-bar{display:none;flex-wrap:wrap;gap:8px;margin-bottom:10px;padding:0 2px}
#file-preview-bar.visible{display:flex}
.file-chip{display:flex;align-items:center;gap:7px;background:var(--bg3);border:1px solid var(--border2);border-radius:var(--radius-sm);padding:6px 10px;font-size:12px;font-family:var(--font-mono);color:var(--text2);animation:fadeUp .2s ease both;max-width:220px}
.file-chip-thumb{width:28px;height:28px;border-radius:5px;object-fit:cover;flex-shrink:0}
.file-chip-icon{width:28px;height:28px;background:var(--bg4);border-radius:5px;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.file-chip-icon svg{width:14px;height:14px;color:var(--cyan)}
.file-chip-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.file-chip-remove{background:none;border:none;color:var(--text3);cursor:pointer;padding:2px;display:flex;border-radius:4px;flex-shrink:0;transition:var(--trans)}
.file-chip-remove:hover{color:var(--danger);background:rgba(255,79,106,0.1)}

.input-wrap{display:flex;align-items:flex-end;gap:10px;background:var(--bg2);border:1px solid var(--border2);border-radius:16px;padding:12px 14px;transition:var(--trans);box-shadow:0 4px 24px rgba(0,0,0,0.2)}
.input-wrap:focus-within{border-color:var(--cyan3);box-shadow:0 4px 32px var(--cyan-glow),0 0 0 1px rgba(0,212,212,0.1)}

/* autocomplete */
#input-shell{flex:1;position:relative;display:flex;align-items:flex-end}
#user-input{width:100%;background:none;border:none;outline:none;color:var(--text);font-family:var(--font-ui);font-size:14.5px;line-height:1.6;resize:none;max-height:180px;min-height:24px;overflow-y:auto;position:relative;z-index:2}
#user-input::placeholder{color:var(--text3)}
#autocomplete-ghost{position:absolute;top:0;left:0;width:100%;pointer-events:none;z-index:1;font-family:var(--font-ui);font-size:14.5px;line-height:1.6;white-space:pre-wrap;word-break:break-word}
.ghost-typed{color:transparent}
.ghost-suggestion{color:var(--text2);opacity:.38}
#tab-badge{display:none;background:var(--bg3);border:1px solid var(--border2);border-radius:4px;padding:0px 4px;font-size:9px;font-family:var(--font-mono);color:var(--text3);vertical-align:middle;margin-left:4px;opacity:.75;line-height:1.6}
#tab-badge.visible{display:inline}

#attach-btn{width:36px;height:36px;background:none;border:1px solid var(--border2);border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:var(--trans);color:var(--text3)}
#attach-btn:hover{border-color:var(--cyan3);color:var(--cyan);background:var(--cyan-dim)}
#attach-btn svg{width:16px;height:16px}

/* send / stop button */
#send-btn{width:38px;height:38px;border:none;border-radius:50%;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:var(--trans);position:relative}
#send-btn.send-mode{background:linear-gradient(135deg,var(--cyan),var(--cyan2));box-shadow:0 0 16px var(--cyan-glow);border-radius:10px}
#send-btn.stop-mode{background:transparent;border:2px solid var(--danger);box-shadow:0 0 14px rgba(255,79,106,0.25)}
#send-btn.send-mode:hover{transform:scale(1.06);box-shadow:0 0 28px rgba(0,212,212,0.35)}
#send-btn.stop-mode:hover{background:rgba(255,79,106,0.1)}
#send-btn:active{transform:scale(0.96)}
#send-btn:disabled{opacity:.35;cursor:not-allowed;transform:none}
#send-btn svg{width:17px;height:17px;transition:var(--trans)}
#send-btn.send-mode svg{color:#000}
#send-btn.stop-mode svg{color:var(--danger)}

/* stop spinner ring */
#send-btn.stop-mode::before{content:'';position:absolute;inset:-2px;border-radius:50%;border:2px solid transparent;border-top-color:var(--danger);animation:spin 1s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

.input-hint{text-align:center;font-size:11px;color:var(--text3);margin-top:10px;font-family:var(--font-mono);letter-spacing:.04em}
.input-hint kbd{background:var(--bg3);border:1px solid var(--border2);border-radius:4px;padding:1px 5px;font-family:var(--font-mono);font-size:10px}

/* thinking */
.thinking{display:flex;gap:5px;padding:4px 0;align-items:center}
.thinking span{width:7px;height:7px;background:var(--cyan3);border-radius:50%;animation:think 1.2s infinite ease-in-out}
.thinking span:nth-child(2){animation-delay:.2s}
.thinking span:nth-child(3){animation-delay:.4s}
@keyframes think{0%,100%{transform:scale(.7);opacity:.4}50%{transform:scale(1);opacity:1}}

/* toast */
#toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%) translateY(20px);background:var(--bg4);border:1px solid var(--border2);border-radius:99px;padding:10px 20px;font-size:13px;font-weight:600;color:var(--text2);opacity:0;pointer-events:none;transition:all .3s ease;z-index:999}
#toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
#file-input{display:none}
</style>
</head>
<body>
<div id="app">
  <aside id="sidebar">
    <div id="sidebar-header">
      <div class="logo">
        <div class="logo-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.22 4.22l2.12 2.12M17.66 17.66l2.12 2.12M2 12h3M19 12h3M4.22 19.78l2.12-2.12M17.66 6.34l2.12-2.12"/></svg>
        </div>
        <span class="logo-text">Wild<span>llama</span></span>
      </div>
      <div class="model-wrap">
        <div class="model-label">Active Model</div>
        <select id="model-select"><option value="">Loading…</option></select>
        <svg class="model-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <button id="new-chat-btn">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        New Chat
      </button>
    </div>
    <div id="history-list"></div>
    <div id="sidebar-footer">
      <div class="status-wrap">
        <span class="status-dot" id="status-dot"></span>
        <span class="status-text" id="status-text">Connecting…</span>
      </div>
    </div>
  </aside>

  <main id="main">
    <div id="topbar">
      <div id="chat-title">New Conversation</div>
      <div class="topbar-right">
        <div class="topbar-chip" id="topbar-model">—</div>
        <button class="icon-btn" id="theme-btn" title="Toggle light/dark">
          <svg id="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          <svg id="icon-sun" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
        </button>
      </div>
    </div>

    <div id="messages">
      <div id="empty-state">
        <div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
        <div class="empty-title">Start a conversation</div>
        <div class="empty-sub">Ask anything — attach images, PDFs or code files too.</div>
        <div class="empty-suggestions">
          <div class="suggestion-pill" onclick="useSuggestion(this)">Explain quantum computing</div>
          <div class="suggestion-pill" onclick="useSuggestion(this)">Write a Python function</div>
          <div class="suggestion-pill" onclick="useSuggestion(this)">What is the Fermi paradox?</div>
          <div class="suggestion-pill" onclick="useSuggestion(this)">Debug my code</div>
        </div>
      </div>
    </div>

    <div id="input-area">
      <div id="file-preview-bar"></div>
      <div class="input-wrap">
        <button id="attach-btn" title="Attach file">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66L9.41 17.41a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
        </button>
        <input type="file" id="file-input" multiple accept="image/*,.pdf,.txt,.md,.py,.js,.ts,.jsx,.tsx,.html,.css,.json,.csv,.xml,.yaml,.yml,.sh,.c,.cpp,.java,.rs,.go"/>
        <div id="input-shell">
          <div id="autocomplete-ghost"><span class="ghost-typed"></span><span class="ghost-suggestion"></span><span id="tab-badge">tab</span></div>
          <textarea id="user-input" placeholder="Try typing something..." rows="1"></textarea>
        </div>
        <button id="send-btn" class="send-mode" title="Send">
          <svg id="send-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          <svg id="stop-icon" style="display:none" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        </button>
      </div>
      <div class="input-hint">Press <kbd>Enter</kbd> to send &nbsp;·&nbsp; <kbd>Shift+Enter</kbd> for newline &nbsp;·&nbsp; <kbd>Tab</kbd> to autocomplete</div>
    </div>
  </main>
</div>
<div id="toast"></div>

<script>
// ── STATE ──
const state = {
  chats: [], activeChatId: null,
  streaming: false, abortController: null,
  models: [], pendingFiles: []
};

// ── DOM ──
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

// ── TOAST ──
function showToast(msg){
  const t=document.getElementById('toast'); t.textContent=msg;
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2500);
}

// ── THEME ──
function applyTheme(light){
  document.documentElement.classList.toggle('light',light);
  document.getElementById('icon-moon').style.display=light?'none':'';
  document.getElementById('icon-sun').style.display=light?'':'none';
  localStorage.setItem('ollama_theme',light?'light':'dark');
}
document.getElementById('theme-btn').addEventListener('click',()=>
  applyTheme(!document.documentElement.classList.contains('light')));
applyTheme(localStorage.getItem('ollama_theme')==='light');

// ── SEND / STOP BUTTON STATE ──
function setStreamingUI(streaming){
  state.streaming = streaming;
  $sendBtn.classList.toggle('send-mode', !streaming);
  $sendBtn.classList.toggle('stop-mode',  streaming);
  $sendIcon.style.display = streaming ? 'none' : '';
  $stopIcon.style.display = streaming ? ''     : 'none';
  $sendBtn.title = streaming ? 'Stop generating' : 'Send';
}

// ── STOP GENERATION ──
function stopGeneration(){
  if(state.abortController) state.abortController.abort();
}

// ── FILE STORAGE ──
function getActiveChat(){ return state.chats.find(c=>c.id===state.activeChatId); }

async function saveChat(chat){
  await fetch('/api/chats/'+chat.id,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(chat)});
}
async function loadChats(){
  const res=await fetch('/api/chats'); state.chats=await res.json();
}
async function apiDeleteChat(id){
  await fetch('/api/chats/'+id,{method:'DELETE'});
}

// ── AUTOCOMPLETE ──
let acSuggestion='';

const WORD_LIST=`about above absolutely accept access across action actually add address after again against age ago agree ahead all allow almost alone along already also although always among another answer any anyone anything apart apply approach area around ask aspect assume at away back based be because become been before behind believe below best better between beyond big both bring build but by call came can cause certain change check choice choose clear close come common complete consider contain continue could create current data day define describe design detail did different difficult direct do does during each easy else end enough even every everything exact example exist experience explain fact find first follow for found from function generate get give given good great group has have help here high him how however human idea identify if important include information instead into its just keep know large last later learn let like list long look main make many mean might mind more most much must name need next note nothing now of off often only open or other our output over own part place plan possible present problem provide question reason recent refer related result return right run same say search see should show side simple since small some something specific start step still such system take than that their them then there these they think this those through time together too top toward type under understand until use various very want ways well were what when where which while will with without word work would write yet your`.split(' ');

function getWordCorpus(){
  const chat=getActiveChat(); if(!chat) return [];
  const text=chat.messages.filter(m=>m.role==='user').map(m=>m.content).join(' ');
  const words=text.match(/\b[a-zA-Z]{3,}\b/g)||[];
  const freq={};
  words.forEach(w=>{const k=w.toLowerCase();freq[k]=(freq[k]||0)+1;});
  return Object.entries(freq).sort((a,b)=>b[1]-a[1]).map(e=>e[0]);
}

function updateAutocomplete(){
  const val=$input.value;
  const m=val.match(/(\S+)$/);
  if(!m||m[1].length<1){clearAutocomplete();return;}
  const partial=m[1].toLowerCase();
  const corpus=[...new Set([...getWordCorpus(),...WORD_LIST])];
  const match=corpus.find(w=>w.startsWith(partial)&&w.length>partial.length);
  if(match){
    acSuggestion=match.slice(partial.length);
    $ghostTyped.textContent=val;
    $ghostSug.textContent=acSuggestion;
    $tabBadge.classList.add('visible');
  } else { clearAutocomplete(); }
}

function clearAutocomplete(){
  acSuggestion='';
  $ghostTyped.textContent='';
  $ghostSug.textContent='';
  $tabBadge.classList.remove('visible');
}

function acceptAutocomplete(){
  if(!acSuggestion) return false;
  $input.value+=acSuggestion;
  $input.style.height='auto';
  $input.style.height=Math.min($input.scrollHeight,180)+'px';
  clearAutocomplete(); return true;
}

// ── TEXTAREA ──
$input.addEventListener('input',()=>{
  $input.style.height='auto';
  $input.style.height=Math.min($input.scrollHeight,180)+'px';
  updateAutocomplete();
});
$input.addEventListener('keydown',e=>{
  if(e.key==='Tab'){e.preventDefault();acceptAutocomplete();return;}
  if(e.key==='Escape'){clearAutocomplete();return;}
  if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();}
});
$input.addEventListener('blur',clearAutocomplete);

// ── FILES ──
$attachBtn.addEventListener('click',()=>$fileInput.click());
$fileInput.addEventListener('change',async()=>{
  for(const f of Array.from($fileInput.files)) await processFile(f);
  $fileInput.value=''; renderPreviewBar();
});
document.getElementById('input-area').addEventListener('dragover',e=>{
  e.preventDefault(); document.querySelector('.input-wrap').style.borderColor='var(--cyan)';
});
document.getElementById('input-area').addEventListener('dragleave',()=>
  document.querySelector('.input-wrap').style.borderColor='');
document.getElementById('input-area').addEventListener('drop',async e=>{
  e.preventDefault(); document.querySelector('.input-wrap').style.borderColor='';
  for(const f of Array.from(e.dataTransfer.files)) await processFile(f);
  renderPreviewBar();
});

async function processFile(file){
  if(file.size>20*1024*1024){showToast(file.name+' too large (max 20MB)');return;}
  if(file.type.startsWith('image/')){
    state.pendingFiles.push({name:file.name,type:'image',dataURL:await readAsDataURL(file)});
  } else if(file.type==='application/pdf'){
    const b64=(await readAsDataURL(file)).split(',')[1];
    try{
      const d=await(await fetch('/api/extract-pdf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({base64:b64,name:file.name})})).json();
      state.pendingFiles.push({name:file.name,type:'pdf',textContent:d.text});
      showToast('PDF extracted: '+file.name);
    }catch{showToast('Could not extract PDF');}
  } else {
    state.pendingFiles.push({name:file.name,type:'text',textContent:await readAsText(file)});
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
    else{const icon=document.createElement('div');icon.className='file-chip-icon';icon.innerHTML=f.type==='pdf'?'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>':'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>';chip.appendChild(icon);}
    const nm=document.createElement('span');nm.className='file-chip-name';nm.textContent=f.name;chip.appendChild(nm);
    const rm=document.createElement('button');rm.className='file-chip-remove';rm.innerHTML='<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
    rm.addEventListener('click',()=>{state.pendingFiles.splice(i,1);renderPreviewBar();});
    chip.appendChild(rm);$previewBar.appendChild(chip);
  });
}

// ── MARKDOWN ──
function renderMarkdown(text){
  let h=text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/```(\w*)\n?([\s\S]*?)```/g,(_,l,c)=>`<pre><code class="lang-${l}">${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g,'<code>$1</code>')
    .replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>')
    .replace(/\*(.+?)\*/g,'<em>$1</em>')
    .replace(/^### (.+)$/gm,'<h3>$1</h3>').replace(/^## (.+)$/gm,'<h2>$1</h2>').replace(/^# (.+)$/gm,'<h1>$1</h1>')
    .replace(/^\s*[-*] (.+)$/gm,'<li>$1</li>')
    .replace(/\n\n+/g,'</p><p>').replace(/\n/g,'<br>');
  return `<p>${h}</p>`;
}
function escapeHtml(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');}

// ── RENDER MESSAGES ──
function renderMessages(){
  const chat=getActiveChat();
  if(!chat||!chat.messages.filter(m=>m.role!=='system').length){
    $messages.innerHTML='';$messages.appendChild(buildEmptyState());return;
  }
  $messages.innerHTML='';
  chat.messages.forEach(m=>{if(m.role==='system')return;appendBubble(m.role,m.content,false,m.images,m.fileChips);});
  scrollBottom();
}

function buildEmptyState(){
  const d=document.createElement('div');d.id='empty-state';
  d.innerHTML=`<div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
    <div class="empty-title">Start a conversation</div>
    <div class="empty-sub">Ask anything — attach images, PDFs or code files too.</div>
    <div class="empty-suggestions">
      <div class="suggestion-pill" onclick="useSuggestion(this)">Explain quantum computing</div>
      <div class="suggestion-pill" onclick="useSuggestion(this)">Write a Python function</div>
      <div class="suggestion-pill" onclick="useSuggestion(this)">What is the Fermi paradox?</div>
      <div class="suggestion-pill" onclick="useSuggestion(this)">Debug my code</div>
    </div>`;
  return d;
}

function appendBubble(role,content,streaming=false,images=[],fileChips=[]){
  const row=document.createElement('div');row.className=`msg-row ${role}`;

  // only AI gets an avatar
  if(role==='assistant'){
    const av=document.createElement('div');av.className='avatar ai-av';av.textContent='AI';
    row.appendChild(av);
  }

  const bubble=document.createElement('div');bubble.className='bubble';
  if(images&&images.length) images.forEach(src=>{const img=document.createElement('img');img.className='bubble-img';img.src=src;bubble.appendChild(img);});
  if(fileChips&&fileChips.length) fileChips.forEach(fc=>{const c=document.createElement('div');c.className='bubble-file-chip';c.innerHTML=`<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>${escapeHtml(fc)}`;bubble.appendChild(c);});
  const tn=document.createElement('div');
  if(streaming) tn.innerHTML='<div class="thinking"><span></span><span></span><span></span></div>';
  else tn.innerHTML=role==='assistant'?renderMarkdown(content):`<p>${escapeHtml(content)}</p>`;
  bubble.appendChild(tn);
  if(role==='assistant'&&!streaming) bubble.appendChild(buildMessageActions(content));
  row.appendChild(bubble);
  $messages.appendChild(row);
  scrollBottom();return tn;
}

function buildMessageActions(content){
  const actions=document.createElement('div');actions.className='msg-actions';
  const copyBtn=document.createElement('button');copyBtn.className='msg-action-btn';
  copyBtn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Copy';
  copyBtn.addEventListener('click',()=>{navigator.clipboard.writeText(content).then(()=>{copyBtn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>Copied!';copyBtn.classList.add('copied');setTimeout(()=>{copyBtn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>Copy';copyBtn.classList.remove('copied');},2000);});});
  const dlBtn=document.createElement('button');dlBtn.className='msg-action-btn';
  dlBtn.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>Download';
  dlBtn.addEventListener('click',()=>{const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type:'text/plain'}));a.download='ollama-response-'+Date.now()+'.txt';a.click();showToast('Downloaded as .txt');});
  actions.appendChild(copyBtn);actions.appendChild(dlBtn);return actions;
}

function scrollBottom(){$messages.scrollTop=$messages.scrollHeight;}

// ── HISTORY ──
function renderHistory(){
  $historyList.innerHTML='';
  if(!state.chats.length){$historyList.innerHTML='<div style="padding:20px;text-align:center;color:var(--text3);font-size:12px;font-weight:600;">No conversations yet</div>';return;}
  const lbl=document.createElement('div');lbl.className='history-section-label';lbl.textContent='Recent';$historyList.appendChild(lbl);
  [...state.chats].reverse().forEach(chat=>{
    const item=document.createElement('div');item.className='history-item'+(chat.id===state.activeChatId?' active':'');
    item.innerHTML=`<div class="history-item-title">${escapeHtml(chat.title||'New Chat')}</div><div class="history-item-meta">${escapeHtml(chat.model||'')}</div><button class="history-item-delete" title="Delete"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6M14 11v6"/></svg></button>`;
    item.querySelector('.history-item-delete').addEventListener('click',e=>{e.stopPropagation();deleteChatUI(chat.id);});
    item.addEventListener('click',()=>switchChat(chat.id));
    $historyList.appendChild(item);
  });
}

// ── CHAT MANAGEMENT ──
function makeTitle(text){
  const words=text.trim().replace(/[^\w\s]/g,'').split(/\s+/).filter(Boolean);
  return words.slice(0,3).join(' ')||'New Chat';
}

async function createNewChat(){
  const id=Date.now().toString();
  const chat={id,title:'New Chat',model:$modelSelect.value||'',messages:[],createdAt:Date.now()};
  state.chats.push(chat);
  await saveChat(chat);
  switchChat(id);
}

function switchChat(id){
  state.activeChatId=id;
  const chat=getActiveChat();
  $chatTitle.textContent=chat?chat.title:'New Conversation';
  $topbarModel.textContent=chat?(chat.model||'—'):'—';
  renderMessages();renderHistory();
}

async function deleteChatUI(id){
  state.chats=state.chats.filter(c=>c.id!==id);
  await apiDeleteChat(id);
  if(state.activeChatId===id){
    if(state.chats.length) switchChat(state.chats[state.chats.length-1].id);
    else{state.activeChatId=null;$chatTitle.textContent='New Conversation';$topbarModel.textContent='—';renderMessages();}
  }
  renderHistory();showToast('Conversation deleted');
}

// ── MODELS ──
async function loadModels(){
  try{
    const data=await(await fetch('/api/models')).json();
    state.models=data.models||[];
    $modelSelect.innerHTML='';
    if(!state.models.length){$modelSelect.innerHTML='<option value="">No models found</option>';setStatus(false,'No models installed');return;}
    state.models.forEach(m=>{const o=document.createElement('option');o.value=m;o.textContent=m;$modelSelect.appendChild(o);});
    setStatus(true,'Ollama connected');$topbarModel.textContent=$modelSelect.value;
  }catch{$modelSelect.innerHTML='<option value="">Ollama not running</option>';setStatus(false,'Ollama offline');}
}
function setStatus(online,text){$statusDot.className='status-dot '+(online?'online':'offline');$statusText.textContent=text;}
$modelSelect.addEventListener('change',()=>{
  $topbarModel.textContent=$modelSelect.value;
  const chat=getActiveChat();if(chat){chat.model=$modelSelect.value;saveChat(chat);}
});

// ── SEND MESSAGE ──
$sendBtn.addEventListener('click',()=>{
  if(state.streaming) stopGeneration();
  else sendMessage();
});

async function sendMessage(){
  const text=$input.value.trim(),files=[...state.pendingFiles];
  if(!text&&!files.length) return;
  const model=$modelSelect.value;
  if(!model){showToast('No model selected');return;}
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
  if(chat.title==='New Chat'){
    chat.title=makeTitle(text||files[0]?.name||'Attachment');
    $chatTitle.textContent=chat.title;
  }
  await saveChat(chat);
  appendBubble('user',fullContent,false,imageDataURLs,fileChipNames);
  renderHistory();

  $input.value='';$input.style.height='auto';
  state.pendingFiles=[];renderPreviewBar();clearAutocomplete();
  setStreamingUI(true);

  const aiBubble=appendBubble('assistant','',true);
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
      body:JSON.stringify({model,messages:apiMessages}),
      signal:state.abortController.signal
    });
    if(!response.ok) throw new Error('Chat request failed');

    const reader=response.body.getReader(),decoder=new TextDecoder();
    let buffer='';
    aiBubble.innerHTML='<span class="cursor"></span>';

    while(true){
      const {done,value}=await reader.read();if(done)break;
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
    aiBubble.appendChild(buildMessageActions(fullResponse));
    chat.messages.push({role:'assistant',content:fullResponse});
    await saveChat(chat);
  }catch(e){
    if(e.name==='AbortError'){
      // stopped by user — save what we have
      if(fullResponse){
        aiBubble.innerHTML=renderMarkdown(fullResponse)+' <em style="font-size:12px;color:var(--text3)">[stopped]</em>';
        aiBubble.appendChild(buildMessageActions(fullResponse));
        chat.messages.push({role:'assistant',content:fullResponse});
        await saveChat(chat);
      } else {
        aiBubble.innerHTML='<em style="color:var(--text3);font-size:13px">Generation stopped.</em>';
      }
    } else {
      aiBubble.innerHTML='<em style="color:var(--danger)">Could not reach Ollama. Make sure it\'s running with <code>ollama serve</code>.</em>';
    }
  }

  setStreamingUI(false);
  state.abortController=null;
  scrollBottom();
}

function useSuggestion(el){$input.value=el.textContent;$input.dispatchEvent(new Event('input'));$input.focus();}
document.getElementById('new-chat-btn').addEventListener('click',createNewChat);

// ── INIT ──
(async()=>{
  await loadModels();
  await loadChats();
  if(state.chats.length) switchChat(state.chats[state.chats.length-1].id);
  else{renderMessages();renderHistory();}
  $input.focus();
})();
</script>
</body>
</html>
"""

# ── HTTP HANDLER ──
class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args): pass

    def send_json(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        return self.rfile.read(int(self.headers.get("Content-Length",0)))

    def do_GET(self):
        if self.path in ("/","/index.html"):
            body=HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","text/html; charset=utf-8")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path=="/api/models":
            try:
                with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags",timeout=5) as r:
                    data=json.loads(r.read())
                self.send_json({"models":[m["name"] for m in data.get("models",[])]})
            except Exception as e:
                self.send_json({"models":[],"error":str(e)},503)
        elif self.path=="/api/chats":
            self.send_json(load_all_chats())
        else:
            self.send_response(404);self.end_headers()

    def do_PUT(self):
        if self.path.startswith("/api/chats/"):
            save_chat(json.loads(self.read_body()))
            self.send_json({"ok":True})
        else:
            self.send_response(404);self.end_headers()

    def do_DELETE(self):
        if self.path.startswith("/api/chats/"):
            delete_chat(self.path[len("/api/chats/"):])
            self.send_json({"ok":True})
        else:
            self.send_response(404);self.end_headers()

    def do_POST(self):
        if self.path=="/api/chat":
            body=json.loads(self.read_body())
            payload=json.dumps({"model":body.get("model",""),"messages":body.get("messages",[]),"stream":True}).encode()
            try:
                req=urllib.request.Request(f"{OLLAMA_BASE}/api/chat",data=payload,headers={"Content-Type":"application/json"},method="POST")
                self.send_response(200)
                self.send_header("Content-Type","application/x-ndjson")
                self.send_header("Transfer-Encoding","chunked")
                self.end_headers()
                with urllib.request.urlopen(req,timeout=120) as resp:
                    while True:
                        line=resp.readline()
                        if not line: break
                        self.wfile.write(line);self.wfile.flush()
            except Exception as e:
                try: self.send_json({"error":str(e)},502)
                except: pass
        elif self.path=="/api/extract-pdf":
            body=json.loads(self.read_body())
            try: self.send_json({"text":extract_pdf_text(body.get("base64",""))})
            except Exception as e: self.send_json({"text":f"[Error: {e}]"})
        else:
            self.send_response(404);self.end_headers()

# ── MAIN ──
def main():
    port=8080
    server=HTTPServer(("127.0.0.1",port),Handler)
    print(f"\n  ✦  Wildllama — BBB.py")
    print(f"  →  Open http://localhost:{port} in your browser")
    print(f"  →  Chats saved to: {CHATS_DIR}\n")
    print("  Press Ctrl+C to stop.\n")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n  Stopped.")

if __name__=="__main__":
    main()
