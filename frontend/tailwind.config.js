/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', '"Noto Sans Devanagari"', "system-ui", "sans-serif"],
      },
      colors: {
        canvas: token("canvas"),
        surface: token("surface"),
        "surface-2": token("surface-2"),
        sunken: token("sunken"),
        line: token("line"),
        ink: token("ink"),
        "ink-2": token("ink-2"),
        "ink-3": token("ink-3"),
        brand: token("brand"),
        "brand-ink": token("brand-ink"),
        "brand-soft": token("brand-soft"),
        accent: token("accent"),
        bubble: token("bubble"),
        "bubble-in": token("bubble-in"),
        danger: token("danger"),
        "danger-soft": token("danger-soft"),
        warn: token("warn"),
        "warn-soft": token("warn-soft"),
      },
      boxShadow: {
        bubble: "0 1px 0.5px rgb(0 0 0 / 0.08)",
        panel: "0 8px 30px -12px rgb(15 23 42 / 0.25)",
        pop: "0 12px 40px -8px rgb(15 23 42 / 0.28)",
      },
      borderRadius: { bubble: "14px" },
      keyframes: {
        shimmer: { "100%": { transform: "translateX(100%)" } },
        "fade-up": { from: { opacity: 0, transform: "translateY(4px)" }, to: { opacity: 1, transform: "none" } },
        "slide-in": { from: { transform: "translateX(16px)", opacity: 0 }, to: { transform: "none", opacity: 1 } },
      },
      animation: {
        shimmer: "shimmer 1.4s infinite",
        "fade-up": "fade-up 180ms ease-out",
        "slide-in": "slide-in 200ms ease-out",
      },
    },
  },
  plugins: [],
};
