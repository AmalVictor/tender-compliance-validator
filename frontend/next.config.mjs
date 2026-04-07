/** @type {import('next').NextConfig} */
const nextConfig = {
  turbopack: {},  // ✅ ADD THIS

  webpack: (config) => {
    config.resolve.alias.canvas = false;
    config.resolve.alias.encoding = false;
    return config;
  },
};

export default nextConfig;