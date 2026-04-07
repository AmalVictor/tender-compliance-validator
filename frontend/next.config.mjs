/** @type {import('next').NextConfig} */
const nextConfig = {
    webpack: (config, { dev }) => {
      // 1. Prevents server-side canvas errors
      config.resolve.alias.canvas = false;
      config.resolve.alias.encoding = false;
      
      return config;
    },
  };
  
  export default nextConfig;