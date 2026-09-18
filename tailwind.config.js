/** Tailwind build config — compiles web/tailwind.css → web/static/app.css.
 *
 *  npm run css        (one-off, minified — run before committing UI changes)
 *  npm run css:watch  (dev loop)
 *
 * Design tokens live here. The `zinc` scale is deliberately overridden with
 * the SIGNAL ink palette (navy-tinted, not neutral gray) so every existing
 * `zinc-*` utility in the templates picks up the theme without a rewrite.
 * Contrast on the page background #0A0E1A:
 *   zinc-500 (tertiary text)   6.2:1   zinc-600 (disabled/decor)  3.3:1
 *   zinc-400 (secondary text)  9.1:1   zinc-300 / 100 (body)      >12:1
 */
module.exports = {
  content: [
    "./web/templates/**/*.html",
    "./web/app.py",          // CLASSIFICATION_PALETTE class strings
  ],
  theme: {
    extend: {
      colors: {
        zinc: {
          50:  "#F5F7FB",
          100: "#E6E9F2",   // text-primary (soft, not pure white)
          200: "#CDD3E1",
          300: "#B4BCCF",
          400: "#98A2BA",   // text-secondary
          500: "#7C8AA3",   // text-tertiary / labels
          600: "#5A6580",   // disabled, decorative
          700: "#2E3A52",   // hover borders, dim marks
          800: "#1D2536",   // borders
          900: "#111827",   // surface
          950: "#0A0E1A",   // page
        },
        signal: {            // brand accent (LIVE dot, focus ring, selection)
          DEFAULT: "#FB7185",
          soft: "rgba(251, 113, 133, 0.14)",
        },
        data: {              // chart series hue — never a status color
          DEFAULT: "#3987E5",
          soft: "rgba(57, 135, 229, 0.12)",
        },
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        display: ['"Chakra Petch"', '"IBM Plex Sans"', "sans-serif"],
        mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
      },
      boxShadow: {
        // Layered depth (bencium "impact" doctrine) instead of glass.
        card: "0 1px 0 0 rgba(255,255,255,0.03) inset, 0 2px 4px rgba(0,0,0,0.25), 0 8px 24px -12px rgba(0,0,0,0.6)",
        raised: "0 1px 0 0 rgba(255,255,255,0.04) inset, 0 4px 8px rgba(0,0,0,0.3), 0 16px 40px -16px rgba(0,0,0,0.7)",
        panel: "0 24px 64px -24px rgba(0,0,0,0.8), 0 0 0 1px rgba(255,255,255,0.04)",
      },
      transitionTimingFunction: {
        enter: "cubic-bezier(0, 0, 0.2, 1)",
        exit: "cubic-bezier(0.4, 0, 1, 1)",
        state: "cubic-bezier(0.4, 0, 0.2, 1)",
      },
      maxWidth: { page: "1440px" },
    },
  },
  plugins: [
    require("@tailwindcss/forms")({ strategy: "class" }),
    require("@tailwindcss/typography"),
  ],
};
