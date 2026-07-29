import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "@/locales/en/common.json";
import he from "@/locales/he/common.json";

export const LANGUAGES = { he: { name: "עברית", dir: "rtl" }, en: { name: "English", dir: "ltr" } } as const;

export type Language = keyof typeof LANGUAGES;

const STORAGE_KEY = "money.language";

function initialLanguage(): Language {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored && stored in LANGUAGES) return stored as Language;
  return navigator.language.startsWith("he") ? "he" : "en";
}

void i18n.use(initReactI18next).init({
  resources: { en: { common: en }, he: { common: he } },
  lng: initialLanguage(),
  // English is the source of truth for keys: a missing Hebrew string shows readable English
  // rather than a raw key like "month.readyToAssign".
  fallbackLng: "en",
  defaultNS: "common",
  interpolation: { escapeValue: false },
});

/** Apply the language to the document. Direction lives on <html> and the tree inherits it. */
export function applyLanguage(language: Language): void {
  localStorage.setItem(STORAGE_KEY, language);
  document.documentElement.lang = language;
  document.documentElement.dir = LANGUAGES[language].dir;
}

applyLanguage(i18n.language as Language);
i18n.on("languageChanged", (language) => applyLanguage(language as Language));

export default i18n;
