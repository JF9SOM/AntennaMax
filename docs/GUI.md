# GUI アプリ

## 起動

```bash
uv sync --extra gui          # PySide6 / pyvista / pyvistaqt / matplotlib
uv run antennamax gui                              # 空の設計(dipole)で起動
uv run antennamax gui examples/yagi3_144mhz.yaml   # 設計ファイルを開いた状態で起動
```

設計ファイルを渡すと開いた直後に自動で計算する。

## 画面

- 左: テンプレート(dipole / yagi / qfh)、パラメータ(pydantic モデルから自動生成。mm・MHz で入力)、
  yagi のエレメント表、周波数掃引とパターン分解能、「Calculate」ボタン
- 右のタブ: 3D view(形状と放射パターン。マウスで回転・拡大)、SWR and R/X、Patterns(水平面・垂直面)、
  Summary(Z、SWR、最大利得、F/B、天頂の軸比、RHCP/LHCP)、Warnings
- File メニュー: 設計ファイルを開く・保存、結果の JSON 出力、QFH の parts 出力(STL/STEP。`cad` extra が必要)

見た目は全 OS で揃える(`gui/theme.py`): Fusion スタイル、ライト/ダークのパレット(上部の View メニューで切替。OS の設定には従わず、選択は次回起動時にも保持)、フォントサイズ 16 px(pt だと OS で大きさが変わるため px)。
メニューバーは macOS でもウィンドウの中に表示する(OS 共通のメニューバーは使わない)。
フォントの種類だけは OS 既定のまま(OS ごとに多少異なる)。

不正な入力は該当欄の下に赤字で表示され、計算は始まらない。

## 構成

`src/antennamax/gui/`

| ファイル | 役割 |
|---|---|
| schema.py | pydantic モデルからフォーム項目を生成(単位は名前の接尾辞から) |
| state.py | フォーム値 ⇔ 設計マッピング、検証(`io.design.parse_design`)、エラーの振り分け |
| calc.py | 計算の実行(既存の `simulate`)。別プロセスのワーカー |
| summary.py | 結果の要約表 |
| widgets.py / window.py | Qt ウィジェット、メインウィンドウ |

計算は既存コード(`parse_design` → `viz.data.simulate`、parts は CLI の `parts`)を呼ぶだけで、
GUI 側には再実装しない。PyNEC は GIL を解放しないため、計算は spawn した別プロセスで行う。

## 環境変数

- `ANTENNAMAX_GUI_BACKEND=thread|process`(既定 process): 計算ワーカーの種類(テストは thread)
- `ANTENNAMAX_GUI_3D=0`: 対話的 3D 表示を無効にする(OpenGL のない環境向け)
- `ANTENNAMAX_TEST_3D=1`: 3D 表示のテストを有効にする(表示のある環境のみ)

## テスト

```bash
uv sync --extra dev --extra gui --extra gui-test
uv run pytest tests/test_gui_state.py tests/test_gui_window.py   # offscreen で動く
```

CI では `gui` ジョブ(3 OS × Python 3.11 / 3.13)で `QT_QPA_PLATFORM=offscreen` として実行する。
3D 表示(VTK/OpenGL)は CI では無効。
