# design.yaml の形式

`antennamax run design.yaml` が読み込む設計ファイル。UTF-8 で保存すること。
未知のキーはエラーになる(タイプミス検出のため)。例は `examples/` を参照。

```yaml
template: yagi            # dipole | yagi
params:                   # テンプレートのパラメータ(下記)
  center_frequency_mhz: 144
  ...
sweep:
  start_mhz: 142
  stop_mhz: 146
  points: 5
pattern:                  # 省略すると放射パターンは計算しない
  resolution_deg: 10
```

## 単位表記

内部は SI(m, Hz)。値は `*_mm`(→ `*_m`)、`*_mhz`(→ `*_hz`)の別名でも書ける。
同じ量を複数の単位で書くとエラー。`params` の中でも、`sweep` でも同じ規則。

## template / params

### dipole(自由空間、素子は y 軸方向)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 中心周波数(必須) |
| `length_m` / `_mm` | 全長。省略時は 0.95 × λ/2(目安。VERIFICATION.md 参照) |
| `diameter_m` / `_mm` | 導体径(必須) |
| `segments` | 分割数。奇数。省略時は自動決定(下記)。指定時はそのまま使い、細線近似の警告のみ |

### yagi(自由空間、素子は y 軸に平行、ブームは x 軸)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 分割数決定に使う中心周波数(必須) |
| `elements` | 2 個以上のリスト。各要素: `position_m`/`_mm`(ブーム上の位置)、`length_m`/`_mm`(全長)、`diameter_m`/`_mm`(導体径) |
| `feed_index` | 給電エレメントの番号(0 始まり) |
| `segments_per_wavelength` | 波長あたりの目標分割数(既定 20)。全エレメント同一分割数 |

反射器から導波器の順に `position` を増やして並べる(主ビームは +x 方向)。
ブーム補正は未実装。

### qfh(四線ヘリカル、自由空間、軸は z、給電は上部)
| キー | 内容 |
|---|---|
| `center_frequency_hz` / `_mhz` | 周波数(必須) |
| `diameter_m` / `_mm` | 導体径(必須。補正係数は 15 mm で頭打ち) |
| `bend_radius_m` / `_mm` | 曲げ半径(必須。寸法計算のみ。NEC2 形状は直角) |
| `turns` | 巻き数(既定 0.5) |
| `width_height_ratio` | 幅/高さ比(既定 0.44) |
| `handedness` | `left`(既定、給電点が上で天頂向きに RHCP)または `right`(LHCP) |
| `speed_of_light_m_s` | 光速(既定 299792458。Coppens の原典に合わせるなら 3e8) |
| `segments_per_wavelength` / `max_frequency_*` | 分割数の自動決定(dipole と同じ) |

寸法式は Coppens (ON6JC) の方式を KF8EEZ が再実装したページに準拠(出典と未照合の点は
`templates/qfh.py` と VERIFICATION.md を参照)。大ループ・小ループの全長、補正後全長、D、Dc、
H、垂直部長は `Qfh.dimensions` で取得できる。

### 分割数の自動決定

`segments` を省略した dipole と、yagi は `core/segmentation.py` で分割数を決める。
最高周波数(掃引の上限。`max_frequency_hz`/`_mhz` を params で指定すれば優先)で評価する。

- 制約: セグメント長 < λ/10、かつ セグメント長/半径 Δ/a > 2(NEC2 拡張細線カーネルの下限)
- 目標密度(`segments_per_wavelength`)から N を決め、Δ/a の制約で上限を超えれば N を減らし、
  λ/10 で足りなければ N を増やす。中央給電のため奇数。yagi は全エレメント同一 N
  (最も厳しいエレメントで決める)
- 両立できない場合(例: 1296 MHz で直径 30 mm のエレメント)はエラー
  (`cannot segment this geometry for NEC2 ...`、終了コード 2)
- Δ/a < 8 になるときは拡張細線カーネルが自動で有効になる

## sweep

`start_*`、`stop_*`(MHz または Hz)、`points`(点数)。周波数は等間隔。
`points: 1` なら `start` の 1 点。`stop` は `start` 以上。

## pattern

`resolution_deg`: 角度分解能(deg)。180 と 360 を割り切る値のみ(例: 5, 10, 15, 30)。
θ は 0〜180°(両端含む)、φ は 0〜360° 未満。

## 出力

- 既定: ソルバー情報の行(拡張細線カーネルの on/off と最小 Δ/a)と、周波数ごとの R, X, SWR(Z0 = 50 Ω)の表。パターン計算時は最大利得、F/B(dB)、天頂(θ=0)の軸比 AR と RHCP/LHCP 利得(dBic)も表示。
  AR は円偏波 0 dB、直線偏波は inf(JSON では null)。
- `impedance`/`swr` は最初の給電点基準。給電点が複数のとき(Geometry の `feeds`)は
  `feed_impedances_*`(周波数×給電数)に全給電点が入り、表には注記が 1 行出る。
- `--json`: `{"template": ..., "result": {...}}`。`result` のキーは
  `frequencies_hz, z0, impedance_real, impedance_imag, feed_impedances_real,
  feed_impedances_imag, swr, theta_rad, phi_rad, gain_dbi,
  max_gain_dbi, front_to_back_db, zenith_axial_ratio_db, zenith_rhcp_gain_dbic,
  zenith_lhcp_gain_dbic, meta`(パターン未計算の項目は null)。`meta` はソルバー情報で、
  `solver`("nec2")、`extended_kernel`(拡張細線カーネルの使用有無)、
  `min_segment_to_radius`(全 Wire の最小 Δ/a)を含む。
  JSON は無限大を表せないため、SWR 無限大・完全ヌル(-inf)・F/B 無限大・AR 無限大・利得 -inf は
  `null` で出力する。
- 設計ファイルのエラーは標準エラー出力にメッセージを出し、終了コード 2 を返す。
- 細線近似の適用条件(セグメント長/半径 Δ/a < 8)を外れる Wire があると、標準エラー出力に
  `antennamax: warning: ...` を出す(Δ/a < 2 は拡張カーネルでも範囲外の強い警告)。
  `view` ではその Wire を黄色(Δ/a < 8)・赤(Δ/a < 2)で表示する。

## 3D プリント部品(`antennamax parts`)

`antennamax parts design.yaml --out DIR` は、設計から STL と STEP を DIR に出力し、部品の一覧
(名前、設置場所 `upper` / `lower_large` / `lower_small`、個数、上端からの距離、外形寸法。
同じ部品でも設置場所ごとに行を分け、距離は上部 0、下部は H1 / H2)と、用途ごとのねじ・ナットの数を表示する(extras `cad` が必要:
`uv sync --extra cad`)。今は template が `qfh` のものだけ対応し、他のテンプレートは「部品未対応」と
表示して終了コード 2。

支持部品は 2 つの構成から選べる(`--support integrated | hub-rod | auto`、既定 `auto`)。`auto` は
一体型の部品がすべて造形範囲に収まれば一体型、超えるとハブ + 棒の構成にする(一覧の先頭行
`Support: ...` に選んだ構成と理由を表示)。

- **一体型(integrated)**: スプレッダー(十字形の板)と押さえ板。435 MHz のような小型向け。
- **ハブ + 棒(hub-rod)**: マストに付けるハブ、市販の絶縁棒(グラスファイバー等、印刷しない)、棒の先に
  付ける導体固定具(溝 + 押さえ板)。137 MHz 帯のような大型向け。棒の長さは一覧に表示される
  (棒の長さ = 固定具の差し込み穴の底の位置 − ハブの差し込み穴の底の位置)。

共通: 導体は半円の溝に置き、押さえ板(下面にも半円溝)で上から挟む。上下の溝で「導体径 + クリアランス」の
円形の通り道になる。押さえ板は M3 ねじ 2 本で固定し、本体の下面に六角ナットのポケットがある。溝と押さえ板は
中心から Dc/2(Dc = D − 2R、曲げ補正後)まで。その外側は導体を曲げるための逃げ。

| 部品 | 個数 | 内容 |
|---|---|---|
| `qfh_upper_spreader` | 1 | 4 本腕(0°/180° 大ループ、90°/270° 小ループ)、中央にマスト穴。上端(上端からの距離 0) |
| `qfh_lower_spreader_large` | 1 | 大ループの下部の棒(x 方向)。溝は端から端まで連続し、マスト穴を横切る。上端から H1 |
| `qfh_lower_spreader_small` | 1 | 小ループの下部の棒(y 方向)。上端から H2 |
| `qfh_clamp_large` | 4 | 大ループ用の押さえ板(上部 2 + 下部の棒 2) |
| `qfh_clamp_small` | 4 | 小ループ用の押さえ板(上部 2 + 下部の棒 2) |

ハブ + 棒の部品(137.5 MHz):

| 部品 | 個数 | 内容 |
|---|---|---|
| `qfh_hub_upper` | 1 | マスト穴 + 棒の穴 4 方向 + 各腕の溝(上端。マスト穴の縁から余白を取って始まる) |
| `qfh_hub_lower_large` / `qfh_hub_lower_small` | 各 1 | マスト穴 + 棒の穴 2 方向 + 端から端までの溝(マスト穴を横切る)。上端から H1 / H2 |
| `qfh_fixture` | 8 | 棒に差し込む穴(M3 ねじ 1 本で固定)+ 導体の溝(外端は Dc/2) |
| `qfh_hub_clamp` | 8 | ハブの溝の押さえ板(ねじは棒の抜け止めのナットポケットと干渉しない位置) |
| `qfh_fixture_clamp` | 8 | 固定具の溝の押さえ板 |
| 棒(印刷しない) | 大ループ用 4、小ループ用 4 | 長さは一覧に表示 |

導体は各腕の 2 か所(ハブと固定具)で、溝と押さえ板に挟まれる。その間は棒の上を渡る。

**マスト固定**: スプレッダー・ハブのマスト穴に、M3 の止めねじ(ナットポケット付き)を腕の間(45°/135°)に
`mast_screws_per_part` 本(既定 2、1〜4)入れる。ナットはマスト穴の縁から壁厚ぶん外側のポケットにスロットから
落とし込む。一体型のハブは、ポケットの壁のためハブの壁を厚くし、ハブだけ板厚を増やす(ボス)。

**ドリルガイド**(`qfh_drill_guide_large` / `qfh_drill_guide_small`): マストにはめるカラー。下部の導体が
マストを貫通する穴(大ループ用が上端から H1、小ループ用が H2)の位置を示す。ガイド穴の径は導体径 + クリアランス、
マストの直径方向に貫通し、向きは大ループ用が x 方向、小ループ用が y 方向(90° ずれる)。基準寸法は
「カラー上面からガイド穴中心まで」(既定 4.8 mm)で、一覧に「カラー上面を上端から (H − 4.8) mm の位置に
置く」と表示される。上面の +x 側の切り欠き(ノッチ)を、上部スプレッダーの +x 腕の向きに合わせて使う。カラーには M3 止めねじ
1 本(ナットポケット付き、ガイド穴とノッチから離れた位置)でマストに固定する。

**向きの目印**: 上部スプレッダー・下部スプレッダー・ハブの +x 側のリム下端に、ドリルガイドのノッチと同じ幅の
切り欠きがある。+x は大ループの腕の向きで、ハブ + 棒では +x のソケット(と反対側)が大ループ用、±y が小ループ用。

**From top**: 一覧の From top は、上部の導体面(上部スプレッダー / ハブの溝の面)から下向きの距離。
ドリルガイドのガイド穴とカラー上面の位置(H − 4.8 mm)も同じ基準で表示される。

必要なねじ・ナットは用途ごとに一覧に表示される(一体型: 押さえ板用 M3 16 本 + マスト用 6 本 +
ドリルガイド用 2 本の計 24 本。ハブ + 棒: ハブの押さえ板 16 本、固定具の押さえ板 16 本、ハブの棒の抜け止め 8 本、
固定具の棒止め 8 本、マスト用 6 本、ドリルガイド用 2 本の計 56 本)。

- `--clearance-mm`(既定 0.2): 溝・ねじ穴・ナットポケット・マスト穴の共通クリアランス。
- `--mast-diameter-mm`(既定 26、VP20 相当)。
- `--rod-diameter-mm`(既定 8)、`--rod-insert-depth-mm`(既定 20): ハブ + 棒の構成の棒の径と差し込み深さ。
  棒の穴径は棒の径 + クリアランス。ハブの各穴に抜け止めの M3 ねじ(ナットポケット付き)が 1 本ずつ。
- `--build-volume-mm X Y Z`(既定 220 220 250): 部品が造形範囲を超えると、どの部品がどれだけ超えるかを
  標準エラー出力に警告する(終了コードは 0)。
- 寸法は QFH の `dimensions`(D、Dc、H)から取り、部品の外形は mm の STL/STEP。内部のパラメータは
  SI(`*_mm` 表記も可)。
