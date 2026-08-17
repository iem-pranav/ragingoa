import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination:
          process.env.NODE_ENV === "development"
            ? "http://127.0.0.1:5328/api/:path*"   // local Flask dev server only
            : "/api/:path*",                          // production: Vercel routes this
                                                        // straight to the Python serverless
                                                        // function itself, no rewrite needed
      },
    ];
  },
};

export default nextConfig;