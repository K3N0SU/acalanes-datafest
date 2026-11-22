"""Notes: a small teleprompter window for the two presenters.

Reads deck/content.json, shows the spoken notes per slide, and asks Windows
to keep this window out of screen capture (SetWindowDisplayAffinity).
"""
import ctypes
import json
import re
import sys
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTENT = HERE / "content.json"

WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011

DEFAULT_SPEAKER = {
    "title": "Hengyi", "question": "Hengyi", "how": "Hengyi", "model": "Hengyi",
    "result": "Hengyi", "worth": "Mohammed", "exceptions": "Mohammed",
    "failures": "Mohammed", "limits": "Hengyi",
}
COLORS = {"Hengyi": "#1f4e79", "Mohammed": "#7a3d14"}
TARGET = 240
AMBER_AT = 215
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[A-Z0-9])")


def load_slides():
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    out, alt = [], 0
    for s in data.get("slides", []):
        if s.get("id") == "methods":
            continue
        sp = s.get("speaker") or DEFAULT_SPEAKER.get(s.get("id"))
        if not sp:
            sp = ["Hengyi", "Mohammed"][alt % 2]
            alt += 1
        out.append({"title": s.get("title", ""), "notes": s.get("notes", "") or "",
                    "seconds": s.get("seconds"), "speaker": sp})
    return out


def sentences(text):
    text = " ".join(text.split())
    return [p for p in SENT_SPLIT.split(text) if p]


def word_counts(slides):
    per = {"Hengyi": 0, "Mohammed": 0}
    for s in slides:
        per[s["speaker"]] = per.get(s["speaker"], 0) + len(s["notes"].split())
    return sum(per.values()), per



def load_demo():
    """the website walkthrough that follows the slides, if content.json has one"""
    try:
        import json as _json
        from pathlib import Path as _Path
        data = _json.loads((_Path(__file__).resolve().parent / "content.json").read_text(encoding="utf-8"))
        demo = data.get("demo")
        return demo if isinstance(demo, dict) else None
    except Exception:  # noqa: BLE001
        return None

class Prompter:
    def __init__(self, root, selftest=False):
        self.root = root
        self.affinity = "NOT hidden: not applied yet"
        self.size = 18
        self.alpha = 1.0
        self.running = False
        self.elapsed = 0.0
        self.started_at = None
        self.slides = []

        root.title("Notes")
        root.geometry("560x720")
        root.minsize(320, 300)
        root.configure(bg="#fafafa")

        family = "Segoe UI" if "Segoe UI" in tkfont.families() else "Consolas"
        self.body = tkfont.Font(family=family, size=self.size)
        self.bold = tkfont.Font(family=family, size=self.size, weight="bold")
        self.head = tkfont.Font(family=family, size=max(9, self.size - 7))
        ui = tkfont.Font(family=family, size=10)

        bar = tk.Frame(root, bg="#efefef", padx=6, pady=4)
        bar.pack(side="top", fill="x")
        self.timer = tk.Label(bar, text="00:00", font=(family, 16, "bold"), bg="#efefef", fg="#222")
        self.timer.pack(side="left")
        tk.Label(bar, text=" / 5:00", font=ui, bg="#efefef", fg="#777").pack(side="left")
        self.start_btn = tk.Button(bar, text="Start", width=6, font=ui, command=self.toggle, takefocus=0)
        self.start_btn.pack(side="left", padx=(8, 2))
        tk.Button(bar, text="Reset", width=6, font=ui, command=self.reset, takefocus=0).pack(side="left")
        self.ontop = tk.BooleanVar(value=True)
        tk.Checkbutton(bar, text="Always on top", variable=self.ontop, font=ui, bg="#efefef",
                       command=self.apply_ontop, takefocus=0).pack(side="right")
        self.alpha_lbl = tk.Label(bar, text="100%", font=ui, bg="#efefef", fg="#555")
        self.alpha_lbl.pack(side="right", padx=4)
        tk.Button(bar, text="+", width=2, font=ui, command=lambda: self.opacity(0.1), takefocus=0).pack(side="right")
        tk.Button(bar, text="-", width=2, font=ui, command=lambda: self.opacity(-0.1), takefocus=0).pack(side="right")

        self.words = tk.Label(root, text="", font=ui, bg="#fafafa", fg="#555", anchor="w", padx=8)
        self.words.pack(side="top", fill="x")

        self.status = tk.Label(root, text="", font=ui, bg="#efefef", fg="#555", anchor="w", padx=8)
        self.status.pack(side="bottom", fill="x")

        wrap = tk.Frame(root, bg="#fafafa")
        wrap.pack(side="top", fill="both", expand=True)
        sb = tk.Scrollbar(wrap)
        sb.pack(side="right", fill="y")
        self.text = tk.Text(wrap, wrap="word", font=self.body, bg="#fffef8", fg="#222",
                            relief="flat", padx=18, pady=12, spacing1=3, spacing2=4, spacing3=6,
                            yscrollcommand=sb.set, cursor="arrow", insertwidth=0)
        self.text.pack(side="left", fill="both", expand=True)
        sb.config(command=self.text.yview)
        self.text.tag_configure("head", font=self.head, foreground="#8a8a8a", spacing1=20)
        for name, col in COLORS.items():
            self.text.tag_configure(name, foreground=col)
            self.text.tag_configure(name + "_b", foreground=col, font=self.bold)

        self.bind_keys()
        self.reload()
        self.apply_ontop()
        self.apply_affinity()
        root.after(200, self.apply_affinity)
        self.tick()
        self._held = set()
        self.keep_above()
        self.poll_global_keys()
        self.text.focus_set()

        if selftest:
            root.after(3000, self.finish_selftest)

    # ---- stay above a fullscreen slideshow, and take keys while the slides have focus ----
    def keep_above(self):
        """A fullscreen slideshow is itself a topmost window and jumps in front when clicked.
        Put this window back on top a few times a second, without taking focus from the slides."""
        if sys.platform == "win32" and self.ontop.get():
            try:
                user32 = ctypes.WinDLL("user32")
                user32.GetParent.restype = ctypes.c_void_p
                user32.GetParent.argtypes = [ctypes.c_void_p]
                user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
                hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                # HWND_TOPMOST = -1; flags: SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
                user32.SetWindowPos(hwnd, ctypes.c_void_p(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
            except Exception:
                pass
        self.root.after(300, self.keep_above)

    def poll_global_keys(self):
        """Ctrl+Alt+Down / Up scroll, Ctrl+Alt+Space starts or pauses the timer, Ctrl+Alt+R resets it.
        Read with GetAsyncKeyState, so they work while the slideshow has the keyboard."""
        if sys.platform == "win32":
            try:
                user32 = ctypes.WinDLL("user32")
                down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)
                mods = down(0x11) and down(0x12)          # Ctrl and Alt
                if mods and down(0x28):                    # Down: repeats while held
                    self.scroll("units", 1)
                if mods and down(0x26):                    # Up
                    self.scroll("units", -1)
                for vk, action in ((0x20, self.toggle), (0x52, self.reset)):   # Space, R: once per press
                    if mods and down(vk):
                        if vk not in self._held:
                            self._held.add(vk)
                            action(None)
                    else:
                        self._held.discard(vk)
            except Exception:
                pass
        self.root.after(70, self.poll_global_keys)

    # ---- capture exclusion ----
    def apply_affinity(self):
        if sys.platform != "win32":
            self.affinity = "NOT hidden: not Windows"
        else:
            try:
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.GetParent.restype = ctypes.c_void_p
                user32.GetParent.argtypes = [ctypes.c_void_p]
                user32.SetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                user32.SetWindowDisplayAffinity.restype = ctypes.c_int
                self.root.update_idletasks()
                hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
                if user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
                    self.affinity = "Hidden from screen capture"
                else:
                    err = ctypes.get_last_error()
                    if user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR):
                        self.affinity = ("NOT hidden: exclude failed (error %d); "
                                         "window shows black in captures instead" % err)
                    else:
                        self.affinity = ("NOT hidden: SetWindowDisplayAffinity failed (error %d)"
                                         % ctypes.get_last_error())
            except Exception as exc:  # noqa: BLE001
                self.affinity = "NOT hidden: %s" % exc
        ok = self.affinity.startswith("Hidden")
        self.status.config(text=self.affinity, fg="#2e7d32" if ok else "#c62828")

    # ---- content ----
    def reload(self):
        try:
            self.slides = load_slides()
        except Exception as exc:  # noqa: BLE001
            self.slides = []
            self.text.config(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("end", "Could not read content.json:\n" + str(exc))
            self.text.config(state="disabled")
            return
        pos = self.text.yview()[0]
        t = self.text
        t.config(state="normal")
        t.delete("1.0", "end")
        for i, s in enumerate(self.slides, 1):
            parts = ["Slide %d" % i, s["title"], s["speaker"]]
            if s.get("seconds"):
                parts.append("%s s" % s["seconds"])
            t.insert("end", " · ".join(p for p in parts if p) + "\n", "head")
            sp = s["speaker"]
            tag = sp if sp in COLORS else "Hengyi"
            t.insert("end", sp + "\n", tag + "_b")
            for line in sentences(s["notes"]):
                t.insert("end", line + "\n", tag)
        demo = load_demo()
        if demo:
            parts = [demo.get("title", "Website"), demo.get("speaker", "")]
            if demo.get("seconds"):
                parts.append("%s s" % demo["seconds"])
            t.insert("end", " · ".join(p for p in parts if p) + "\n", "head")
            if demo.get("before"):
                t.insert("end", demo["before"] + "\n", "head")
            for n, step in enumerate(demo.get("steps", []), 1):
                t.insert("end", "DO %d: %s\n" % (n, step.get("do", "")), "Mohammed_b")
                for line in sentences(step.get("say", "")):
                    t.insert("end", line + "\n", "Hengyi")
        t.config(state="disabled")
        t.yview_moveto(pos)
        total, per = word_counts(self.slides)
        self.words.config(text="%d words  ·  Hengyi %d  ·  Mohammed %d"
                          % (total, per.get("Hengyi", 0), per.get("Mohammed", 0)))

    # ---- timer ----
    def now_elapsed(self):
        if self.running:
            return self.elapsed + (time.monotonic() - self.started_at)
        return self.elapsed

    def toggle(self, _e=None):
        if self.running:
            self.elapsed = self.now_elapsed()
            self.running = False
            self.start_btn.config(text="Start")
        else:
            self.started_at = time.monotonic()
            self.running = True
            self.start_btn.config(text="Pause")
        return "break"

    def reset(self, _e=None):
        self.running = False
        self.elapsed = 0.0
        self.start_btn.config(text="Start")
        return "break"

    def tick(self):
        e = int(self.now_elapsed())
        col = "#222"
        if e >= TARGET:
            col = "#c62828"
        elif e >= AMBER_AT:
            col = "#e08a00"
        self.timer.config(text="%02d:%02d" % (e // 60, e % 60), fg=col)
        self.root.after(200, self.tick)

    # ---- view ----
    def zoom(self, d):
        self.size = max(10, min(48, self.size + d))
        self.body.configure(size=self.size)
        self.bold.configure(size=self.size)
        self.head.configure(size=max(9, self.size - 7))
        return "break"

    def opacity(self, d):
        self.alpha = round(max(0.4, min(1.0, self.alpha + d)), 2)
        self.root.attributes("-alpha", self.alpha)
        self.alpha_lbl.config(text="%d%%" % round(self.alpha * 100))
        return "break"

    def apply_ontop(self):
        self.root.attributes("-topmost", bool(self.ontop.get()))

    def scroll(self, what, n):
        self.text.yview_scroll(n, what)
        return "break"

    def bind_keys(self):
        r = self.root

        def brk(fn):
            return lambda e: (fn(), "break")[1]

        r.bind_all("<space>", self.toggle)
        r.bind_all("<r>", self.reset)
        r.bind_all("<R>", self.reset)
        r.bind_all("<F5>", brk(self.reload))
        r.bind_all("<Escape>", lambda e: "break")
        for seq in ("<Control-plus>", "<Control-equal>", "<Control-KP_Add>"):
            r.bind_all(seq, lambda e: self.zoom(1))
        for seq in ("<Control-minus>", "<Control-KP_Subtract>"):
            r.bind_all(seq, lambda e: self.zoom(-1))
        r.bind_all("<Control-Up>", lambda e: self.opacity(0.1))
        r.bind_all("<Control-Down>", lambda e: self.opacity(-0.1))
        r.bind_all("<Up>", lambda e: self.scroll("units", -2))
        r.bind_all("<Down>", lambda e: self.scroll("units", 2))
        r.bind_all("<Prior>", lambda e: self.scroll("pages", -1))
        r.bind_all("<Next>", lambda e: self.scroll("pages", 1))
        r.bind_all("<Home>", brk(lambda: self.text.yview_moveto(0)))
        r.bind_all("<End>", brk(lambda: self.text.yview_moveto(1)))
        r.bind_all("<Control-MouseWheel>", lambda e: self.zoom(1 if e.delta > 0 else -1))
        r.bind_all("<MouseWheel>", lambda e: self.scroll("units", -3 if e.delta > 0 else 3))

    def finish_selftest(self):
        total, per = word_counts(self.slides)
        print("affinity:", self.affinity)
        print("slides:", len(self.slides))
        print("words: total %d, Hengyi %d, Mohammed %d"
              % (total, per.get("Hengyi", 0), per.get("Mohammed", 0)))
        sys.stdout.flush()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    root = tk.Tk()
    Prompter(root, selftest="--selftest" in sys.argv)
    root.mainloop()


if __name__ == "__main__":
    main()
