import {
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type User,
} from 'firebase/auth'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { auth, configured } from './firebase'

const MESSAGES: Record<string, string> = {
  'auth/invalid-credential': 'That email and password don\'t match an account.',
  'auth/invalid-email': 'That doesn\'t look like an email address.',
  'auth/user-not-found': 'No account with that email. Create one below.',
  'auth/wrong-password': 'Wrong password.',
  'auth/email-already-in-use': 'There is already an account with that email. Sign in instead.',
  'auth/weak-password': 'Use at least 6 characters.',
  'auth/popup-closed-by-user': 'The Google window was closed before finishing.',
  'auth/popup-blocked': 'Your browser blocked the Google window. Allow pop-ups for this site and try again.',
  'auth/unauthorized-domain': 'This site\'s address isn\'t on the Firebase list of authorized domains yet.',
  'auth/operation-not-allowed': 'This sign-in method is switched off in the Firebase console.',
  'auth/network-request-failed': 'Network problem. Check your connection and try again.',
  'auth/too-many-requests': 'Too many attempts. Wait a minute and try again.',
}
const explain = (e: unknown) => {
  const code = (e as { code?: string })?.code ?? ''
  return MESSAGES[code] ?? `Sign-in failed (${code || 'unknown error'}).`
}

export default function Account({ user, sync }: { user: User | null; sync: string }) {
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'in' | 'new'>('in')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    const onDown = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onDown)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onDown)
    }
  }, [open])

  useEffect(() => {
    if (user) {
      setPassword('')
      setError('')
    }
  }, [user])

  async function run(fn: () => Promise<unknown>) {
    setBusy(true)
    setError('')
    try {
      await fn()
      setOpen(false)
    } catch (e) {
      setError(explain(e))
    } finally {
      setBusy(false)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    if (!auth) return
    const a = auth
    void run(() => (mode === 'in' ? signInWithEmailAndPassword(a, email.trim(), password) : createUserWithEmailAndPassword(a, email.trim(), password)))
  }

  const name = user?.displayName || user?.email?.split('@')[0]

  return (
    <div className="account" ref={box}>
      <button className="account-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        {user ? name : 'Sign in'}
      </button>
      {open && (
        <div className="account-panel" role="dialog" aria-label="Account">
          {!configured || !auth ? (
            <p className="account-note">Sign-in isn't set up on this copy of the site yet. Your favorites and history are kept in this browser.</p>
          ) : user ? (
            <>
              <p className="label" style={{ margin: 0 }}>
                Signed in
              </p>
              <p className="account-who">{user.email}</p>
              <p className="account-note">Favorites and history are saved to {sync}.</p>
              <button className="btn" disabled={busy} onClick={() => auth && run(() => signOut(auth!))}>
                Sign out
              </button>
            </>
          ) : (
            <>
              <p className="label" style={{ margin: 0 }}>
                {mode === 'in' ? 'Sign in' : 'Create an account'}
              </p>
              <p className="account-note">Keeps your favorite stations and past lookups across devices.</p>
              <button className="btn wide" disabled={busy} onClick={() => auth && run(() => signInWithPopup(auth!, new GoogleAuthProvider()))}>
                Continue with Google
              </button>
              <div className="or">or</div>
              <form onSubmit={submit}>
                <label>
                  Email
                  <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    autoComplete={mode === 'in' ? 'current-password' : 'new-password'}
                    required
                    minLength={6}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </label>
                {error && (
                  <p className="account-error" role="alert">
                    {error}
                  </p>
                )}
                <button className="btn solid wide" type="submit" disabled={busy}>
                  {busy ? 'One moment…' : mode === 'in' ? 'Sign in' : 'Create account'}
                </button>
              </form>
              <button className="linkish" onClick={() => (setMode(mode === 'in' ? 'new' : 'in'), setError(''))}>
                {mode === 'in' ? 'New here? Create an account' : 'Have an account? Sign in'}
              </button>
            </>
          )}
        </div>
      )}
    </div>
  )
}
