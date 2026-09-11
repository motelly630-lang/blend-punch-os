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
  //
  // ⚠️ 패턴에 ^...$ 앵커를 반드시 유지할 것.
  // 앵커가 없으면 `hover:bg-red-500` 같은 변형 이름이 부분일치로 전부 걸려서
  // Tailwind 가 모든 변형을 생성한다 — 실제로 그래서 app.css 가 1.34MB(셀렉터 24,997개)
  // 까지 부풀었다. 앵커를 넣으면 263KB(셀렉터 약 3,800개)로 줄고 화면은 동일하다.
  //
  // variants 는 "동적으로 조합되는 것만" 최소로 적는다. 현재 hover 가 필요한 이유:
  //   app/templates/companies/detail.html   — hover:border-{{ plan_color }}-200, hover:bg-{{ plan_color }}-50
  //   app/templates/feature_flags/index.html — hover:border-{{ plan_color }}-200
  // 정적으로 쓰인 변형(예: focus:ring-blue-500)은 content 스캔이 잡으므로 여기 적지 않는다.
  safelist: [
    {
      pattern:
        /^(bg|text|border|border-l|ring)-(red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose|gray|slate|zinc|neutral|stone)-(50|100|200|300|400|500|600|700|800|900)$/,
      variants: ["hover"],
    },
    // ring offset / 상태 배지에서 쓰는 유틸
    { pattern: /^ring-(offset-)?[0-9]$/ },
  ],
};
