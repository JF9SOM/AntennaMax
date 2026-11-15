# ロードマップ

各フェーズは「完了条件」をすべて満たしてから次へ進む。

## P0: 基盤 + NEC2 バックエンド(現在)

- [ ] プロジェクト雛形(uv, pyproject.toml, ruff, pytest, .gitattributes)
- [ ] CI: Linux / Windows / macOS × Python 3.11 / 3.13
- [ ] `core/`: 単位変換、Wire、ジオメトリコンテナ
- [ ] `solvers/base.py`: Solver プロトコル、Sweep、SolverUnavailableError
- [ ] `solvers/nec2.py`: PyNEC によるインピーダンス・パターン計算
- [ ] `results/`: Result 型、SWR・利得・F/B
- [ ] `templates/`: dipole, yagi
- [ ] `io/`: MMANA .maa 読み込み
- [ ] `cli/`: `antennamax run design.yaml`

完了条件:
- 半波長ダイポールのインピーダンスが理論値に近いテストが通る
- 既知の八木設計で MMANA と比較したリファレンステストが通る
- 3 OS の CI がグリーン

## P1: 進行波・ループ系 + 3D プリント + 製作キット

- [ ] テンプレート: helix, qfh, magloop
- [ ] 偏波指標(軸比、RHCP/LHCP)
- [ ] マグループ指標(効率、Q、帯域、コンデンサ電圧・電流)
- [ ] NEC 細線近似の適用条件チェックと警告
- [ ] `mech/`: build123d による部品生成(まず QFH)
- [ ] `buildkit/`: 寸法図、切断リスト、BOM、調整ガイド(感度解析)
- [ ] 嵌合クリアランス設定、テストピース、大型部品の分割
- [ ] `designs/` の構造と CI による STL 再生成

完了条件: QFH 1 設計について製作キット一式が出力される

## P2: openEMS バックエンド(平面アンテナ)

- [ ] `solvers/openems.py`(遅延 import、プラグイン扱い)
- [ ] テンプレート: patch(FR-4 等の基板定義)
- [ ] 基板データ出力(DXF / KiCad フットプリント)
- [ ] OS 別 openEMS 導入ドキュメント

完了条件: 自作 L バンドパッチ(FR-4)の実測値との比較

## P3: パラボラ

- [ ] `solvers/po.py`(物理光学法)
- [ ] 給電部パターン(NEC/openEMS/解析式 cos^q)との結合
- [ ] 開口効率、スピルオーバー、ブロッキング
- [ ] 給電部マウント部品

## P4: GUI + 最適化 + 配布

- [ ] PySide6 + pyvistaqt による GUI(寸法編集、3D 表示、パターン、Smith チャート)
- [ ] 最適化(scipy / optuna)
- [ ] PyInstaller / Briefcase による OS 別インストーラー

## 範囲未決定

- マグループのリモートチューナー(ステッピングモーター部品・制御)
