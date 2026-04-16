'use client'
import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export function useHavenAuth() {
  const router = useRouter()
  useEffect(() => {
    if (typeof window !== 'undefined') {
      if (sessionStorage.getItem('haven_unlocked') !== 'true') {
        router.replace('/')
      }
    }
  }, [router])
}