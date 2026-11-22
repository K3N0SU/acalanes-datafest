/* Sign-in and sync.
   The whole site works signed out. An account does one thing: it carries your saved commute to your other devices.

   - Config: public/config/firebase.json. These are Firebase's public web identifiers, not secrets;
     access is enforced by Firebase Auth and the Firestore rules (each person can touch only users/{their id}).
     If the file is missing, the Sign in button never appears and nothing else changes.
   - The Firebase SDK loads from Google's CDN after the page has drawn, so it can't hold up the forecast.
   - Sync talks to commute.js through the "commute:change" event it already sends. */

const SDK = "https://www.gstatic.com/firebasejs/13.4.0";
const COMMUTE_KEY = "rbr.commute.v1"; // same key commute.js uses

let fb = null;        // { A: auth module, F: firestore module, auth, db } once the SDK is in
let sdkReady = null;  // promise for the above
let user = null;
let sync = "idle";    // idle | saved | empty | failed
let button, dialog, body;

const MESSAGES = {
  "auth/invalid-credential": "That email and password don't match an account.",
  "auth/wrong-password": "That email and password don't match an account.",
  "auth/user-not-found": "That email and password don't match an account.",
  "auth/invalid-email": "That doesn't look like an email address.",
  "auth/missing-password": "Enter a password.",
  "auth/email-already-in-use": "There's already an account with that email. Sign in instead.",
  "auth/weak-password": "Use a password with at least 6 characters.",
  "auth/too-many-requests": "Too many tries. Wait a minute, then try again.",
  "auth/popup-blocked": "Your browser blocked the Google window. Allow pop-ups for this page and try again.",
  "auth/unauthorized-domain": "Google sign-in isn't switched on for this address yet. Email sign-in works.",
  "auth/network-request-failed": "No connection. Check your internet and try again.",
  "auth/requires-recent-login": "For safety, sign out, sign back in, then delete again.",
  "auth/account-exists-with-different-credential": "That email already has an account with a different sign-in method.",
};
const QUIET = new Set(["auth/popup-closed-by-user", "auth/cancelled-popup-request", "auth/user-cancelled"]);
const explain = (err) => (QUIET.has(err?.code) ? "" : MESSAGES[err?.code] || "That didn't work. Check your connection and try again.");

/* ---------------- Firebase ---------------- */

async function loadSdk(config) {
  const [{ initializeApp }, A, F] = await Promise.all([
    import(`${SDK}/firebase-app.js`),
    import(`${SDK}/firebase-auth.js`),
    import(`${SDK}/firebase-firestore-lite.js`),
  ]);
  const app = initializeApp(config);
  fb = { A, F, auth: A.getAuth(app), db: F.getFirestore(app) };
  A.onAuthStateChanged(fb.auth, onUser);
  return fb;
}

async function onUser(u) {
  user = u;
  sync = "idle";
  paint();
  if (!u) return;
  try { await pull(); } catch { sync = "failed"; }
  paint();
}

/* ---------------- commute sync ---------------- */

function localCommute() {
  try {
    const c = JSON.parse(localStorage.getItem(COMMUTE_KEY) || "null");
    return c && c.home && c.work ? c : null;
  } catch { return null; }
}

function adopt(c) {
  try { localStorage.setItem(COMMUTE_KEY, JSON.stringify(c)); } catch { /* private window: this visit only */ }
  window.dispatchEvent(new CustomEvent("commute:change", { detail: { ...c, _external: true } }));
}

const userDoc = () => fb.F.doc(fb.db, "users", user.uid);

async function push(c) {
  await fb.F.setDoc(userDoc(), { commute: c || null, updatedAt: Date.now() }, { merge: true });
  sync = c ? "saved" : "empty";
}

/* On sign-in the account wins if it has a commute; otherwise this browser's commute is saved to it. */
async function pull() {
  const snap = await fb.F.getDoc(userDoc());
  const remote = snap.exists() ? snap.data().commute : null;
  const local = localCommute();
  if (remote && remote.home && remote.work) {
    if (JSON.stringify(remote) !== JSON.stringify(local)) adopt(remote);
    sync = "saved";
  } else if (local) {
    await push(local);
  } else {
    sync = "empty";
  }
}

function onCommuteChange(e) {
  if (!user || !fb || e.detail?._external) return;
  const c = e.detail ? { ...e.detail } : null;
  if (c) delete c._external;
  push(c).catch(() => { sync = "failed"; }).finally(paint);
}

/* ---------------- actions ---------------- */

async function run(fn) {
  setBusy(true);
  say("");
  try {
    await sdkReady;
    await fn();
  } catch (err) {
    say(fb ? explain(err) : "Sign-in needs a connection. Everything else on this page works without it.");
  } finally {
    setBusy(false);
  }
}

const withGoogle = () => run(() => fb.A.signInWithPopup(fb.auth, new fb.A.GoogleAuthProvider()));

function withEmail(e) {
  e.preventDefault();
  const f = e.currentTarget;
  const email = f.email.value.trim();
  const password = f.password.value;
  const create = e.submitter?.value === "new";
  run(() => (create ? fb.A.createUserWithEmailAndPassword : fb.A.signInWithEmailAndPassword)(fb.auth, email, password));
}

const signOut = () => run(() => fb.A.signOut(fb.auth));

let armed = 0;
function removeAccount(btn) {
  if (Date.now() - armed > 5000) { // first press arms it, second press within 5 s deletes
    armed = Date.now();
    btn.textContent = "Press again to delete for good";
    return;
  }
  armed = 0;
  run(async () => {
    await fb.F.deleteDoc(userDoc());
    await fb.A.deleteUser(fb.auth.currentUser);
  });
}

/* ---------------- view ---------------- */

const G_MARK = `<svg viewBox="0 0 18 18" width="18" height="18" aria-hidden="true"><path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z"/><path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.84.86-3.04.86-2.34 0-4.33-1.58-5.04-3.71H.96v2.33A9 9 0 0 0 9 18z"/><path fill="#FBBC05" d="M3.96 10.71a5.41 5.41 0 0 1 0-3.42V4.96H.96a9 9 0 0 0 0 8.08l3-2.33z"/><path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.59A9 9 0 0 0 .96 4.96l3 2.33C4.67 5.16 6.66 3.58 9 3.58z"/></svg>`;

const SIGNED_OUT = `
  <h2 id="acct-title">Sign in</h2>
  <p class="acct__lede">Everything here works without an account. Sign in to keep your commute on every device you use.</p>
  <button type="button" class="acct__google" data-act="google">${G_MARK}<span>Continue with Google</span></button>
  <p class="acct__or"><span>or use email</span></p>
  <form class="acct__form" novalidate>
    <label class="acct__field"><span>Email</span>
      <input type="email" name="email" autocomplete="email" inputmode="email" spellcheck="false" required></label>
    <label class="acct__field"><span>Password</span>
      <input type="password" name="password" autocomplete="current-password" minlength="6" required></label>
    <div class="acct__row">
      <button type="submit" value="in" class="acct__primary">Sign in</button>
      <button type="submit" value="new" class="acct__ghost">Create account</button>
    </div>
  </form>
  <p class="acct__msg" role="status" aria-live="polite"></p>`;

const SIGNED_IN = `
  <h2 id="acct-title">Your account</h2>
  <p class="acct__who"></p>
  <p class="acct__sync"></p>
  <div class="acct__row">
    <button type="button" class="acct__primary" data-act="out">Sign out</button>
    <a class="acct__ghost" href="#yourweek" data-act="commute">My commute</a>
  </div>
  <button type="button" class="acct__danger" data-act="delete">Delete my account and data</button>
  <p class="acct__msg" role="status" aria-live="polite"></p>`;

const SYNC_TEXT = {
  idle: "Checking your account…",
  saved: "Your commute is saved to your account and follows you to any device you sign in on.",
  empty: "No commute saved yet. Set one under My commute and it will be kept here.",
  failed: "Couldn't reach your account just now. Your commute is still saved in this browser.",
};

function paint() {
  if (!button) return;
  button.textContent = user ? "Account" : "Sign in";
  button.classList.toggle("is-in", Boolean(user));
  const view = user ? "in" : "out";
  if (body.dataset.view !== view) {
    body.dataset.view = view;
    body.innerHTML = user ? SIGNED_IN : SIGNED_OUT;
    body.querySelector("form")?.addEventListener("submit", withEmail);
    armed = 0;
  }
  if (user) {
    body.querySelector(".acct__who").textContent = user.email || user.displayName || "Signed in";
    body.querySelector(".acct__sync").textContent = SYNC_TEXT[sync];
  }
}

function say(text) {
  const m = body?.querySelector(".acct__msg");
  if (m) m.textContent = text;
}

function setBusy(on) {
  body?.querySelectorAll("button, input").forEach((n) => { n.disabled = on; });
  dialog?.classList.toggle("is-busy", on);
}

function onBodyClick(e) {
  const act = e.target.closest("[data-act]")?.dataset.act;
  if (act === "google") withGoogle();
  if (act === "out") signOut();
  if (act === "delete") removeAccount(e.target.closest("[data-act]"));
  if (act === "commute") dialog.close();
}

function build() {
  const css = document.createElement("link");
  css.rel = "stylesheet";
  css.href = new URL("./account.css", import.meta.url).href;
  document.head.append(css);

  button = document.createElement("button");
  button.type = "button";
  button.className = "acct-btn";
  button.setAttribute("aria-haspopup", "dialog");
  button.addEventListener("click", () => { say(""); dialog.showModal(); });

  dialog = document.createElement("dialog");
  dialog.className = "acct";
  dialog.setAttribute("aria-labelledby", "acct-title");
  dialog.innerHTML = `
    <button type="button" class="acct__close" aria-label="Close">
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true"><path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
    </button>
    <div class="acct__body"></div>`;
  body = dialog.querySelector(".acct__body");
  dialog.querySelector(".acct__close").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); }); // click on the backdrop
  body.addEventListener("click", onBodyClick);

  document.getElementById("nav")?.append(button);
  document.body.append(dialog);
  paint();
}

export async function initAccount() {
  let config = null;
  try {
    const r = await fetch("./config/firebase.json", { cache: "no-store" });
    if (r.ok) config = await r.json();
  } catch { /* no config: no sign-in */ }
  if (!config?.apiKey || !config?.projectId || !config?.appId) return;

  build();
  window.addEventListener("commute:change", onCommuteChange);
  sdkReady = loadSdk(config);
  sdkReady.catch(() => { /* offline: the button still opens the panel, which says why it can't sign in */ });
}
