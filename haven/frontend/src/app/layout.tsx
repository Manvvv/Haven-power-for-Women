import type { Metadata } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { LanguageProvider } from '@/components/LanguageContext'
import './globals.css'

export const metadata: Metadata = {
  title: 'Haven — A Silent Shield, A Strong Voice',
  description: 'AI-powered platform empowering women in abusive situations.',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>
          <LanguageProvider>
            {children}
          </LanguageProvider>
        </body>
      </html>
    </ClerkProvider>
  )
}