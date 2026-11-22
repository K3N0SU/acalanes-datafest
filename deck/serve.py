#!/usr/bin/env python3
"""Local editor for deck/content.json. Standard library only, 127.0.0.1 only.

Usage: python serve.py [port]   (default 5190)
"""
import json, shutil, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

DECK = Path(__file__).resolve().parent
CONTENT = DECK / "content.json"
HISTORY = DECK / "history"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5190
TYPES = {".json": "application/json; charset=utf-8", ".md": "text/plain; charset=utf-8",
         ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8",
         ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
         ".png": "image/png"}

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Deck editor</title>
<style>
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:820px;margin:0 auto;padding:0 16px 80px;color:#111;line-height:1.4}
header{position:sticky;top:0;background:#fff;border-bottom:1px solid #ccc;padding:10px 0;z-index:5}
h1{font-size:18px;margin:0 0 6px}
.bar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:14px}
button{font:inherit;padding:6px 12px;cursor:pointer}
#total{font-weight:600}.over{color:#b00020}.under{color:#1a7f37}
.card{border:1px solid #ccc;padding:12px 14px;margin:18px 0}
.card h2{font-size:16px;margin:0 0 4px}
.meta{font-size:13px;color:#555;margin:0 0 10px}
.group{margin:8px 0 8px 0;padding-left:12px;border-left:2px solid #ddd}
.group>.glabel{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#555;margin:4px 0}
label{display:block;font-size:12px;color:#555;margin:8px 0 2px}
input[type=text],input[type=number],textarea{width:100%;box-sizing:border-box;font:inherit;padding:5px 6px;border:1px solid #bbb}
textarea{resize:vertical;overflow:hidden}
input[disabled]{background:#f2f2f2;color:#666}
pre{white-space:pre-wrap;background:#f6f6f6;padding:8px;font-size:12px}
.ok{color:#1a7f37}.err{color:#b00020}
</style></head><body>
<header>
<h1>Deck editor</h1>
<div class="bar">
<button id="save">Save and rebuild</button>
<a id="dl" href="/Rushover.pptx">Download pptx</a>
<a href="/SCRIPT.md" target="_blank">View SCRIPT.md</a>
<span id="total"></span>
</div>
<div id="status" class="meta"></div>
</header>
<main id="cards"></main>
<script>
const WPM=150;let data=null;
const words=s=>(String(s).trim().match(/\S+/g)||[]).length;
const fmt=s=>{s=Math.round(s);return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")};
function el(t,a,...k){const e=document.createElement(t);for(const x in a||{})e[x]=a[x];k.forEach(c=>e.append(c));return e}
function setAt(path,v){let o=data;for(let i=0;i<path.length-1;i++)o=o[path[i]];o[path[path.length-1]]=v}
function autosize(t){t.style.height="auto";t.style.height=(t.scrollHeight+2)+"px"}
function field(label,path,val,out){
  const key=path[path.length-1];
  if(Array.isArray(val)||(val&&typeof val==="object")){
    const g=el("div",{className:"group"});g.append(el("div",{className:"glabel",textContent:label}));
    const isArr=Array.isArray(val);
    Object.keys(val).forEach(k=>field(isArr?(typeof val[k]==="object"?label+" "+(+k+1):label+" "+(+k+1)):k,path.concat(isArr?+k:k),val[k],g));
    out.append(g);return}
  const ro=(key==="id"||key==="layout");
  if(typeof val==="boolean"){
    const i=el("input",{type:"checkbox",checked:val});i.onchange=()=>setAt(path,i.checked);
    out.append(el("label",{},i," "+label));return}
  out.append(el("label",{textContent:label}));
  if(typeof val==="number"){
    const i=el("input",{type:"number",value:val,disabled:ro});
    i.oninput=()=>{setAt(path,i.value===""?0:Number(i.value))};out.append(i);return}
  const multi=!ro&&(val.length>60||key==="notes"||key==="body");
  const i=multi?el("textarea",{value:val}):el("input",{type:"text",value:val,disabled:ro});
  i.oninput=()=>{setAt(path,i.value);if(multi)autosize(i);refreshStats()};
  out.append(i);if(multi)setTimeout(()=>autosize(i),0);
}
function render(){
  const root=document.getElementById("cards");root.innerHTML="";
  data.slides.forEach((s,i)=>{
    const c=el("section",{className:"card"});
    c.append(el("h2",{textContent:(i+1)+". "+s.id+" ("+s.layout+")"}));
    c.append(el("p",{className:"meta",id:"st"+i}));
    Object.keys(s).filter(k=>k!=="notes").forEach(k=>field(k,["slides",i,k],s[k],c));
    field("notes (speaker script)",["slides",i,"notes"],s.notes,c);
    root.append(c)});
  const m=el("section",{className:"card"});m.append(el("h2",{textContent:"Deck meta"}));
  Object.keys(data.meta).forEach(k=>field(k,["meta",k],data.meta[k],m));root.append(m);
  refreshStats();
}
function refreshStats(){
  let tot=0;
  data.slides.forEach((s,i)=>{const w=words(s.notes),e=w/WPM*60;tot+=e;
    document.getElementById("st"+i).textContent="Notes: "+w+" words, about "+fmt(e)+" at "+WPM+" wpm. Target "+s.seconds+"s.";});
  const lim=(data.meta.minutes||5)*60,d=tot-lim,t=document.getElementById("total");
  t.className=d>0?"over":"under";
  t.textContent="Total "+fmt(tot)+" of "+fmt(lim)+": "+(d>0?fmt(d)+" OVER":fmt(-d)+" under");
}
async function load(){data=await (await fetch("/api/content")).json();render()}
document.getElementById("save").onclick=async()=>{
  const st=document.getElementById("status");st.className="meta";st.textContent="Saving and building...";
  try{
    const r=await fetch("/api/save",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
    const j=await r.json();
    st.className="meta "+(j.ok?"ok":"err");
    st.innerHTML="";st.append(j.ok?"Saved and rebuilt. ":"Failed. ",el("pre",{textContent:j.output||j.error||""}));
    document.getElementById("dl").href="/Rushover.pptx?t="+Date.now();
  }catch(e){st.className="meta err";st.textContent="Error: "+e}
};
load();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "DeckEditor"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s\n" % (fmt % a))

    def _send(self, code, body, ctype="text/plain; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "bad host")
        path = unquote(urlparse(self.path).path)
        if path in ("/", "/index.html"):
            return self._send(200, PAGE, "text/html; charset=utf-8")
        if path == "/api/content":
            return self._send(200, CONTENT.read_bytes(), "application/json; charset=utf-8")
        rel = path.lstrip("/")
        if not rel or "\x00" in rel:
            return self._send(404, "not found")
        target = (DECK / rel).resolve()
        try:
            target.relative_to(DECK)
        except ValueError:
            return self._send(403, "forbidden")
        if not target.is_file():
            return self._send(404, "not found")
        extra = {}
        if target.suffix == ".pptx":
            extra["Content-Disposition"] = 'attachment; filename="%s"' % target.name
        self._send(200, target.read_bytes(), TYPES.get(target.suffix.lower(), "application/octet-stream"), extra)

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, "bad host")
        if urlparse(self.path).path != "/api/save":
            return self._send(404, "not found")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            data = json.loads(self.rfile.read(n).decode("utf-8"))
            assert isinstance(data, dict) and isinstance(data.get("slides"), list) and isinstance(data.get("meta"), dict)
        except Exception as e:
            return self._send(400, json.dumps({"ok": False, "error": "bad payload: %s" % e}), "application/json")
        HISTORY.mkdir(exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = HISTORY / ("content-%s.json" % stamp)
        shutil.copy2(CONTENT, backup)
        old = CONTENT.read_text(encoding="utf-8")
        CONTENT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            p = subprocess.run([sys.executable, str(DECK / "build_deck.py")], cwd=str(DECK),
                               capture_output=True, text=True, timeout=120)
            out = (p.stdout + p.stderr).strip()
            ok = p.returncode == 0
        except Exception as e:
            out, ok = str(e), False
        if not ok:
            failed = HISTORY / ("failed-edit-%s.json" % stamp)
            failed.write_text(CONTENT.read_text(encoding="utf-8"), encoding="utf-8")
            CONTENT.write_text(old, encoding="utf-8")   # keep the last good file
            out += "\n(content.json restored to the previous version; your edit is saved as history/%s)" % failed.name
        self._send(200, json.dumps({"ok": ok, "output": out, "backup": backup.name}), "application/json")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Deck editor on http://127.0.0.1:%d" % PORT)
    srv.serve_forever()
