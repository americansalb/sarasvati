/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  swcMinify: true,

  // Enable WebSocket support
  webpack: (config, { isServer }) => {
    if (!isServer) {
      config.resolve.fallback = {
        ...config.resolve.fallback,
        net: false,
        tls: false,
        fs: false,
      };
    }
    return config;
  },

  // Environment variables
  env: {
    NEXT_PUBLIC_LIVEKIT_URL: process.env.NEXT_PUBLIC_LIVEKIT_URL || 'ws://localhost:7880',
    NEXT_PUBLIC_BACKEND_WS_URL: process.env.NEXT_PUBLIC_BACKEND_WS_URL || 'http://localhost:3001',
    NEXT_PUBLIC_ROOM_NAME: process.env.NEXT_PUBLIC_ROOM_NAME || 'sarasvati-session',
  },

  // Image optimization
  images: {
    domains: ['localhost'],
  },
};

export default nextConfig;
