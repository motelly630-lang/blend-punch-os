/** @type {import('tailwindcss').Config} */
// Tailwind 정적 빌드 설정 — CDN(cdn.tailwindcss.com) 대체용.
// content 를 스캔해 실제로 쓰인 클래스만 CSS 로 생성한다.
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./static/**/*.js",
    "./app/**/*.py", // 파이썬에서 문자열로 박아둔 클래스도 포함
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Noto Sans KR", "system-ui", "sans-serif"],
      },
    },
  },
  // Jinja 보간(bg-{{ color }}-50 등)·JS 동적 조합으로 만들어지는 클래스는
  // content 스캔에 안 잡히므로 아래 패턴으로 강제 포함(safelist).
  safelist: [
    {
      pattern:
        /(bg|text|border|border-l|ring)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|gray|slate|zinc|neutral|stone)-(50|100|200|300|400|500|600|700|800|900)/,
    },
    // ring offset / 상태 배지에서 쓰는 유틸
    { pattern: /ring-(offset-)?[0-9]/ },
  ],
};
