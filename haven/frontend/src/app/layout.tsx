import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { Analytics } from "@vercel/analytics/next"
import './globals.css'
export const metadata: Metadata = {
  title: 'Haven — A Silent Shield, A Strong Voice',
  description: 'AI-powered platform empowering women in abusive situations with discreet help, mental health support, and legal guidance.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>
          {children}
          <Analytics />
        </body>
      </html>
    </ClerkProvider>
  )
}
