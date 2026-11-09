import { NextRequest, NextResponse } from 'next/server'

/**
 * GET /api/well-known/assetlinks
 * Rewritten by next.config.js to serve at /.well-known/assetlinks.json
 *
 * Digital Asset Links verification for HAVEN Android TWA.
 * Android Chrome verifies this URL during app install / first launch to authorize full-screen TWA mode.
 *
 * PRODUCTION VERIFIED FINGERPRINT:
 *   Extracted and verified from haven/android/app/haven-release.keystore
 *   via keytool and apksigner:
 *   84:E7:3D:E4:6A:41:C3:DB:0B:78:36:F2:DB:74:FE:4B:90:57:A5:BB:A1:E8:0A:0B:D3:44:38:58:32:6F:5B:99
 *
 * GOOGLE PLAY APP SIGNING:
 *   When the AAB is published via Google Play Console with Play App Signing,
 *   retrieve the production app signing certificate from:
 *   Google Play Console -> Release -> Setup -> App Signing
 *   and append its SHA-256 fingerprint to this list.
 */

const assetLinks = [
  {
    relation: ['delegate_permission/common.handle_all_urls'],
    target: {
      namespace: 'android_app',
      package_name: 'com.haven.android',
      sha256_cert_fingerprints: [
        // Verified Production Release Keystore (haven-release.keystore)
        '84:E7:3D:E4:6A:41:C3:DB:0B:78:36:F2:DB:74:FE:4B:90:57:A5:BB:A1:E8:0A:0B:D3:44:38:58:32:6F:5B:99',
      ],
    },
  },
]

export async function GET(_req: NextRequest) {
  return NextResponse.json(assetLinks, {
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'public, max-age=3600',
    },
  })
}
