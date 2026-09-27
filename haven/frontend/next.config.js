const path = require('path')
const os = require('os')

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  images: {
    domains: ['res.cloudinary.com'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
  // Fix for tunnel/external URL navigation
  assetPrefix: process.env.ASSET_PREFIX || '',
  trailingSlash: false,
  async headers() {
    return [
      {
        source: '/(.*)',
        headers: [
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-XSS-Protection', value: '1; mode=block' },
          { key: 'Permissions-Policy', value: 'camera=(self), microphone=(self), geolocation=(self)' },
        ],
      },
    ];
  },
  webpack: (config, { dev }) => {
    // Dev build cache hardening.
    // The project lives inside a OneDrive-synced folder. If webpack's filesystem
    // cache is written under the synced tree (.next/cache or node_modules/.cache),
    // OneDrive syncs those artifacts mid-write and corrupts them — which serves
    // broken/empty JS chunks and blanks pages across the whole app. We keep the
    // filesystem cache (memory cache previously hit a RangeError on large buffers)
    // but relocate it OUTSIDE OneDrive, to the OS temp dir, so sync can't touch it.
    if (dev) {
      config.cache = {
        type: 'filesystem',
        cacheDirectory: path.join(os.tmpdir(), 'haven-next-cache'),
        buildDependencies: {
          config: [__filename],
        },
      };
    }
    return config;
  },
}

module.exports = nextConfig

