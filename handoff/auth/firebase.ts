import { initializeApp } from 'firebase/app'
import { getAuth, type Auth } from 'firebase/auth'
import { getFirestore, type Firestore } from 'firebase/firestore'

// These are the public web identifiers from Firebase console > Project settings > Your apps.
// They are safe to ship in the browser. Access is controlled by Firebase Auth and the Firestore rules.
const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
}

export const configured = Boolean(config.apiKey && config.authDomain && config.projectId && config.appId)

let auth: Auth | null = null
let db: Firestore | null = null
if (configured) {
  const app = initializeApp(config)
  auth = getAuth(app)
  db = getFirestore(app)
}

export { auth, db }
