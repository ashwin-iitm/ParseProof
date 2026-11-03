/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`;
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: v("paper"), panel: v("panel"), surface: v("surface"),
        ink: { DEFAULT: v("ink"), 2: v("ink-2"), 3: v("ink-3") },
        line: { DEFAULT: v("line"), strong: v("line-strong") },
        accent: { DEFAULT: v("accent"), hover: v("accent-hover"), weak: v("accent-weak") },
        pass: { DEFAULT: v("pass"), weak: v("pass-weak") },
        fail: { DEFAULT: v("fail"), weak: v("fail-weak") },
        review: { DEFAULT: v("review"), weak: v("review-weak") },
        mark: v("mark"),
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      fontSize: {
        xs: ["12px", "16px"], sm: ["13px", "18px"], base: ["14px", "20px"],
        md: ["16px", "22px"], lg: ["18px", "24px"], xl: ["22px", "28px"],
      },
      borderRadius: { DEFAULT: "6px", md: "6px", lg: "8px" },
      boxShadow: { float: "0 4px 16px rgb(27 29 33 / 0.10), 0 1px 2px rgb(27 29 33 / 0.06)" },
    },
  },
  plugins: [],
};
