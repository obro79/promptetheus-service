import path from "node:path";

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  eslint: { ignoreDuringBuilds: true },
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  experimental: {
    outputFileTracingRoot: path.join(process.cwd(), "../../"),
  },
};

export default nextConfig;
