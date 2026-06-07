import { useEffect, useState } from 'react'

export function useLiveAge(refreshedAt: number | null) {
  const [age, setAge] = useState(0)

  useEffect(() => {
    if (!refreshedAt) return
    const tick = () => setAge(Math.floor((Date.now() - refreshedAt) / 1000))
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [refreshedAt])

  if (!refreshedAt) return null
  if (age < 5) return 'just now'
  if (age < 60) return `${age}s ago`
  return `${Math.floor(age / 60)}m ago`
}
