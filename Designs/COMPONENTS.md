# COMPONENTS — Jinja2 컴포넌트 매크로 규격

> **코드(`src/web/templates/components/*.html`)와 다르면 코드가 이긴다.** 토큰 값은 `DESIGN.md` / `tokens.css` 참고.
> 규칙: hex 직접 사용 금지, 토큰 기반 유틸만, 그림자 없음, 숫자는 `.num`(tabular). `attrs` 인자는 개발자가 넣는 신뢰된 문자열(`|safe` 로 출력)이므로 사용자 입력을 넣지 않는다.

사용법 예: `{% from "components/button.html" import button %}{{ button("새 여행 계획", icon="plus") }}`

## 1. button (`button.html`)

`button(label, variant="primary", size="md", icon=None, attrs="", disabled=False, loading=False, type="button")`

| variant | 배경 | 글자 | 테두리 | 호버 |
|---|---|---|---|---|
| primary | `bg-accent` | `text-accent-fg` | transparent | `bg-accent-hover` |
| secondary | `bg-surface` | `text-text` | `border-border` | `bg-surface-muted` |
| ghost | transparent | `text-text-muted` | transparent | `bg-surface-muted`, `text-text` |
| danger | `bg-surface` | `text-danger` | `border-danger` | `bg-surface-muted` |

| size | 높이 | 가로 패딩 | 글자 크기 / line-height | radius | 아이콘 |
|---|---|---|---|---|---|
| sm | 32px (`h-8`) | 12px (`px-3`) | 14px / 20px (`text-sm leading-5`) | `rounded-control` | 16px |
| md | 40px (`h-10`) | 16px (`px-4`) | 14px / 20px | `rounded-control` | 16px |
| lg | 48px (`h-12`) | 20px (`px-5`) | 16px / 24px (`text-base leading-6`) | `rounded-control` | 16px |

- 공통: `font-medium`, `gap-2`, 1px 테두리.
- 상태: 기본 / 호버 / 포커스(전역 `:focus-visible` 링, `--color-focus`) / 비활성(`disabled`, 불투명도 50%, `cursor-not-allowed`) / 로딩(`loading=True`: `disabled` + `aria-busy="true"`, 아이콘 대신 스피너, 스크린리더용 "(처리 중)").
- 아이콘 이름: `send, plus, refresh, check, alert, info, x, file, chevron, clock, arrow-up, arrow-down, sparkle` (`_icons.html`).
- 접근성: 아이콘은 `aria-hidden`, 텍스트 라벨 필수. 터치 높이 sm 32px 는 보조 행동에만, 주요 모바일 행동은 md 이상.

## 2. card (`card.html`)

`{% call card(title, subtitle=None, badge=None, state="default", message=None, action=None, fallback=False) %}본문{% endcall %}`

| 요소 | 규격 |
|---|---|
| 컨테이너 | `rounded-card border border-border bg-surface p-5` (20px 패딩) |
| 제목 | `text-base font-semibold leading-6 text-text` (16/24, `<h3>`) |
| 부제 | `text-sm leading-5 text-text-muted` (14/20) |
| 헤더 간격 | 본문과 16px (`mb-4`) |
| 배지 슬롯 | 헤더 오른쪽. `badge` 에 `badge()` 렌더 결과 전달 |

| state | 표시 |
|---|---|
| default | `caller()` 본문 |
| loading | `skeleton(3)`, `aria-busy="true"` |
| empty | `message`(기본 "아직 표시할 내용이 없어요.", `text-sm leading-6 text-text-muted`) + `action`(예: `example_chip` 렌더 결과) |
| error | `role="alert"`, 경고 아이콘 + `message`(`text-danger`). `fallback=True` 면 헤더에 "예시 데이터"(warning 배지) 표시 + 본문(caller)을 예시로 함께 표시 |

- 접근성: `<section aria-labelledby>` 로 제목 연결. 오류는 색 + 아이콘 + 문장. 빈 상태는 다음 행동을 안내한다. 권한 없음 상태는 해당 없음(항목 숨김).

## 3. badge (`badge.html`)

`badge(text, tone="neutral")` — 모양: `rounded-pill border h-6 px-2 text-xs leading-4 font-medium gap-1`, 아이콘 12px + 텍스트.

| tone | 배경 | 글자·아이콘 | 테두리 | 아이콘 |
|---|---|---|---|---|
| neutral | `bg-surface-muted` | `text-text-muted` | `border-border` | info |
| accent | `bg-accent-soft` | `text-accent` | transparent | sparkle |
| success | `bg-surface-muted` | `text-success` | `border-border` | check |
| warning | `bg-surface-muted` | `text-warning` | `border-border` | alert |
| danger | `bg-surface-muted` | `text-danger` | `border-border` | alert |

- 접근성: 색만으로 전달하지 않는다(아이콘 + 텍스트 항상 같이). 대비비는 `DESIGN.md` 4.1 참고(모두 AA 이상).

## 4. chip (`chip.html`)

| 매크로 | 시그니처 | 규격 |
|---|---|---|
| 출처 칩 | `source_chip(city, section=None)` 예: `도쿄 가이드 · 음식과 맛집` (파일명·title 없음) | `rounded-pill border border-border bg-surface-muted h-6 px-2.5 text-xs leading-4 text-text-muted`, 파일명 `font-medium text-text`, 파일 아이콘 12px, 길면 `truncate`, `title` 로 전체 표시 |
| 예시 질문 | `example_chip(text, attrs="")` | `<button>`: `rounded-pill border border-border bg-surface h-8 px-3 text-sm leading-5 text-text`, 호버 `border-accent text-accent` |

- 접근성: 출처 칩은 정보 표시(비상호작용). 예시 질문은 버튼이며 키보드 포커스 가능. 클릭 동작은 `attrs`(hx-* / data-*)로 연결.

## 5. message (`message.html`)

`message(role, content, sources=[], trace=None)` — `sources: [{file, section}]`, `trace: trace()의 steps`

| role | 컨테이너 | 글자 |
|---|---|---|
| user | 오른쪽 정렬, `max-w-[85%] rounded-card bg-accent px-3.5 py-2.5` | `text-accent-fg text-sm leading-6` |
| assistant | 왼쪽 아바타 + `max-w-[85%] rounded-card bg-surface-muted px-3.5 py-2.5`, 내부 간격 12px (9-1 참고) | `text-text text-sm leading-6` |

- assistant 구성 순서: 본문 → 출처 칩 줄(`source_chip`, `gap-1.5`, `aria-label="출처"`) → `<details>` "실행 흐름 보기"(`text-xs leading-4 text-text-muted`, 펼치면 `trace`).
- 본문은 `whitespace-pre-wrap break-words`(줄바꿈 보존, 375px 가로 스크롤 방지). `trace` 가 비어 있으면 실행 흐름 슬롯을 그리지 않는다.
- 접근성: `<details>`/`<summary>` 기본 키보드 지원. 스트리밍 영역의 `aria-live` 는 화면 템플릿에서 스레드 컨테이너에 지정한다.

## 6. trace (`trace.html`)

`trace(steps)` — `steps: [{node, status, ms}]`

| status | 점 색 | 텍스트 |
|---|---|---|
| pending | `bg-border` | 대기 |
| running | `bg-accent animate-pulse` | 실행 중 |
| success | `bg-success` | 완료 |
| error | `bg-danger` | 오류 |
| fallback | `bg-warning` | 예시 데이터 |

- 행: `flex items-center gap-3 px-3 py-2 text-sm leading-5`, 행 사이 `divide-border`, 컨테이너 `rounded-control border border-border bg-surface`.
- 노드명 `font-mono text-text`(말줄임), 상태 텍스트 `text-xs text-text-muted`, 소요 시간 `.num w-16 text-right text-xs text-text-muted`("12 ms", 값이 없으면 "—"). 점 8px.
- 접근성: 상태를 점 색 + 텍스트로 이중 표기. `<ol aria-label="실행 흐름">`. 펄스는 `prefers-reduced-motion` 에서 정지.

## 7. chat_input (`input.html`)

`chat_input(placeholder="여행에 대해 물어보세요", attrs="", name="message")` — `attrs` 는 `<form>` 에 붙는다(hx-post 등).

| 요소 | 규격 |
|---|---|
| 컨테이너 | `rounded-card border border-border bg-surface p-2`, `focus-within:border-accent` |
| textarea | `min-h-10 max-h-40 text-sm leading-6 px-2 py-2`, 투명 배경, placeholder `text-text-muted`, 크기 조절 없음(`resize-none`), 높이 자동 확장은 페이지 JS |
| 전송 버튼 | `button("보내기", primary, md, icon="send", type="submit")` |
| 안내 문구 | "Enter로 전송, Shift+Enter로 줄바꿈" `text-xs leading-4 text-text-muted` |

- 접근성: 숨김 `<label>`(`sr-only`) 연결. 키 동작(Enter/Shift+Enter)은 화면 단계 JS에서 구현하고 이 안내 문구와 일치시킨다. 포커스는 컨테이너 테두리 + 전역 포커스 링.

## 8. skeleton (`skeleton.html`)

`skeleton(lines=3)` — 줄당 `.skeleton-bar h-4`(16px, `bg-surface-muted`, `rounded-control`, 펄스 1.4s), 줄 간격 12px, 마지막 줄 `w-2/3`. `role="status"` + 스크린리더 "불러오는 중". reduced-motion 에서는 애니메이션 정지.

## 9. stat (`stat.html`)

`stat(label, value, unit=None, delta=None, delta_label=None)` — V-F 단일 지표. `delta` 는 숫자.

| 요소 | 규격 |
|---|---|
| 라벨 | `text-sm leading-5 text-text-muted` (14/20) |
| 값 | `.num text-3xl font-semibold leading-9 text-text` (30/36) |
| 단위 | `text-base font-medium leading-6 text-text-muted` (16/24), 값 뒤 4px |
| 증감 | `.num text-sm leading-5 font-medium` (14/20), 화살표 14px + 부호 + 절댓값 + `delta_label`(`font-normal text-text-muted`) |

| delta | 색 | 표시 |
|---|---|---|
| > 0 | `text-up` | 위 화살표 + "+" |
| < 0 | `text-down` | 아래 화살표 + "−"(U+2212) |
| = 0 | `text-text-muted` | 부호·화살표 없이 "0 변동 없음" |
| None | — | 증감 줄 생략 |

- 접근성: 색 + 화살표 + 부호 + 텍스트를 함께 표시(색만으로 전달 금지). 환율·기온은 참고값이므로 실시간 깜빡임 효과를 쓰지 않는다.

## 9-1. chat widget · FAB · bubble · typing (`index.html` 의 `widget` 블록, `message.html`)

| 항목 | 규격 |
|---|---|
| FAB | `#chat-fab`, 오른쪽 아래 고정 `h-14 w-14 rounded-pill bg-accent text-accent-fg`. `aria-label` "AI 여행 비서 열기", `aria-expanded`, `aria-controls="chat-widget"`. 열리면 아이콘이 ✕로 바뀌고 라벨은 "닫기". 알림 점 `#chat-dot`(`bg-danger` + `border-surface`, sr-only "새 답변")은 닫힌 동안 답변이 오면 표시 |
| chat widget | `#chat-widget` `role="dialog"` `aria-label="AI 여행 비서"`. sm 이상 `w-96`(24rem) · `h-[min(40rem,calc(100dvh-7rem))]` · `rounded-card border border-border bg-surface`, 640px 미만 `inset-0` 전체 화면 시트. 구성: 헤더(아바타·제목·상태·새 대화·닫기) / `#thread`(`role="log"`) / 입력창 |
| bubble | 봇: 아바타(`bg-accent-soft`) + `bg-surface-muted rounded-card px-3.5 py-2.5`. 사용자: `bg-accent text-accent-fg`, 오른쪽. 시간은 `.num text-xs text-text-muted`. `message(role, content, sources, trace, time, live)` 와 `bot_avatar()` |
| typing | 봇 말풍선 안 `.typing-dot` 3개. `motion-reduce` 에서는 점을 숨기고 "답변 작성 중…" 텍스트만 표시 |

- 그림자·그라디언트 없이 테두리와 토큰 색으로만 떠 보이게 한다. 포인트 컬러는 FAB·사용자 말풍선·전송 버튼에만 쓴다.

## 9-2. GNB · carousel · course card · 도시 일러스트 (랜딩)

- **GNB** (`partials/gnb.html`, `gnb_search.html`): 랜딩과 `/planner` 공용. 로고 `<a href="/">`, 검색 `role="search"`(Enter → `GET /search`), 여행지 드롭다운(`aria-haspopup`, `aria-expanded`, Esc 닫기), 1024px 미만 햄버거 → 전체메뉴 패널(`data-action="open-gnb"`). 모달을 여는 모든 요소는 `data-plan-dest`, `data-plan-days`, `data-plan-places`(`|` 구분)를 쓴다.
- **carousel** (`landing.html` #hero, `landing.js`): `aria-roledescription="carousel"`, 슬라이드 `aria-roledescription="slide"` + "n / 5", 이전·다음 원형 버튼, 점 인디케이터(`aria-label`, `aria-current`), 일시정지 버튼. 6초 자동 넘김, 호버·포커스 시 멈춤, reduced-motion 이면 자동 넘김 없음, 좌우 키.
- **course card**: `article` 안에 썸네일(일러스트 또는 `image`), 국가 라벨, 제목 버튼(`after:absolute after:inset-0` 로 카드 전체가 눌림), 해시태그 줄, "1인 예상 경비 약 OO만원~", "참고용 · 항공 제외".
- **도시 일러스트** (`illustrations/{city}.svg.html`, `_all.html` 의 `illustration()`/`media()`): 평면 SVG, 색은 `--color-dest-*` 토큰 클래스만. `image` 필드가 있으면 `<img>` 로 교체.
- **내 여행 계획 카드·삭제 대화상자** (`landing.html` 의 `<template>`, `partials/confirm_delete.html`): 로컬 저장본 카드. "이 기기에서 삭제"는 `<dialog>` 확인 후 로컬 항목만 지운다.

## 10. 공통 CSS 유틸 (`app.src.css`)

| 클래스 | 역할 |
|---|---|
| `.num` | `font-variant-numeric: tabular-nums`. 숫자 열은 `text-right` 와 함께 |
| `.skeleton-bar` | 스켈레톤 줄 |
| `.spinner` | 버튼 로딩 스피너 |
| `.typing-dot` | 봇 타이핑 점(바운스, reduced-motion 에서는 템플릿이 숨김) |
| `:focus-visible` | 2px `--color-focus` 아웃라인, offset 2px (전역) |
| `prefers-reduced-motion` | 애니메이션·전환 사실상 제거 (전역) |
