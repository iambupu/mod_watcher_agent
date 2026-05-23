import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhCN from "@/locales/zh-CN.json";
import enUS from "@/locales/en-US.json";
import jaJP from "@/locales/ja-JP.json";

i18n.use(initReactI18next).init({
  resources: {
    "zh-CN": { translation: zhCN },
    "en-US": { translation: enUS },
    "ja-JP": { translation: jaJP },
  },
  lng: localStorage.getItem("i18nextLng") || "zh-CN",
  fallbackLng: "en-US",
  interpolation: {
    escapeValue: false,
  },
});

i18n.on("languageChanged", (lng) => {
  localStorage.setItem("i18nextLng", lng);
});
