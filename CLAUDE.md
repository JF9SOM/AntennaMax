# CLAUDE.md

このファイルは Claude Code がこのリポジトリで作業する際の指針です。作業前に必ず読み、
詳細は `docs/ARCHITECTURE.md` と `docs/ROADMAP.md` を参照すること。

## プロジェクト概要

MMANA に代わる、現代的な Python スタックによるアマチュア無線用アンテナシミュレーター。
(ソフト名: AntennaMax、Python パッケージ名: `antennamax`)

- 対象: ワイヤー / 八木 / ループ / LPDA / マグネチックループ / ヘリックス / QFH /
  パッチ等の平面アンテナ / パラボラ(HF〜衛星用マイクロ波帯)
- 単一ソルバーではなく、アンテナ種別ごとに適切なソルバーを使い分け、
  共通のジオメトリ記述で束ねる
- 電気モデルと 3D プリント部品を **同一パラメータから生成** する(Single Source of Truth)
- 自作に必要な「製作キット」(STL/STEP、寸法図、切断リスト、BOM、組立・調整ガイド)を出力する
- Linux / Windows / macOS の 3 OS を同等にサポートする

## 技術スタック

| 用途 | ライブラリ | 備考 |
|---|---|---|
| 言語 | Python >= 3.11 | PyNEC 2.4.0 の要件に合わせる |
| パッケージ管理 | uv | `uv sync`, `uv run` |
| ワイヤー系ソルバー | PyNEC (nec2++) | 必須依存 |
| 平面系ソルバー | openEMS (FDTD) | **オプション**。未インストールでも本体は動くこと |
| 反射鏡 | 自前の物理光学 (PO) 実装 (numpy) | |
| 数値計算 | numpy, scipy | |
| 設計ファイル | pydantic + PyYAML | `design.yaml` のスキーマ検証 |
| RF データ | scikit-rf | Touchstone 入出力, Smith チャート |
| 3D CAD | build123d (OCP) | extras `cad` |
| プロット | matplotlib | extras `plot`(`gui` にも含む)。`antennamax plot` |
| 3D 表示 | pyvista | extras `gui`。`antennamax view`(確認用表示) |
| GUI | PySide6 + pyvistaqt | extras `gui`。GUI アプリ(`antennamax gui`)を最優先で開発中 |
| 最適化 | scipy.optimize(必要なら optuna) | |
| テスト / Lint | pytest, ruff | |

## ディレクトリ構成

```
src/antennamax/
  core/        ジオメトリ基本要素(Wire, Helix, Plate, Substrate, Reflector)、材料、単位
  templates/   パラメトリック設計(dipole, yagi, magloop, qfh, helix, patch, dish)
  solvers/     base.py(共通IF), nec2.py, openems.py, po.py, analytic.py
  results/     Result 型, 指標計算(SWR, 利得, F/B, 軸比, RHCP/LHCP, 効率)
  mech/        build123d による 3D プリント部品生成
  buildkit/    製作キット出力(寸法図, 切断リスト, BOM, 手順書)
  io/          .nec 入出力, Touchstone(MMANA .maa 読込は将来の移行支援、優先度低)
  optimize/
  cli/
  viz/         描画データ生成(NumPy のみ), view(pyvista)/plot(matplotlib)
  gui/         GUI アプリ(PySide6)。計算ロジックは持たず既存コードを呼ぶだけ
designs/       コミュニティ設計の蓄積(design.yaml が唯一のソース)
tests/
docs/
```

## 設計上の規約

### 単位・座標
- 内部単位は **SI に統一**(m, Hz, Ω, rad)。mm や MHz は入出力境界でのみ変換する
- 座標系: 右手系、z 軸上向き、地面は z=0
- 角度は内部では rad。表示・ファイルでは deg 可

### ソルバー共通インターフェース
- すべてのソルバーは `solvers/base.py` の `Solver` プロトコルを実装する
  - `supports(geometry) -> bool`
  - `run(geometry, sweep) -> Result`
- ソルバー固有の処理(NEC カード生成など)を `core/` や `templates/` に漏らさない
- openEMS は import を遅延させ、未インストール時は `SolverUnavailableError` を投げる。
  本体の import やテストが openEMS に依存してはならない

### テンプレート
- テンプレートは「パラメータ(pydantic モデル)→ ジオメトリ」と
  「パラメータ → 機械部品」の両方を提供する
- 寸法は必ずパラメータから導出する。マジックナンバーを部品生成コードに直書きしない

### クロスプラットフォーム規約(最初のコミットから厳守)
- パス操作は `pathlib` のみ。文字列連結や `/` 決め打ち禁止
- 外部コマンド(`subprocess` でのシェル呼び出し)禁止。必要な場合は事前に相談
- multiprocessing は spawn 方式前提で書く(トップレベル関数, `if __name__ == "__main__"`)
- 一時ファイルは `tempfile` を使う
- ファイルの読み書きは `encoding="utf-8"` を明示する
- 改行コードは `.gitattributes` で管理

### 物理的な前提の扱い
- 検証していない物理的前提・近似・数値には `# TODO(要確認): ...` コメントを付け、
  `docs/VERIFICATION.md` に追記する
- 文献値を使う場合は出典をコメントに書く
- NEC の細線近似の適用条件(セグメント長と導体半径の比など)を外れる場合は
  警告を出す処理を入れる(具体的な閾値は要確認)

## 開発ワークフロー(重要)

1. **1 セッション 1 タスク**。指示された範囲外の変更をしない。範囲外の改善点は
   提案として報告するに留める
2. **コミット前に必ず diff を提示し、承認を得てからコミットする**。勝手にコミット・push しない
3. 新しい依存パッケージを追加する前に相談する
4. 同じエラーで 2〜3 回修正が失敗したら作業を止め、エラーログ・試したこと・仮説を
   まとめて報告する(ループしない)
5. 作業完了時は「やったこと / テスト結果 / 未解決・要確認事項」を報告する
6. コミットメッセージは英語、Conventional Commits 形式(`feat:`, `fix:`, `test:` 等)

## よく使うコマンド

```bash
uv sync --all-extras          # 依存インストール
uv run pytest                 # テスト
uv run ruff check . && uv run ruff format .
uv run antennamax --help          # CLI
```

## テストの方針

- ソルバーの結果は **既知の理論値・文献値** と比較するテストを書く
  (例: 自由空間の半波長ダイポール ≈ 73 + j42 Ω。許容誤差は導体半径依存のため緩めに)
- 文献値・実測値のリファレンスケースは `tests/reference/` に置く
- openEMS を要するテストは `@pytest.mark.openems` を付け、未インストール時は skip
- CI は Linux / Windows / macOS × Python 3.11 / 3.13 で回る。OS 依存の失敗を出さないこと

## 現在のフェーズ

**GUI アプリを最優先で開発中**(`docs/GUI.md`、`docs/ROADMAP.md` 参照)。基盤(P0)・確認用表示(view/plot)・QFH の製作キットは実装済み。
GUI は dipole / yagi / qfh の設計・計算・結果表示・保存を備える。計算は既存コードを呼ぶだけで、GUI 側に再実装しない。
openEMS・PO には着手しない。新しい部品は作らない。

## ライセンス

- コード: GPLv3(openEMS / nec2++ との組み合わせのため。正式決定はオーナーが行う)
- `designs/` の設計データ: CC BY-SA を想定(未決定)
