/** @type {import('next').NextConfig} */
const nextConfig = {
  // Off: the @swype-org/deposit React hook nulls its ref in effect cleanup and
  // then reads it, which crashes under StrictMode's dev double-invoke
  // ("Cannot read properties of null (reading 'on')").
  reactStrictMode: false,
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000',
    NEXT_PUBLIC_WALLET_URL: process.env.NEXT_PUBLIC_WALLET_URL || 'http://127.0.0.1:8787',
  },
};
module.exports = nextConfig;
