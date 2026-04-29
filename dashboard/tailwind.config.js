/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        gray: {
          950: '#0a0a0f',
          900: '#111827',
          800: '#1f2937',
          700: '#374151',
        },
      },
    },
  },
  plugins: [],
}
