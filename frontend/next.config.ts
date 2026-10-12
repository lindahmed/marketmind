import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone", poweredByHeader: false,
  turbopack: { root: process.cwd() }, outputFileTracingRoot: process.cwd(),
};
export default config;
