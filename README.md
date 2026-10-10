# Session Recorder

블렌더에서 한 작업을 `.blend` 파일 옆에 **순서대로 기록**하는 Blender 확장(5.1+).
Claude/MCP 없이 블렌더 안에서 혼자 동작합니다. 기록은 나중에 학습 노트(The Daily Blender)를 쓸 때 재료로 씁니다.

## 기록되는 것

| 이벤트 `ev` | 내용 | 출처 |
|---|---|---|
| `session_start` / `session_end` | 블렌더 실행·파일 열기 / 종료·다른 파일 열기. 버전, 파일, 기록 ID, 세션 중 동작 수 | load/exit 핸들러 |
| `op` | 실행한 동작과 **값** (`mesh.bevel(offset=0.03, segments=2)`). 기본값 인자는 생략 | Info 에디터 리포트 |
| `prop` | 패널에서 바꾼 값 (`bpy.context.object.modifiers["Bevel"].width = 0.02`) | Info 에디터 리포트 |
| `undo` / `redo` | `Ctrl+Z` / `Ctrl+Shift+Z`, 연속이면 `n`으로 묶음 | undo/redo 핸들러 |
| `error` | 경고·에러 메시지 (막힌 지점 단서) | Info 에디터 리포트 |
| `info` | 그 밖의 안내 메시지 | Info 에디터 리포트 |
| `save` | 저장 + 통계 (오브젝트 수, 버텍스/면 수, 메시별 모디파이어 스택) | save 핸들러 |
| `shot` | 3D 뷰포트 스크린샷 (`shots/0007.png`)과 이유 `save`·`mode`·`ops`·`note` | 타이머 |
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

- 블렌더를 닫았다 열어도, 며칠 뒤에도 같은 `log.jsonl`에 이어서 기록됩니다. 세션 경계는 `session_start`로 구분합니다.
- 한 번도 저장하지 않은 파일은 메모리에 모았다가 **첫 저장 때** 로그로 옮깁니다. 저장하지 않고 닫으면 확장 전용 폴더(`extensions/.user/user_default/session_recorder/unsaved/`)에 보관합니다.
- 첫 저장 시 씬에 커스텀 프로퍼티 `session_recorder_id`를 넣습니다. 다른 이름으로 저장해도 같은 작업의 로그임을 알 수 있습니다.

## 사용법

- 설치 후 켜 두기만 하면 됩니다. 상태 표시줄에 `REC <동작 수>`가 보입니다.
- **`Ctrl+Alt+N`**: 메모 남기기 (왜 그렇게 했는지, 막힌 점, 튜토리얼 타임스탬프 …). 스크린샷도 함께 찍습니다.
- 환경설정: 일시정지, 확인 주기(기본 0.25초), 스크린샷 조건(저장 시·모드 변경 시·N개 동작마다, 최소 간격 60초), 뷰 설정 변경 기록 여부, 단축키, 기록 폴더 열기.

## 한계

- 뷰포트 회전·확대, Info 에디터가 보여주지 않는 일부 클릭은 기록되지 않습니다.
- `mode`/`obj`는 확인 주기만큼 늦게 읽어서, 동작 직후 모드를 바꾸면 다음 모드로 찍힐 수 있습니다.
- 좌하단 패널(F9)로 값을 고치면 같은 동작이 새 값으로 한 번 더 기록됩니다. 연속된 같은 동작은 마지막 값이 최종값입니다.
- 스크린샷은 PNG(장당 수백 KB)입니다. 발행할 때 줄여서 씁니다.

## 개발

```sh
python3 -m unittest discover -s tests   # compact.py 테스트 (블렌더 불필요)
blender --command extension build --source-dir . --output-dir /tmp
```

License: GPL-3.0-or-later
