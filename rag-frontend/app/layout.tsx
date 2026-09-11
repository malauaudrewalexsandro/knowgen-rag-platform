import type { Metadata } from "next";
import { Source_Serif_4, Inter } from "next/font/google";
import "./globals.css";

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-serif",
});

const sans = Inter({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});

export const metadata: Metadata = {
  title: "Dokumen — RAG Assistant",
  description: "Tanya jawab berbasis dokumen dengan sitasi sumber.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id" className={`${serif.variable} ${sans.variable}`}>
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
