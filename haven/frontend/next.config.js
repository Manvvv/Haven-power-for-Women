/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    domains: ['res.cloudinary.com'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  },
  // Fix for tunnel/external URL navigation
  assetPrefix: process.env.ASSET_PREFIX || '',
  trailingSlash: false,
}

module.exports = nextConfig
