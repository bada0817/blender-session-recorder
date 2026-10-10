# Session Recorder

블렌더에서 한 작업을 `.blend` 파일 옆에 **순서대로 기록**하는 Blender 확장(5.1+).
Claude/MCP 없이 블렌더 안에서 혼자 동작합니다. 기록은 나중에 학습 노트(The Daily Blender)를 쓸 때 재료로 씁니다.

## 기록되는 것

| 이벤트 `ev` | 내용 | 출처 |
|---|---|---|
| `session_start` / `session_end` | 녹화 시작(제목 `title`) / 종료(`comment`, `reason`, 동작 수 `ops`, 걸린 시간 `minutes`) | Start/Stop 버튼 |
| `op` | 실행한 동작과 **값** (`mesh.bevel(offset=0.03, segments=2)`). 기본값 인자는 생략 | Info 에디터 리포트 |
| `prop` | 패널에서 바꾼 값 (`bpy.context.object.modifiers["Bevel"].width = 0.02`) | Info 에디터 리포트 |
| `undo` / `redo` | `Ctrl+Z` / `Ctrl+Shift+Z`, 연속이면 `n`으로 묶음 | undo/redo 핸들러 |
| `error` | 경고·에러 메시지 (막힌 지점 단서) | Info 에디터 리포트 |
| `info` | 그 밖의 안내 메시지 | Info 에디터 리포트 |
| `save` | 저장 + 통계 (오브젝트 수, 버텍스/면 수, 메시별 모디파이어 스택) | save 핸들러 |
| `shot` | 3D 뷰포트 스크린샷 (`shots/0007.png`)과 이유 `start`·`stop`·`save`·`mode`·`ops`·`note` | 타이머 |
| `note` | `Ctrl+Alt+N`으로 남긴 메모 | 오퍼레이터 |
| `log_created` / `continued_from` | 로그 생성 / 다른 이름으로 저장하기 전 로그 경로 | save 핸들러 |

공통 필드: `t`(로컬 시각), `mode`(동작 직후 모드), `obj`(활성 오브젝트).
엣지 루프 선택처럼 같은 클릭이 이어지면 한 줄로 묶고 `n`(횟수)과 `t_end`를 붙입니다.

```jsonl
{"t":"2026-10-10T19:12:30","ev":"op","op":"mesh.loopcut_slide","msg":"mesh.loopcut_slide(MESH_OT_loopcut={number_cuts=3, edge_index=5})","mode":"EDIT_MESH","obj":"Muzzle"}
{"t":"2026-10-10T19:13:09","ev":"op","op":"mesh.loop_select","msg":"mesh.loop_select(...)","mode":"EDIT_MESH","obj":"Muzzle","n":16,"t_end":"2026-10-10T19:13:39"}
{"t":"2026-10-10T19:13:50","ev":"op","op":"mesh.bevel","msg":"mesh.bevel(offset=0.0304854, segments=2, affect='EDGES')","mode":"EDIT_MESH","obj":"Muzzle"}
{"t":"2026-10-10T19:14:01","ev":"save","file":"muzzle.blend","stats":{"objects":3,"verts":412,"faces":398,"meshes":[...]}}
{"t":"2026-10-10T19:14:01","ev":"shot","file":"shots/0003.png","why":"save"}
```

## 파일 위치

```
muzzle_modeling.blend
muzzle_modeling_history/
├── log.jsonl      # 한 줄에 하나씩 덧붙이기만 함 (세션이 여러 번이어도 한 파일)
└── shots/0001.png …
```

- 블렌더를 닫았다 열어도, 며칠 뒤에도 같은 `log.jsonl`에 이어서 기록됩니다. 녹화 한 번이 `session_start` ~ `session_end` 한 구간입니다.
- 녹화 중에 다른 파일을 열거나 블렌더를 닫으면 `session_end`(`reason`: `file`·`exit`)로 끝납니다. 다시 Start를 눌러야 이어집니다.
- 한 번도 저장하지 않은 파일은 메모리에 모았다가 **첫 저장 때** 로그로 옮깁니다. 저장하지 않고 닫으면 확장 전용 폴더(`extensions/.user/user_default/session_recorder/unsaved/`)에 보관합니다.
- 첫 저장 시 씬에 커스텀 프로퍼티 `session_recorder_id`를 넣습니다. 다른 이름으로 저장해도 같은 작업의 로그임을 알 수 있습니다.

## 사용법

3D 뷰포트 **N 사이드바 → Recorder 탭**에서 녹화합니다. 단축키 실수로 켜고 끄는 일이 없도록 시작/종료는 버튼으로만 합니다.

1. **Start Recording** → 제목 입력(선택, 예: 튜토리얼 이름) → **Start**
2. 작업. 상태 표시줄에 `REC <동작 수>`가 보입니다.
3. 중간에 **`Ctrl+Alt+N`** 또는 **Add Note** 버튼: 메모 (왜 그렇게 했는지, 막힌 점, 튜토리얼 타임스탬프 …). 스크린샷도 함께 찍습니다.
4. **Stop Recording** → 세션 코멘트 입력(선택) → **Stop**

- **Settings** 하위 패널(환경설정에도 동일): 메모 단축키 변경, 자동 시작(기본 꺼짐), 뷰 설정 변경 기록 여부, 상태 표시줄 표시, 확인 주기(기본 0.25초), 스크린샷 조건(저장 시·모드 변경 시·N개 동작마다, 최소 간격 60초).
- **Open History Folder**: 이 파일의 기록 폴더 열기.

## 한계

- 뷰포트 회전·확대, Info 에디터가 보여주지 않는 일부 클릭은 기록되지 않습니다.
- `mode`/`obj`는 확인 주기만큼 늦게 읽어서, 동작 직후 모드를 바꾸면 다음 모드로 찍힐 수 있습니다.
- 좌하단 패널(F9)로 값을 고치면 블렌더는 "undo → 새 값으로 다시 실행"을 합니다. 이 둘은 한 줄로 합쳐서 **최종 값**만 남기고 `adjusted`(고친 횟수)를 붙입니다. 같은 속성을 연달아 바꿀 때(`prop`)도 마찬가지입니다.
- `Ctrl+Z` 직후 1초 안에 같은 동작을 다시 하면 조정으로 보고 합쳐질 수 있습니다.
- 화면이 바뀌지 않은 스크린샷, 5초 안에 변경 없이 다시 저장한 경우는 기록하지 않습니다. 저장 스크린샷도 최소 간격(기본 60초)을 지킵니다. 시작·종료·메모는 항상 찍습니다.
- 스크린샷은 PNG(장당 수백 KB)입니다. 발행할 때 줄여서 씁니다.

## 개발

```sh
python3 -m unittest discover -s tests   # compact.py 테스트 (블렌더 불필요)
blender --command extension build --source-dir . --output-dir /tmp
```

License: GPL-3.0-or-later
