import { useUser } from '@clerk/nextjs'
import { useEffect, useState } from 'react'

export function useRole() {
  const { user, isLoaded } = useUser()
  const [role, setRole] = useState<'user' | 'authority' | 'admin' | 'responder'>('user')

  useEffect(() => {
    if (typeof window !== 'undefined') {
      // A field-responder session is tracked separately from the authority token
      // slot so the two never collide. Role still comes from the verified backend
      // token on every request — this is only a client-side UI hint.
      const responderRole = sessionStorage.getItem('haven_responder_role')
      if (responderRole === 'responder') {
        setRole('responder')
        return
      }
      const authRole = sessionStorage.getItem('haven_authority_role')
      if (authRole === 'authority') {
        setRole('authority')
        return
      }
      if (authRole === 'admin') {
        setRole('admin')
        return
      }
    }

    if (user) {
      const metaRole = user.publicMetadata?.role as string
      if (metaRole === 'admin') {
        setRole('admin')
      } else if (metaRole === 'authority') {
        setRole('authority')
      } else {
        setRole('user')
      }
    }
  }, [user])

  return {
    isLoaded,
    role,
    isAuthority: role === 'authority',
    isAdmin: role === 'admin',
    isUser: role === 'user',
    isResponder: role === 'responder'
  }
}
