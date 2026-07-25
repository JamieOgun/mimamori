import { match } from "@formatjs/intl-localematcher";
import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { Inter, Krub } from "next/font/google";
import Negotiator from "negotiator";

import {
  defaultLocale,
  isLocale,
  locales,
  type Locale,
} from "../i18n/config";
import "./globals.css";
import { LanguageProvider } from "./language-provider";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

const krub = Krub({
  subsets: ["latin", "thai"],
  display: "swap",
  variable: "--font-krub",
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "MimaMori Dashboard",
  description: "Care call scoring and transcript review dashboard",
};

function detectLocale(acceptLanguage: string): Locale {
  const languages = new Negotiator({
    headers: { "accept-language": acceptLanguage },
  }).languages();

  return match(languages, locales, defaultLocale) as Locale;
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const savedLocale = cookieStore.get("mimamori-locale")?.value;
  const locale = isLocale(savedLocale)
    ? savedLocale
    : detectLocale(headerStore.get("accept-language") ?? defaultLocale);

  return (
    <html lang={locale}>
      <body className={`${inter.className} ${inter.variable} ${krub.variable}`}>
        <LanguageProvider initialLocale={locale}>{children}</LanguageProvider>
      </body>
    </html>
  );
}
