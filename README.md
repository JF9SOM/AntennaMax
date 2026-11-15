# AntennaMax

アマチュア無線用の現代的なアンテナシミュレーター。MMANA の後継を目指す。

- ワイヤー / 八木 / マグネチックループ / ヘリックス / QFH / パッチ / パラボラ
- NEC2(PyNEC)・openEMS・物理光学法を用途に応じて使い分け
- 3D プリント部品(STL/STEP)と製作キット(寸法図・切断リスト・BOM・調整ガイド)を出力
- Linux / Windows / macOS 対応

> 開発初期段階(P0)。詳細は [docs/ROADMAP.md](docs/ROADMAP.md) を参照。

## 開発

```bash
uv sync --all-extras
uv run pytest
```

## ライセンス

コード: GPLv3(予定) / 設計データ(designs/): CC BY-SA(予定)
