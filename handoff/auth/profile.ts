import { onAuthStateChanged, type User } from 'firebase/auth'
import { doc, getDoc, setDoc } from 'firebase/firestore'
import { useCallback, useEffect, useRef, useState } from 'react'
import { auth, db } from './firebase'

export type Search = { station: string; date: string; at: number }
export type Profile = {
  favorites: string[]
  visits: Record<string, number> // station code -> how many times you looked it up
  searches: Search[] // newest first
}

const EMPTY: Profile = { favorites: [], visits: {}, searches: [] }
const MAX_SEARCHES = 12
const key = (uid: string | null) => `rbr.profile.${uid ?? 'guest'}`

function readLocal(uid: string | null): Profile {
  try {
    const raw = localStorage.getItem(key(uid))
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY
  } catch {
    return EMPTY
  }
}
function writeLocal(uid: string | null, p: Profile) {
  try {
    localStorage.setItem(key(uid), JSON.stringify(p))
  } catch {
    /* private mode or storage full: the profile just won't persist */
  }
}

export function useUser() {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(!auth)
  useEffect(() => {
    if (!auth) return
    return onAuthStateChanged(auth, (u) => {
      setUser(u)
      setReady(true)
    })
  }, [])
  return { user, ready }
}

/**
 * Favorites, visit counts and recent searches.
 * Signed out: kept in this browser. Signed in: kept in Firestore at users/{uid} and mirrored locally,
 * so it follows you across devices. If Firestore can't be reached, it keeps working locally.
 */
export function useProfile(user: User | null) {
  const uid = user?.uid ?? null
  const [profile, setProfile] = useState<Profile>(() => readLocal(null))
  const [sync, setSync] = useState<'this browser' | 'your account' | 'this browser (cloud save failed)'>('this browser')
  const loaded = useRef(false)

  useEffect(() => {
    loaded.current = false
    let cancelled = false
    const local = readLocal(uid)
    setProfile(local)
    if (!uid || !db) {
      setSync('this browser')
      loaded.current = true
      return
    }
    getDoc(doc(db, 'users', uid))
      .then((snap) => {
        if (cancelled) return
        if (snap.exists()) {
          const remote = { ...EMPTY, ...(snap.data() as Partial<Profile>) }
          setProfile(remote)
          writeLocal(uid, remote)
        } else {
          // first sign-in: carry over what this browser already knew
          const guest = readLocal(null)
          const start = guest.searches.length || guest.favorites.length ? guest : local
          setProfile(start)
          void setDoc(doc(db!, 'users', uid), start)
        }
        setSync('your account')
      })
      .catch(() => !cancelled && setSync('this browser (cloud save failed)'))
      .finally(() => {
        loaded.current = true
      })
    return () => {
      cancelled = true
    }
  }, [uid])

  const save = useCallback(
    (next: Profile) => {
      setProfile(next)
      writeLocal(uid, next)
      if (uid && db && loaded.current) {
        setDoc(doc(db, 'users', uid), next)
          .then(() => setSync('your account'))
          .catch(() => setSync('this browser (cloud save failed)'))
      }
    },
    [uid],
  )

  const toggleFavorite = useCallback(
    (station: string) => {
      const has = profile.favorites.includes(station)
      save({ ...profile, favorites: has ? profile.favorites.filter((s) => s !== station) : [...profile.favorites, station] })
    },
    [profile, save],
  )

  const recordSearch = useCallback(
    (station: string, date: string) => {
      const last = profile.searches[0]
      if (last && last.station === station && last.date === date) return
      const searches = [{ station, date, at: Date.now() }, ...profile.searches.filter((s) => !(s.station === station && s.date === date))].slice(
        0,
        MAX_SEARCHES,
      )
      save({ ...profile, searches, visits: { ...profile.visits, [station]: (profile.visits[station] ?? 0) + 1 } })
    },
    [profile, save],
  )

  const clearHistory = useCallback(() => save({ ...profile, searches: [], visits: {} }), [profile, save])

  const mostVisited = Object.entries(profile.visits)
    .sort((a, b) => b[1] - a[1])
    .map(([s]) => s)

  return { profile, sync, toggleFavorite, recordSearch, clearHistory, mostVisited }
}
