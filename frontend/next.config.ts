import type { NextConfig } from "next";
if (process.env.DEPLOYMENT_ENVIRONMENT === "production" && process.env.NEXT_PUBLIC_API_URL) {
  throw new Error("Production uses the same-origin API proxy; remove NEXT_PUBLIC_API_URL");
}
const config: NextConfig = {
  output: "standalone", poweredByHeader: false,
  turbopack: { root: process.cwd() }, outputFileTracingRoot: process.cwd(),
  async headers() {
    return [{ source: "/:path*", headers: [
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      { key: "X-Frame-Options", value: "DENY" },
      ...(process.env.DEPLOYMENT_ENVIRONMENT === "production"
        ? [{ key: "Strict-Transport-Security", value: "max-age=31536000" }] : []),
    ] }];
  },
};
export default config;
