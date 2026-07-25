"use client";

import { Globe2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { useLanguage } from "../app/language-provider";
import type { Locale } from "../i18n/config";

export function LanguageSelect() {
  const t = useTranslations("Dashboard");
  const { locale, setLocale } = useLanguage();

  return (
    <label className="filter-control language-control">
      <Globe2 size={18} />
      <select
        aria-label={t("changeLanguage")}
        onChange={(event) => setLocale(event.target.value as Locale)}
        value={locale}
      >
        <option value="en">English</option>
        <option value="ja">日本語</option>
      </select>
    </label>
  );
}
