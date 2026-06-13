/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000',
    NEXT_PUBLIC_WALLET_URL: process.env.NEXT_PUBLIC_WALLET_URL || 'http://127.0.0.1:8787',
  },
};
module.exports = nextConfig;
