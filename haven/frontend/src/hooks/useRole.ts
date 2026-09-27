import { useUser } from '@clerk/nextjs'
import { useEffect, useState } from 'react'

export function useRole() {
  const { user, isLoaded } = useUser()
  const [role, setRole] = useState<'user' | 'authority' | 'admin'>('user')

  useEffect(() => {
    if (typeof window !== 'undefined') {
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
    isUser: role === 'user'
  }
}
