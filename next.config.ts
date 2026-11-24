import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Pastki chap burchakdagi Next.js "N" belgisini (dev indicator) ko'rsatmaslik
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    // Uy papkasidagi boshqa package-lock.json bilan adashmaslik uchun
    root: process.cwd(),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
