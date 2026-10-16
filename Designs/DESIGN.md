# DESIGN — 스마트 여행 비서 디자인 토큰과 방향

> **코드(`src/web/static/css/tokens.css`)와 다르면 코드가 이긴다.** 이 문서는 코드를 설명하는 표일 뿐이며, 값을 바꿀 때는 `tokens.css`를 먼저 고치고 이 표를 맞춘다.
> 컴포넌트 규격은 `COMPONENTS.md`, 화면 패턴 근거는 `DASHBOARD_PATTERNS.md`·`DASHBOARD_VISUAL.md`.

## 1. 두 겹 표기

`A + 고유(여행 보드) + AI 패널 · 시각 V-L(#53), 결과 카드 V-F(#17, #25)` / 트레이딩 적합도: 부적합 / 기본 테마: 라이트(다크 지원)

## 2. 레퍼런스와 방향

| 구분 | 내용 |
|---|---|
| V-L (#53) | AI 코파일럿 패널. 주 콘텐츠 옆에 대화 패널을 둔다. 메시지 스레드, 출처 칩, 입력창, 예시 질문 |
| V-F (#17, #25) | 결과 카드. 한 카드에 지표 하나(`stat`)를 크게, 보조 정보는 작게 |
| 방향 | 라이트 기본 + 다크 지원, 포인트컬러 1개(딥 오션 블루), 그림자 대신 1px 테두리, 숫자는 tabular |
| 가져오지 않을 것 | 캔들·호가창, 네온 다크, 글로우·그라디언트(셸·카드), KPI 카드 나열, 게이지·도넛, 차트 라이브러리, 목업 연출, 보라 계열 |

## 3. 금지 사항

- 템플릿·CSS에 hex 직접 사용 금지. 색은 토큰 기반 유틸만(`bg-surface`, `text-text-muted`, `border-border`, `rounded-card`, `bg-accent`). 검증: `grep -rn "#[0-9A-Fa-f]\{6\}" src/web/templates` 결과 0건.
- 포인트컬러는 화면당 1개. CTA·선택 상태·진행·현재 위치에만. 보라 금지.
- 그림자(`shadow-*`) 금지. 구분은 테두리와 면 명도차로.
- 색만으로 상태 전달 금지. 부호(+/−)·아이콘·텍스트를 함께 쓴다.
- `tailwind.config.js`, `@tailwind base` 같은 v3 문법 금지. Tailwind v4 CSS 우선 문법(`@import "tailwindcss"`, `@theme`, `@custom-variant`, `@source`)만.
- 상승·하락색(`--color-up`/`--color-down`)을 브랜드·CTA에 쓰지 않는다. 의미는 증감뿐이다(여행 앱은 환율·기온 변화 등 참고값 표시용).

## 4. 토큰 표

대비비는 WCAG 2.x 상대 휘도 공식으로 직접 계산했다(소수 둘째 자리 반올림). 기준: 일반 텍스트 4.5:1, 큰 글씨·UI 3:1.

### 4.1 색

| 토큰 | 라이트 | 다크 | 용도 | 대비비 (라이트 / 다크) |
|---|---|---|---|---|
| `--color-bg` | `#F3F5F8` | `#0C1117` | 페이지 배경 | 표면과 면 구분용(대비 규정 없음) |
| `--color-surface` | `#FFFFFF` | `#141B23` | 카드·패널·입력 면 | 배경 대비 명도차 약 4~6% |
| `--color-surface-muted` | `#EAEEF3` | `#1B242E` | 보조 면(칩, 호버, 스켈레톤, 배지 바탕) | text/muted 15.03 / 13.32 |
| `--color-border` | `#E2E6EC` | `#27323F` | 구분선 | 장식용. surface 대비 1.25 / 1.33 (아래 메모) |
| `--color-text` | `#121A24` | `#E8EDF2` | 본문 | bg 16.04 / 16.09, surface 17.52 / 14.72 |
| `--color-text-muted` | `#4A5868` | `#9CA9B8` | 보조 글자, 라벨 | bg 6.66 / 7.92, surface 7.27 / 7.25, muted 6.24 / 6.56 |
| `--color-accent` | `#0B6E99` | `#4DB2E0` | CTA 배경, 링크, 선택 상태 | bg 5.19 / 7.90, surface 5.67 / 7.24 |
| `--color-accent-hover` | `#085879` | `#79C7EB` | CTA 호버 | accent-fg 대비 7.83 / 8.84 |
| `--color-accent-fg` | `#FFFFFF` | `#05212F` | accent 위 글자 | accent 대비 5.67 / 6.92 |
| `--color-accent-soft` | `#E0EFF6` | `#12303F` | 포인트 배지 바탕 | accent 글자 4.82 / 5.76, text 14.89 / 11.73, text-muted 6.18 / 5.78 |
| `--color-up` | `#17794A` | `#4CC38A` | 증가(초록 계열) | bg 4.97 / 8.55, surface 5.43 / 7.83 |
| `--color-down` | `#B8322C` | `#FF8077` | 감소(빨강 계열) | bg 5.45 / 7.77, surface 5.95 / 7.11 |
| `--color-success` | `#17794A` | `#4CC38A` | 성공 상태 | surface 5.43 / 7.83, surface-muted 4.66 / 7.08 |
| `--color-warning` | `#8A5200` | `#E9B24C` | 경고·예시 데이터 | surface 6.39 / 9.03, surface-muted 5.48 / 8.17 |
| `--color-danger` | `#B8322C` | `#FF8077` | 오류·삭제 | surface 5.95 / 7.11, surface-muted 5.10 / 6.43 |
| `--color-focus` | `#0B6E99` | `#79C7EB` | 포커스 링(2px, offset 2px) | bg 5.19 / 10.09, surface 5.67 / 9.24 (UI 3:1 이상) |

보조 확인값(라이트 / 다크): up·down·success·warning·danger 가 accent-soft 위에 놓일 때 4.61~5.43 / 5.66~7.19 로 모두 AA 이상.

**테두리 메모**: `--color-border` 는 카드·표 구분 같은 장식 경계이며 대비 3:1 미만이다(WCAG 1.4.11 은 정보 전달에 필수인 경계에만 적용). 입력창은 `focus-within:border-accent` + 포커스 링으로 상호작용 상태를 별도로 드러낸다. 입력 경계가 유일한 식별 수단이 되는 새 컴포넌트를 만들 때는 더 진한 경계 토큰을 추가해 검토한다.

### 4.2 모서리·글꼴

| 토큰 | 값 | 용도 / Tailwind 유틸 |
|---|---|---|
| `--radius-control` | 0.5rem (8px) | 버튼·입력·트레이스 목록 / `rounded-control` |
| `--radius-card` | 0.75rem (12px) | 카드·메시지 말풍선·입력 컨테이너 / `rounded-card` |
| `--radius-pill` | 9999px | 배지·칩·상태 점 / `rounded-pill` |
| `--font-sans` | Pretendard Variable, Pretendard, 시스템 폰트(-apple-system, Segoe UI, Apple SD Gothic Neo, Noto Sans KR, Malgun Gothic, system-ui) | 전체 글꼴. Pretendard 파일이 없으면 시스템 폰트로 자동 폴백 |

### 4.3 선택 규칙

- 다크 값은 `[data-theme="dark"]` 에서 같은 변수를 재정의한다. `@custom-variant dark` 로 `dark:` 유틸도 `data-theme="dark"` 기준으로 동작한다.
- `prefers-color-scheme: dark` 는 `<html>` 에 `data-theme` 속성이 없을 때만 적용된다(`:root:not([data-theme])`). 사용자가 테마를 직접 고르면 `data-theme="light|dark"` 를 설정해 OS 설정을 덮는다.
- `tokens.css` 안에 다크 값이 두 곳(명시 선택, OS 따름)에 있으므로 수정 시 둘을 함께 고친다.

## 5. 명도 관계 (DASHBOARD_VISUAL 6.4 대응)

| 역할 | 6.4 참고값 (라이트 / 다크) | 이 프로젝트 (라이트 / 다크) | 비고 |
|---|---|---|---|
| 배경 | `#F3F5F8` / `#0B0E14` | `#F3F5F8` / `#0C1117` | 라이트는 그대로, 다크는 푸른 톤 유지 |
| 표면 | `#FFFFFF` / `#141922` | `#FFFFFF` / `#141B23` | 그림자 없이 테두리로 분리 |
| 구분선 | `#E2E6EC` / `#232A36` | `#E2E6EC` / `#27323F` | 다크는 약간 밝혀 구분 확보 |
| 포인트 | 보라(예시) | `#0B6E99` / `#4DB2E0` | 딥 오션 블루. 보라는 쓰지 않음(6.2 제품 간 구분) |

## 6. 다음 단계 연결

- 빌드: `tailwindcss -i src/web/static/css/app.src.css -o src/web/static/css/app.css` (standalone CLI, 4.x 고정). `app.src.css` 가 `@source "../../templates/**/*.html"` 로 템플릿 클래스를 스캔한다.
- 화면(`base.html`, `index.html`, `/dev/components`)은 다음 단계에서 이 토큰과 `templates/components/*.html` 매크로만 사용한다.
