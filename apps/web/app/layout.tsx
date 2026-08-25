import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  description:
    "A local-only ProxyLoop conversation UI backed by the fictional telecom Thin Runtime.",
  title: "ProxyLoop · Local demo",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
