import { Fraunces, Work_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const fraunces = Fraunces({ subsets: ["latin"], variable: "--font-display", weight: ["500", "600"] });
const workSans = Work_Sans({ subsets: ["latin"], variable: "--font-body" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-mono" });

export const metadata = { title: "RAGInGoa", description: "Voice-enabled RAG over MSMARCO-XI", icons: {
    icon: { url: "/favicon.webp", type: "image/webp" }, }, };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className={`${fraunces.variable} ${workSans.variable} ${jetbrainsMono.variable}`}>
        {children}
      </body>
    </html>
  );
}