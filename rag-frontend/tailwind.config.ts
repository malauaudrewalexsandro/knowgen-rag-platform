import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paper: "#F1F2ED",
        "paper-raised": "#FFFFFF",
        ink: "#1C2333",
        "ink-soft": "#5B6472",
        "ink-faint": "#8991A0",
        line: "#D8DBD3",
        amber: {
          DEFAULT: "#C1861F",
          soft: "#F3E3C4",
        },
        teal: {
          DEFAULT: "#2F6F6B",
          soft: "#E4EEEC",
          deep: "#1F4B48",
        },
      },
      fontFamily: {
        serif: ["var(--font-serif)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(28, 35, 51, 0.06), 0 1px 1px rgba(28, 35, 51, 0.04)",
      },
    },
  },
  plugins: [],
};
export default config;
