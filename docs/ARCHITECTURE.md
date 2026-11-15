# アーキテクチャ

## 全体のデータフロー

```
design.yaml ──▶ Template(pydantic パラメータ)
                    │
        ┌───────────┴────────────┐
        ▼                        ▼
   Geometry(core)           Mechanical parts(mech: build123d)
        │                        │
        ▼                        ▼
   Solver(nec2 / openems /   STL / STEP / 3MF
          po / analytic)         │
        │                        │
        ▼                        │
   Result ──────────┬────────────┘
                    ▼
              BuildKit(寸法図・切断リスト・BOM・手順書・調整ガイド)
```

## アンテナ種別とソルバー

| 対象 | ソルバー | 理由・注意 |
|---|---|---|
| ワイヤー、八木、ループ、LPDA、ヘリックス、QFH、マグループ | NEC2(PyNEC) | 細線モーメント法。Sommerfeld 地面モデル |
| パッチ等の平面、誘電体基板あり | openEMS(FDTD) | NEC は誘電体基板を扱えない。オプション依存 |
| パラボラ | 物理光学(PO)自前実装 + 給電部パターン(NEC/openEMS) | 電気的に巨大で MoM/FDTD は非現実的 |
| 全種別の概算 | analytic(解析式) | 本格計算前の即時見積もり |

## Result に含める指標

- 入力インピーダンス Z、SWR(基準インピーダンス指定可)、S11
- 放射パターン(θ/φ グリッド)、最大利得、F/B、F/R、ビーム幅
- 偏波: 軸比、RHCP / LHCP 利得(衛星用途の差別化ポイント)
- 効率(放射抵抗と損失抵抗の分離)— マグループで必須
- マグループ専用: Q、帯域幅、コンデンサ電圧・電流(送信電力指定時)
- 出力: JSON, Touchstone(scikit-rf), .nec

## マグネチックループのモデル化

- ループ本体: 多角形ワイヤー + 導体損失(NEC LD type 5)
- チューニングコンデンサ: 集中定数 C(LD カード)+ ESR / Q による直列抵抗
- 給電: ファラデーループ / ガンマを別ワイヤーとしてモデル化(誘導結合)
- 解析式(Rr ≈ 31171·(A/λ²)² Ω 等)と NEC 結果を並べて提示
- 既知の弱点(VERIFICATION.md 参照): 近接効果、太導体の細線近似、極小ループの数値精度

## 製作キット(BuildKit)の出力物

テンプレート由来の設計のみフルサポート。自由形状は寸法表・BOM のみ。

| 種類 | 内容 | 形式 |
|---|---|---|
| 3D プリント部品 | 本体部品、曲げ治具(QFH)、巻き治具(ヘリックス)、ドリルガイド | STL / 3MF / STEP |
| 寸法図 | 1:1 印刷用型紙、穴位置テンプレート | PDF / SVG / DXF |
| 切断リスト | エレメント長、同軸位相線長(短縮率考慮)、切りしろ | PDF / CSV |
| BOM | 材料仕様(パイプ径、同軸種類、コネクタ、ネジ規格) | CSV |
| 基板(パッチ) | 製造用データ | DXF / KiCad フットプリント |
| 組立手順 | 分解図 + 工程 | PDF(最初はテンプレートごとの手書き雛形に寸法を差し込む) |
| 調整ガイド | 寸法感度解析(1 mm あたりの周波数変化)、NanoVNA 目標波形 | PDF / Touchstone |

3D プリント関連の共通機能:
- プリンターごとの嵌合クリアランス設定とテストピース出力
- 造形範囲を超える部品の自動分割(継ぎ手付き)
- 材料推奨(屋外は ASA / PETG 等)の注記

## designs/ ディレクトリ(コミュニティ設計の蓄積)

```
designs/<type>/<variant>/
  design.yaml      ← 唯一のソース(手で管理)
  result.json      ← シミュレーション結果要約(CI 生成)
  measured.json    ← 実測値(任意。NanoVNA 等)
  parts/           ← STL / STEP / preview.png(CI 生成)
```

- CI(GitHub Actions)が design.yaml から生成物を再生成する
- 実測値を蓄積し、シミュレーションとの比較データベースにする

## クロスプラットフォーム配布

- 本体(NEC2 + CAD + GUI)は 3 OS で wheel のみで導入可能な依存に限定
- openEMS はプラグイン扱い。OS 別導入手順をドキュメント化
- 配布: 開発者向け `pip` / `uv`、一般向けに PyInstaller または Briefcase で OS 別インストーラー(P4 以降)

### 依存ライブラリの配布状況(2026-11 時点で確認)

- PyNEC 2.4.0: Windows x86-64 / Linux x86-64 / macOS ARM64・x86-64 の wheel あり。
  Python >= 3.11。Windows ARM64・Linux ARM64 の wheel はなし
- cadquery-ocp 7.9.3.1: Windows x86-64 / Linux ARM64 / macOS ARM64・x86-64 の wheel を確認
  (実際の `uv sync --extra cad` では `cadquery-ocp-novtk 8.0.1.1.0` + build123d 0.13.0 が導入され、
  Linux x86-64 を含む 3 OS × Python 3.11/3.13 の CI で動作を確認。docs/VERIFICATION.md 参照)
  (Linux x86-64 は要確認)
- openEMS: Windows は MSVC ビルド版を利用、macOS は Homebrew でソースビルド後に
  Python モジュールを手動インストール
