"use client";

import { NextIntlClientProvider } from "next-intl";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

import enMessages from "../../messages/en.json";
import jaMessages from "../../messages/ja.json";
import type { Locale } from "../i18n/config";

const messages = {
  en: enMessages,
  ja: jaMessages,
} satisfies Record<Locale, typeof enMessages>;

type LanguageContextValue = {
  locale: Locale;
  setLocale: (locale: Locale) => void;
};

const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({
  children,
  initialLocale,
}: {
  children: React.ReactNode;
  initialLocale: Locale;
}) {
  const [locale, setLocaleState] = useState(initialLocale);

  const setLocale = useCallback((nextLocale: Locale) => {
    setLocaleState(nextLocale);
    document.documentElement.lang = nextLocale;
    document.cookie = `mimamori-locale=${nextLocale}; path=/; max-age=31536000; samesite=lax`;
  }, []);

  const contextValue = useMemo(
    () => ({ locale, setLocale }),
    [locale, setLocale],
  );

  return (
    <LanguageContext.Provider value={contextValue}>
      <NextIntlClientProvider
        locale={locale}
        messages={messages[locale]}
        timeZone="Asia/Tokyo"
      >
        {children}
      </NextIntlClientProvider>
    </LanguageContext.Provider>
  );
}

export function useLanguage() {
  const context = useContext(LanguageContext);

  if (!context) {
    throw new Error("useLanguage must be used within LanguageProvider");
  }

  return context;
}
