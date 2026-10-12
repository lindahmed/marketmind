import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MarketMind AI | Business intelligence",
  description: "Understand your performance. Build a more profitable business.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
