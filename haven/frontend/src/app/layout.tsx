import type { Metadata, Viewport } from 'next'
import { ClerkProvider } from '@clerk/nextjs'
import { LanguageProvider } from '@/components/LanguageContext'
import QuickEscape from '@/components/QuickEscape'
import OfflineBanner from '@/components/OfflineBanner'
import './globals.css'

export const viewport: Viewport = {
  themeColor: '#be185d',
  width: 'device-width',
  initialScale: 1,
}

export const metadata: Metadata = {
  title: 'Haven — A Silent Shield, A Strong Voice',
  description: 'AI-powered platform empowering women in abusive situations.',
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'default',
    title: 'Haven',
  },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <ClerkProvider>
      <html lang="en">
        <body>
          <LanguageProvider>
            <OfflineBanner />
            <QuickEscape>
              {children}
            </QuickEscape>
          </LanguageProvider>
        </body>
      </html>
    </ClerkProvider>
  )
}