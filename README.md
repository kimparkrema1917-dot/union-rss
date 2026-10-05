# 단체별 RSS 수집기

공개 게시판을 매시간 확인하고, **단체마다 RSS 2.0 피드를 하나씩** 만듭니다.
GitHub Actions에서 수집하고 GitHub Pages에서 피드와 구독 안내 페이지를 제공합니다.
API 키, AI 서비스, 별도 데이터베이스는 필요하지 않습니다.

## 수집 대상과 피드

| 단체 | 수집 범위 | RSS 파일 |
|---|---|---|
| 공공운수노조 | [주요소식](https://www.kptu.net/board/list.aspx?mid=BCB52DDC) | `feeds/kptu.xml` |
| 금속노조 | [보도자료·성명](https://kmwu.kr/bbs/board.php?bo_table=ce_B12) | `feeds/kmwu.xml` |
| 전국결집 | [소식지](https://leftall.com/bbs/board.php?bo_table=newsletter) | `feeds/leftall.xml` |
| 기후정의동맹 | [홈페이지](https://www.climatejusticealliance.kr/)의 알립니다·성명 및 자료·활동 소식 | `feeds/climatejusticealliance.xml` |

**공공운수노조의 현재 제한:** 2026-10-06 확인 당시 [robots.txt](https://www.kptu.net/robots.txt)는 일반 로봇의 접근을 막고 네이버 Yeti에만 별도 규칙을 두고 있습니다. 이 프로젝트는 Yeti로 가장하지 않습니다. 따라서 공공운수노조 피드는 생성되지만 현재 기본 실행에서는 **수집 보류·0건**입니다. 사이트 측에서 UnionRSS의 접근을 허용하면 자동으로 수집을 시작합니다. 해당 게시판 파서는 실제 공개 목록 자료로 검증했습니다. 나머지 세 단체는 자동 수집 가능합니다.

## GitHub에 올리고 구독하기

### 1. 공개 저장소 만들기

GitHub에서 **New repository**를 선택합니다.

- 이름 예: `union-rss`
- 공개 여부: **Public** — 무료 GitHub Pages를 사용하기 위한 선택입니다.
- 기본 브랜치: **main**

압축을 푼 `union-rss` **폴더 안의 내용**을 저장소 맨 위에 올립니다. `collector.py`, `sources.json`, `requirements.txt`, `tests`, `data`, `.github`가 같은 위치에 있어야 합니다. `union-rss` 폴더가 저장소 안에 한 겹 더 들어가지 않게 하세요.

**`.github` 폴더를 반드시 포함하세요.** 자동 실행 설정이 들어 있습니다. Mac Finder에서 숨겨진 파일을 표시하려면 `Command + Shift + .`를 누릅니다. ZIP 파일 자체만 업로드하면 자동 실행되지 않습니다. 생성 결과인 `site`는 올리지 않아도 됩니다.

터미널로 올리는 경우에는 이 폴더에서 다음 순서로 진행할 수 있습니다. `YOUR_ID`와 저장소 이름은 실제 값으로 바꿉니다. 새 GitHub 저장소는 README 없이 비워 두세요.

```sh
git init -b main
git add .
git commit -m "Add organization RSS collectors"
git remote add origin https://github.com/YOUR_ID/union-rss.git
git push -u origin main
```

### 2. Pages 활성화

저장소의 **Settings → Pages → Build and deployment → Source**에서 **GitHub Actions**를 선택합니다.

### 3. 자동 실행의 저장 권한 확인

**Settings → Actions → General → Workflow permissions**에서 **Read and write permissions**를 선택하고 저장합니다. 프로젝트의 자동 실행은 `data/state.json`에 수집 기록을 저장하므로 저장소 쓰기 권한이 필요합니다. 공개되는 데이터는 수집한 제목·요약·원문 주소와 수집 상태입니다.

조직 정책이나 브랜치 보호 규칙이 자동 커밋을 막으면 설정을 조정해야 합니다. 강제 푸시는 하지 않습니다.

### 4. 첫 실행

**Actions → Update RSS feeds → Run workflow → Run workflow**를 선택합니다.

처음에는 **약 3~5분**이 걸릴 수 있습니다. 금속노조가 `Crawl-delay: 180`을 지정해서 첫 robots.txt 확인 뒤 게시판을 읽기 전에 3분을 기다립니다. 이후에는 robots.txt를 24시간 캐시하므로 대부분 더 빠릅니다. 실제 소요 시간은 사이트 응답과 GitHub 대기열에 따라 달라집니다.

업로드 직후 Pages 설정 전 자동 실행이 실패했다면, 위 설정을 마친 뒤 수동으로 다시 실행하면 됩니다.

### 5. RSS 주소 구독

배포가 끝나면 **Settings → Pages**에 실제 사이트 주소가 표시됩니다. 예를 들어 주소가 다음과 같다면:

```text
https://YOUR_ID.github.io/union-rss/
```

피드 주소는 다음과 같습니다.

```text
https://YOUR_ID.github.io/union-rss/feeds/kptu.xml
https://YOUR_ID.github.io/union-rss/feeds/kmwu.xml
https://YOUR_ID.github.io/union-rss/feeds/leftall.xml
https://YOUR_ID.github.io/union-rss/feeds/climatejusticealliance.xml
```

각 주소를 RSS 리더에 추가하세요. 사이트 첫 화면에서 주소를 찾을 수 있고, `feeds.opml`을 가져오면 네 피드를 한 번에 등록할 수 있습니다. **위 주소의 YOUR_ID는 예시이며 실제 공개 주소는 아직 생성되지 않았습니다.**

## 무엇이 수집되나요?

- 제목, 원문 주소, 게시 날짜, 분류를 제공합니다. 공공운수노조는 허용 후 목록에 있는 요약도 포함합니다.
- 한글·PDF 첨부파일이나 이미지에서 본문을 추출하지 않습니다. 전체 내용은 원문 링크에서 읽습니다.
- 금속노조는 제목이 잘리지 않도록 PC 화면을 읽고, 상단 고정 공지는 기본적으로 제외합니다.
- 전국결집은 제목 안의 날짜가 아니라 실제 목록의 등록일을 사용합니다.
- 기후정의동맹은 공개 홈페이지에 포함된 Oopy/Notion 데이터에서 세 목록의 글만 읽습니다. 로그인이나 Notion API 키를 사용하지 않습니다. 공개된 **페이지 생성 시각**을 사용하며, 실제 발표 시각과 다를 수 있음을 피드에 명시합니다.
- 날짜만 제공하는 게시판의 시각은 한국시간 00:00으로 표시합니다. 수집한 시각을 게시 시각으로 바꾸지 않습니다.
- RSS 항목 고유번호는 게시물 ID에 고정됩니다. 재실행·제목 수정·원문 주소의 페이지 번호 변화로 같은 글을 새 글처럼 중복 생성하지 않습니다.

## 수집 주기와 보관

기본값은 **매시간 17분**입니다. 한국에서도 매시간 17분에 해당하며, GitHub의 실행 지연이 있을 수 있습니다. `.github/workflows/rss.yml`의 설정을 바꿀 수 있습니다.

```yaml
schedule:
  - cron: '17 * * * *'       # 매시간 17분
# - cron: '17 */2 * * *'    # 두 시간마다
# - cron: '17,47 * * * *'   # 30분마다
```

각 게시판의 **첫 페이지**, 기후정의동맹은 **홈페이지에 처음 표시되는 세 목록**만 확인합니다. 과거 전체 글을 처음부터 긁지 않습니다. 실행 중 발견한 글을 누적해 단체별 최근 200건까지 보관합니다. `sources.json`의 `max_items`로 보관 수를 바꿀 수 있습니다.

첫 실행 시점에 목록에 보이는 기존 글도 피드에 들어갑니다. 장기간 실행이 멈추거나 다음 실행 전 첫 페이지보다 많은 글이 올라오면 일부 글을 놓칠 수 있습니다. 게시판에서 삭제된 글도 이미 저장돼 있으면 보관 한도까지 남습니다.

금속노조 상단 고정 공지까지 포함하려면 `sources.json`의 `include_pinned`를 `true`로 바꾸세요.

기후정의동맹에서 특정 목록만 받고 싶다면 `collections` 배열을 변경합니다. 사이트의 원래 목록 이름은 `알립니다`, `성명 및 자료`, `소식`이고, 마지막 목록은 화면에 ‘활동 소식’으로 표시됩니다.

## 오류가 나면

배포 사이트의 단체 카드와 `status.json`, GitHub Actions 실행 요약에서 확인할 수 있습니다.

- `ok`: 수집 성공. 마지막 성공 시각과 보관 건수를 표시합니다.
- `blocked`: robots.txt에 따라 수집 보류. 기존 글이 있다면 유지합니다.
- `error`: 통신 또는 사이트 구조 오류. **기존 데이터를 지우지 않고** 다음 실행에 재시도합니다.
- 예상하지 못한 오류가 있으면 정상 피드와 상태 페이지를 먼저 게시한 뒤 해당 Actions 실행을 실패로 표시합니다. GitHub 알림 설정에 따라 실패 알림을 받을 수 있습니다.
- 공공운수노조의 알려진 제한만으로 매시간 실패 알림이 발생하지 않도록 `expected_robots_block`을 설정해 두었습니다. 보류 상태 자체는 화면에 계속 표시합니다.
- 게시물이 갑자기 0건으로 읽히는 경우 성공으로 처리하지 않습니다. 기존 피드를 유지하고 오류로 표시합니다.

robots.txt는 하루 한 번 갱신합니다. 사이트 측에서 접근을 허용한 직후 바로 다시 확인하려면 `data/state.json`의 `robots` 객체만 `{}`로 비우고 실행하세요. **`sources` 기록은 지우지 마세요.** 전체 기록을 지우면 RSS 리더에 과거 글이 새로 나타날 수 있습니다.

## 내 컴퓨터에서 실행

Python 3.9 이상이 필요합니다. GitHub에서는 Python 3.12를 사용합니다.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python collector.py
```

결과는 `site/feeds/`에 생성됩니다. `site/index.html`에서 상태와 각 파일을 확인할 수 있습니다. 이 상태는 로컬 파일이며 외부 RSS 리더가 접근하려면 Pages 등에서 게시해야 합니다.

이미 저장한 데이터로 파일만 다시 만들려면:

```sh
python collector.py --render-only
```

자체 호스팅 주소를 사용할 경우:

```sh
python collector.py --base-url https://example.org/union-rss
```

GitHub Actions에서는 Pages의 실제 주소를 자동으로 넣습니다. `--base-url` 없이 로컬에서 생성한 OPML은 상대 주소를 사용하므로 RSS 리더에 가져올 때는 배포된 `feeds.opml`을 사용하세요.

## 비용과 실행 환경

공개 저장소의 표준 GitHub 실행 환경 및 GitHub Pages를 이용하는 소규모 구성입니다. GitHub의 무료 사용 범위와 정책 내에서 사용할 수 있습니다. 별도 도메인은 필요 없습니다. 유료 실행 환경을 선택하거나 다른 유료 서비스를 붙이는 설정은 포함하지 않았습니다.

GitHub 예약 실행은 정확한 시각을 보장하지 않으며, 공개 저장소에 60일간 활동이 없으면 예약 실행이 비활성화될 수 있습니다. 이 프로젝트는 매번 수집 상태를 자동 커밋하므로 정상 실행 중에는 저장소 활동이 생깁니다. 장기간 중단 후에는 Actions에서 활성화 여부를 확인하세요.

- [GitHub Actions 요금](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub Pages 설정](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [예약 실행 제약](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## 파일 구성

```text
.github/workflows/rss.yml    자동 수집·기록 저장·Pages 게시
.github/workflows/test.yml   변경 시 검증
collector.py                사이트별 수집기와 RSS/OPML 생성기
sources.json                대상과 보관 설정
requirements.txt            Python 의존성
data/state.json             글 목록과 수집 이력 — 삭제하지 않기
tests/                      실제 목록을 간추린 자료와 회귀 테스트
site/                       실행 시 생성되는 공개 파일
```

이 저장소는 각 단체의 공식 서비스가 아닙니다. 게시물의 저작권은 원저작자에게 있습니다.
